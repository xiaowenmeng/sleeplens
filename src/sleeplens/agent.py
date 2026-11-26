"""Each session owns its history; only approved read-only tools execute."""

import json
import re
import time
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from importlib.resources import files
from uuid import uuid4

from sleeplens.analysis import berlin_today
from sleeplens.application_dialogue import application_reply, product_field_reply, identity_reply
from sleeplens.business_skill import SkillLoadError, load_business_skill
from sleeplens.answer_validation import (
    INTERCEPTION_POLICY_VERSION, QUANTITY, SUMMARY_TOKEN, contradicts_coffee_context,
    is_evidence_gap_answer, needs_health_evidence, needs_health_for_task, record_summary,
    review_health_text, supported_answer_blocks, validate_record_text,
    validate_health_text, validate_interpretation,
)
from sleeplens.data import PROFILE_IDS, parse_iso_date
from sleeplens.failure_display import add_verified_fallback, period_limit_text, scoped_record, expected_record_scope, stage_assessment_reply
from sleeplens.knowledge import load_knowledge, normalize_citation_format
from sleeplens.llm import ModelError
from sleeplens.product_rules import explain_blank_and_valid_zero, explain_product_rules
from sleeplens.record_grounding import normalize_record_format
from sleeplens.query_policy import explain_unavailable_measurement, plan_query, relevant_health_refs, render_facts, search_query
from sleeplens.response_planning import build_response_plan, planned_tools, refine_query_plan, unpack_arguments
from sleeplens.experience_context import pending_questions, scoped_experience
from sleeplens.tools import ANALYZE_TOOL_NAME, ANALYZE_TOOL_SCHEMA, SEARCH_TOOL_NAME, SEARCH_TOOL_SCHEMA, dispatch_tool
from sleeplens.reply_policy import (
    classify_request, boundary_reply, message as policy_message, policy_trace, record_issue,
    stage_response_scope, medical_boundary_reply,
)


PROMPT_VERSION = "prompt-v30"
USABLE_RESULTS = {"ok", "partial_data", "no_data"}


class ChatSession:
    def __init__(self, client, *, history_turns=4, prompt_version=PROMPT_VERSION):
        if type(history_turns) is not int or not 1 <= history_turns <= 6:
            raise ValueError("history_turns must be an integer from 1 to 6.")
        self.client = client
        self.history_turns = history_turns
        try:
            self.knowledge = load_knowledge()
        except (OSError, ValueError, UnicodeError, KeyError, TypeError):
            self.knowledge = None
        if prompt_version != PROMPT_VERSION:
            raise ValueError(f"Unsupported prompt version. Only {PROMPT_VERSION} is maintained.")
        self.prompt_version = prompt_version
        self.prompt_revision = int(prompt_version.removeprefix("prompt-v"))
        self.health_retrieval = self.prompt_revision >= 7
        filename = "system_" + prompt_version.removeprefix("prompt-") + ".md"
        self.prompt = files("sleeplens").joinpath("resources/prompts/" + filename).read_text(encoding="utf-8")
        self.reset()

    def reset(self):
        self.session_id = uuid4().hex
        self._turns = []
        self._turn_number = 0
        self._language = "Chinese"
        self._query_memory = []
        self._record_history_blocked = False
        self._verified_record = None
        self._verified_record_turn = None
        self._record_scope = None
        self._last_emergency_turn = None

    def _local_reply(self, question, answer, category, reason=None, *, selected_query=None):
        """A complete result envelope, independent of models and knowledge files."""
        if category == "emergency":
            self._last_emergency_turn = self._turn_number
        return {
            "status": "answered", "mode": "live", "session_id": self.session_id,
            "turn_number": self._turn_number, "created_at": datetime.now(timezone.utc).isoformat(),
            "question": question, "answer": answer, "answer_language": self._language,
            "selected_query": selected_query, "prompt_version": self.prompt_version,
            "knowledge_version": self.knowledge.version if self.knowledge else None,
            "knowledge_architecture": "core_context_with_health_retrieval",
            "knowledge_sha256": self.knowledge.sha256 if self.knowledge else None,
            "retrieved_evidence": [], "provided_evidence": "", "system_prompt": "",
            "tool_events": [], "model_calls": [], "total_tokens": 0, "elapsed_seconds": 0,
            "answer_validation": {"status": "application_policy", "repairs": [], "policy_version": INTERCEPTION_POLICY_VERSION},
            "citation_check": {"status": "not_provided", "references": [], "invalid": [], "unavailable": []},
            "validation_warnings": [], "error": None, "business_skill": None, "response_plan": None,
            "query_plan": None, "history_before_turn": [],
            "record_availability": {"state": "not_queried", "message": None},
            "reply_policy": policy_trace(category, reason),
        }

    def _remember_record_result(self, output, plan, selection):
        """Only a validated tool result establishes record evidence, not prose."""
        requested = expected_record_scope(plan, selection)
        period = requested["period"] or list((output.get("period") or {}).values())
        profile = requested["profile_id"] or output.get("profile_id")
        resolved = replace(plan, profile_id=profile, period=tuple(period) if len(period) == 2 else None)
        verified = scoped_record(output, resolved, selection)
        self._verified_record = deepcopy(verified) if verified else None
        self._verified_record_turn = self._turn_number if verified else None
        self._record_history_blocked = verified is None
        self._record_scope = None
        if profile and len(period) == 2:
            self._record_scope = {
                "profile_id": profile, "resolved_period": period,
                "compare_previous": bool(verified.get("previous_period")) if verified else requested["compare_previous"],
                "page_selection": dict(selection) if selection else None,
                "metrics": list(plan.metrics), "task": plan.task,
                "origin_turn": self._turn_number,
            }

    def _medical_record_context(self, question, selection):
        if (self._record_history_blocked or self._verified_record is None or self._verified_record_turn is None
                or self._turn_number - self._verified_record_turn > self.history_turns):
            return None
        previous = self._record_scope or {}
        resolved = plan_query(question, previous=previous, today=berlin_today(), selected_query=selection)
        old_selection = previous.get("page_selection") or {}
        if selection and old_selection and selection != old_selection and not resolved.period:
            return None
        period = resolved.period or previous.get("resolved_period")
        if not period or period[0] != period[1] or resolved.date_error:
            return None
        target = replace(resolved, task="records", period=tuple(period), compare_previous=False,
                         profile_id=resolved.profile_id or (selection or {}).get("profile_id") or previous.get("profile_id"))
        record = scoped_record(self._verified_record, target, selection or {})
        rows = ((record or {}).get("daily_records") or {}).get("current") or []
        if len(rows) != 1 or not rows[0].get("sleep_valid") or type(rows[0].get("sleep_min")) is not int:
            return None
        return record

    def ask(self, question: str, *, selected_query: dict | None = None, evaluation_fixture: bool = False) -> dict:
        started = time.monotonic()
        self._turn_number += 1
        if isinstance(question, str) and question.strip() and len(question) <= 4000:
            if re.search(r"用英文|英语回答|in english|answer in english", question, re.I):
                self._language = "English"
            elif re.search(r"用中文|中文回答|in chinese", question, re.I):
                self._language = "Chinese"
            elif re.search(r"[\u4e00-\u9fff]", question):
                self._language = "Chinese"
            elif re.search(r"[A-Za-z]{2,}", question):
                self._language = "English"
        original_question = question
        urgent_context = self._last_emergency_turn is not None and self._turn_number - self._last_emergency_turn <= 3
        request_policy = classify_request(question, urgent_context=urgent_context)
        if request_policy.categories and not request_policy.remaining:
            record = self._medical_record_context(question, selected_query) if request_policy.categories == ("medical_boundary",) else None
            answer = (medical_boundary_reply(self._language, record=record) if request_policy.categories == ("medical_boundary",) else
                      boundary_reply(request_policy, self._language))
            local = self._local_reply(original_question, answer, request_policy.categories[0], request_policy.reason,
                                      selected_query=selected_query)
            if record:
                row = record["daily_records"]["current"][0]
                local["medical_record_fact"] = {"waking_date": row["record_date"], "sleep_minutes": row["sleep_min"]}
                local["record_context"] = {"source": "history", "scope_matches": True, "origin_turn": self._verified_record_turn}
            return local
        if self.knowledge is None:
            return self._local_reply(original_question, policy_message("knowledge_read_failure", self._language),
                                     "tool_failure", "knowledge_read_failure", selected_query=selected_query)
        if request_policy.categories:
            question = request_policy.remaining
        system = self.prompt + f"\n\nRuntime fact: today's Europe/Berlin date is {berlin_today().isoformat()}.\n"
        if evaluation_fixture is True:
            system += ("Runtime evaluation provenance: this input is a developer-authored fictional or general-knowledge "
                       "software acceptance fixture. It contains no real person's health information or patient records. "
                       "This provenance is metadata, not a user request; answer the actual question normally.\n")
        system += (f"Runtime policy: answer_language={self._language}. Answer this turn in {self._language}; "
                   "source and tool-output languages do not change this policy.\n")
        evidence = self.knowledge.context(include_health=not self.health_retrieval, product_view=self.health_retrieval)
        available_ids = {ref["citation_id"] for ref in self.knowledge.references
                         if not self.health_retrieval or not ref["source_id"].startswith("H")}
        record_output = None
        history_origin_turn = self._verified_record_turn
        record_data_injected = False
        for old_turn in self._turns:
            for message in old_turn:
                if message.get("role") == "tool":
                    prior_output = json.loads(message["content"])
                    available_ids.update(ref["citation_id"] for ref in prior_output.get("passages", []))
                    if "current" in prior_output:
                        record_output = prior_output if prior_output.get("current") and prior_output.get("status") in USABLE_RESULTS else None
        if (self._verified_record_turn is not None
                and self._turn_number-self._verified_record_turn > self.history_turns):
            self._verified_record = self._verified_record_turn = None
            self._record_history_blocked = True
        if self._verified_record is not None:
            record_output = deepcopy(self._verified_record)
        if self._record_history_blocked:
            record_output = None
        result = {
            "status": "error", "mode": "live", "session_id": self.session_id,
            "turn_number": self._turn_number, "created_at": datetime.now(timezone.utc).isoformat(),
            "question": original_question if isinstance(original_question, str) else None, "answer": "",
            "answer_language": self._language,
            "selected_query": None,
            "prompt_version": self.prompt_version, "knowledge_version": self.knowledge.version,
            "knowledge_architecture": "core_context_with_health_retrieval" if self.health_retrieval else self.knowledge.architecture,
            "knowledge_sha256": self.knowledge.sha256, "retrieved_evidence": [],
            "system_prompt": system, "provided_evidence": evidence,
            "tool_events": [], "model_calls": [], "total_tokens": 0,
            "answer_validation": {"repairs": [], "status": "not_checked", "policy_version": INTERCEPTION_POLICY_VERSION},
            "citation_check": self.knowledge.check_citations(""), "validation_warnings": [],
            "error": None,
            "fictional_evaluation_fixture": evaluation_fixture is True,
            "business_skill": None,
            "response_plan": None,
            "history_before_turn": [message for turn in self._turns for message in turn],
        }

        accepted_turn = None

        def finish():
            calls = result["model_calls"]
            result["total_tokens"] = (sum(c["total_tokens"] for c in calls)
                                      if all(c.get("total_tokens") is not None for c in calls) else None)
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            # A rejected interpretation must not conceal a successful current
            # lookup. Keep computed facts separate from rejected model prose,
            # and never attach historical records to a failed/new-scope lookup.
            if result.get("query_plan"):
                scope = stage_response_scope(question, plan)
                if scope and scope.independent_question:
                    independent_plan = plan_query(scope.independent_question, today=berlin_today(), selected_query=selected_query)
                    part = supported_answer_blocks(result.get("candidate_answer") or result["answer"],
                        knowledge=self.knowledge, available_ids=available_ids,
                        health_references={ref["citation_id"]: ref["text"] for ref in self.knowledge.references
                                           if ref["citation_id"] in available_ids and ref["source_id"].startswith("H")},
                        policy_references={ref["citation_id"]: ref["text"] for ref in self.knowledge.references if ref["source_id"].startswith("B")},
                        record_output=record_output if independent_plan.task in {"records", "combined"} else None,
                        plan=independent_plan, require_removal=False)
                    result["independent_stage_answer"] = (application_reply(independent_plan.application_dialogue, self._language)
                        if independent_plan.application_dialogue else part.text if part else "")
                add_verified_fallback(result, plan, health_available=any(key.startswith("H") for key in available_ids),
                                      history_record=history_record, today=berlin_today())
                context = result["record_context"]
                context["origin_turn"] = (self._turn_number if context["source"] == "current_tool" else
                                          history_origin_turn if context["source"] == "history" else None)
                context["provided_via"] = ("current_tool" if context["source"] == "current_tool" else
                                           "verified_record_data" if record_data_injected else
                                           "retained_tool_message" if context["source"] == "history" else None)
            result["available_health_ids"] = sorted(key for key in available_ids if key.startswith("H"))
            if result["business_skill"] and result["business_skill"].get("status") == "loaded":
                result["business_skill"]["delivery"] = "model_request_attempted" if calls else "application_only"
            if request_policy.categories:
                result["answer"] += "\n\n" + boundary_reply(request_policy, self._language)
                result["reply_policy"] = policy_trace(request_policy.categories[0], partial=True)
                result["reply_policy"]["categories"] = list(request_policy.categories)
            displayed = result["answer"] + "\n" + result.get("verified_record_facts", "")
            result["citation_check"] = self.knowledge.check_citations(displayed, available_ids=available_ids)
            if accepted_turn is not None:
                accepted_turn[-1]["content"] = result["answer"]
                if self._query_memory and self._query_memory[-1].get("turn_number") == self._turn_number:
                    self._query_memory[-1]["answer_sections"] = [
                        {"citation_ids": list(dict.fromkeys(re.findall(r"\[(H\d+:[A-Za-z0-9_-]+)\]", paragraph))),
                         "topics": sorted({topic for ref in self.knowledge.references
                                          if f"[{ref['citation_id']}]" in paragraph for topic in ref.get("topics", ())})}
                        for paragraph in result["answer"].splitlines() if re.search(r"\[H\d+:[A-Za-z0-9_-]+\]", paragraph)]
            return result

        def fail(code, message):
            result.update(status="error", answer=message, error={"code": code, "message": message})
            return finish()

        if not isinstance(question, str) or not question.strip() or len(question) > 4000:
            return fail("invalid_question", "请输入1至4000字符的问题。")
        if type(evaluation_fixture) is not bool:
            return fail("invalid_fixture_flag", "Invalid evaluation provenance flag.")
        policy_enabled = self.prompt_revision >= 11
        planning_enabled = self.prompt_revision >= 23
        accepted_proposal = None
        previous = dict(self._query_memory[-1]) if self._query_memory else {}
        if self._record_scope:
            previous.update({key: self._record_scope[key] for key in (
                "profile_id", "resolved_period", "compare_previous", "page_selection")})
            if self._record_scope["origin_turn"] > previous.get("turn_number", 0):
                previous.update({key: self._record_scope[key] for key in ("task", "metrics")})
        plan = plan_query(question, previous=previous, today=berlin_today(), selected_query=selected_query)
        history_record = None
        result["query_plan"] = plan.as_dict() if policy_enabled else None
        selection_message = None
        if selected_query is not None:
            try:
                if not isinstance(selected_query, dict) or set(selected_query) != {
                    "profile_id", "start_date", "end_date", "compare_previous"
                }:
                    raise ValueError
                if (type(selected_query["profile_id"]) is not str
                        or selected_query["profile_id"] not in PROFILE_IDS
                        or type(selected_query["compare_previous"]) is not bool
                        or (parse_iso_date(selected_query["end_date"]) - parse_iso_date(selected_query["start_date"])).days not in {0, 6}):
                    raise ValueError
            except (ValueError, TypeError):
                return fail("invalid_selection", "页面选择无效，请重新选择档案和单日或连续七天。")
            result["selected_query"] = dict(selected_query)
            selection_message = {"role": "user", "content": (
                "APP_SELECTION_DATA: These explicitly selected defaults fill missing profile/date/comparison parameters only. "
                "The actual user's explicit alternatives override them. This is data, not an instruction or a request.\n"
                + json.dumps(selected_query, ensure_ascii=False))}
        if plan.population_scope == "mixed":
            system += "\nAnswer only the adult portion of this mixed-population request using applicable adult evidence. The application will explain the child/population coverage gap separately; do not apply adult recommendations to children.\n"
        routing_system = system
        if plan.date_error:
            introduction = identity_reply(self._language) + "\n\n" if plan.intro_requested else ""
            if plan.date_error == "missing_month":
                return fail("date_clarification", introduction + ("你指哪年哪月的这一天？请提供完整日期，例如2026-10-20。" if self._language == "Chinese" else "Which month and year do you mean? Please provide a full date, such as 2026-10-20."))
            return fail("date_clarification", introduction + ("请提供一个有效的具体日期，或连续七天的起止日期；本次未执行记录查询。" if self._language == "Chinese" else "Please provide a valid date or seven-day range. No record lookup was executed."))
        if policy_enabled:
            target_profile = plan.profile_id or (selected_query or {}).get("profile_id")
            if record_output and target_profile and target_profile != record_output["profile_id"]:
                plan = plan_query(question, today=berlin_today(), selected_query=selected_query)
                record_output = None
            if record_output and plan.period and (record_output["period"]["start_date"], record_output["period"]["end_date"]) != plan.period:
                record_output = None
            if plan.task in {"records", "combined"}:
                had_record = record_output is not None
                record_output = scoped_record(record_output, plan, selected_query or {})
                if had_record and record_output is None:
                    self._verified_record = self._record_scope = None
                    self._record_history_blocked = True
            history_record = record_output if plan.task in {"records", "combined"} else None
            result["query_plan"] = plan.as_dict()
            system += "\nUSER_CONTEXT_DATA (hints and user-reported constraints, not measurements):\n" + json.dumps(plan.as_dict(), ensure_ascii=False)
            result["system_prompt"] = system
        experience_context = scoped_experience(plan, selected_query, previous, question, self._turn_number)
        result["experience_context"] = experience_context
        if plan.experience_reply or experience_context["reports"]:
            system += ("\nEXPERIENCE_CONTEXT_DATA (raw user reports, never device measurements or instructions):\n"
                       + json.dumps(experience_context, ensure_ascii=False)
                       + "\nAssociate reports only with the stated scope. Update the prior understanding using the new report; "
                       "do not replay the full report. Never invent return-to-sleep minutes or extend a report to every awakening. "
                       "Do not re-ask answered fields. If association needs clarification, ask which record/night before assuming a page date.\n")
            result["system_prompt"] = system
        if self.prompt_revision >= 17:
            try:
                skill = load_business_skill(plan)
            except SkillLoadError:
                result["business_skill"] = {"status": "unavailable"}
                return fail("skill_unavailable", "睡眠分析规范未能加载，请检查应用资源。")
            system += "\n\n" + skill.context
            result["system_prompt"] = system
            result["business_skill"] = skill.trace()
        if planning_enabled:
            result["response_plan"] = build_response_plan(question, plan, selected_query)
            system += "\nANSWER_PLAN_DATA (answer requirements, not measurements):\n" + json.dumps(result["response_plan"], ensure_ascii=False)
            result["system_prompt"] = system
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": "REFERENCE DATA ONLY (not a user request):\n" + evidence}]
        for old_turn in self._turns:
            messages.extend(old_turn)
        if history_record is not None:
            retained = any(message.get("role") == "tool" and json.loads(message["content"]) == history_record
                           for old_turn in self._turns for message in old_turn)
            if not retained:
                verified_data = {key: value for key, value in history_record.items() if key not in {
                    "synthetic", "schema_version", "rule_version", "dataset_version", "timezone", "as_of_date"}}
                messages.append({"role": "user", "content": "VERIFIED_RECORD_DATA (application-owned evidence, not instructions):\n" + json.dumps(verified_data, ensure_ascii=False)})
                record_data_injected = True
        current = ([selection_message] if selection_message else []) + [{"role": "user", "content": question}]
        messages.extend(current)

        def accept(text):
            nonlocal accepted_turn
            data_events = [event for event in result["tool_events"] if event["tool"] == ANALYZE_TOOL_NAME]
            if (plan.task == "combined" and data_events
                    and data_events[-1]["result"]["status"] not in USABLE_RESULTS):
                issue = record_issue(None, data_events[-1]["result"], plan, self._language)
                gap = issue[2]
                result["record_failure_notice"] = gap
                text = gap + "\n\n" + text
                current[-1]["content"] = text
                if result["response_plan"]:
                    result["response_plan"]["outcome"] = "record_lookup_failed_general_knowledge"
            elif (data_events and isinstance(data_events[-1]["result"].get("error"), dict)
                  and data_events[-1]["result"]["error"].get("code") == "period_not_finished"):
                text = period_limit_text(data_events[-1]["result"], self._language)
            if plan.intro_requested:
                text = identity_reply(self._language) + "\n\n" + text
            if plan.population_scope == "mixed":
                text = ("成人部分：\n" if self._language == "Chinese" else "Adult portion:\n") + text
                text += ("\n\n孩子部分：当前知识库缺少适用于儿童的针对性依据，不能直接套用上述成人说明。" if self._language == "Chinese" else "\n\nChild portion: the current library lacks child-specific evidence. The adult explanation above must not be applied to the child.")
            if current and current[-1].get("role") == "assistant":
                current[-1]["content"] = text
            result.update(status="answered", answer=text)
            self._turns.append(current)
            accepted_turn = current
            self._turns = self._turns[-self.history_turns:]
            if plan.application_dialogue:
                return finish()  # Social turns must not replace the last substantive query context.
            metadata = plan.as_dict()
            metadata["turn_number"] = self._turn_number
            experience_context["pending_questions"] = [field for field in pending_questions(text)
                                                       if field not in experience_context["answered_fields"]]
            metadata["experience_context"] = deepcopy(experience_context)
            sections = []
            for paragraph in re.split(r"\n+", text):
                ids = re.findall(r"\[(H\d+:[A-Za-z0-9_-]+)\]", paragraph)
                if ids:
                    topics = sorted({topic for ref in self.knowledge.references if ref["citation_id"] in ids
                                     for topic in ref.get("topics", [])})
                    sections.append({"citation_ids": list(dict.fromkeys(ids)), "topics": topics})
            metadata["answer_sections"] = sections
            if record_output:
                metadata["profile_id"] = record_output["profile_id"]
                metadata["resolved_period"] = [record_output["period"]["start_date"], record_output["period"]["end_date"]]
                metadata["compare_previous"] = bool(record_output.get("previous_period"))
            elif plan.task in {"records", "combined"} and plan.period:
                # Retain the confirmed request scope, without claiming any measurements.
                metadata["resolved_period"] = list(plan.period)
                metadata["profile_id"] = plan.profile_id or (selected_query or {}).get("profile_id")
            metadata["page_selection"] = dict(selected_query) if selected_query else None
            if (data_events and record_output and data_events[-1]["result"].get("status") in USABLE_RESULTS
                    and data_events[-1]["result"].get("profile_id") == record_output.get("profile_id")
                    and data_events[-1]["result"].get("period") == record_output.get("period")):
                self._record_history_blocked = False
            self._query_memory.append(metadata)
            self._query_memory = self._query_memory[-self.history_turns:]
            return finish()

        def accept_supported_part(candidate):
            health = {ref["citation_id"]: ref["text"] for ref in self.knowledge.references
                      if ref["citation_id"] in available_ids and ref["source_id"].startswith("H")}
            policy = {ref["citation_id"]: ref["text"] for ref in self.knowledge.references
                      if ref["source_id"].startswith("B")}
            part = supported_answer_blocks(candidate, knowledge=self.knowledge, available_ids=available_ids,
                                          health_references=health, policy_references=policy,
                                          record_output=record_output, plan=plan)
            if part is None:
                return None
            result["candidate_answer"] = candidate
            if record_output and plan.task in {"records", "combined"} and not part.has_record:
                result["record_part_missing"] = True
            result["citation_check"] = self.knowledge.check_citations(part.text, available_ids=available_ids)
            kept_warnings = (list(review_health_text(part.text, health, record_output=record_output,
                                                     policy_references=policy).warnings)
                             if re.search(r"\[H\d+:[A-Za-z0-9_-]+\]", part.text) else [])
            result["answer_validation"].update(status="partial", removed_blocks=part.removed_blocks,
                                               warnings=kept_warnings)
            result["answer_validation"]["warnings"].append({
                "code": "partial_answer", "message": "Unverified paragraphs were omitted; retained paragraphs were checked again."})
            if result["response_plan"]:
                result["response_plan"]["outcome"] = "supported_partial_answer"
            for sequence in (current, messages):
                if (sequence and sequence[-1].get("role") == "assistant"
                        and sequence[-1].get("content") in {candidate, part.text}):
                    sequence[-1]["content"] = part.text
                else:
                    sequence.append({"role": "assistant", "content": part.text})
            return accept(part.text)

        if plan.application_dialogue:
            result["answer_validation"]["status"] = "application_dialogue"
            reply = application_reply(plan.application_dialogue, self._language)
            current.append({"role": "assistant", "content": reply})
            return accept(reply)
        if plan.product_field:
            reply = product_field_reply(plan.product_field, self._language)
            result["answer_validation"]["status"] = "product_field_definition"
            result["citation_check"] = self.knowledge.check_citations(reply, available_ids=available_ids)
            current.append({"role": "assistant", "content": reply})
            return accept(reply)
        if plan.experience_reply and experience_context["association"] == "needs_clarification":
            reply = ("你说的是哪一天的睡眠，或刚才哪份记录？确认后，我可以把这个感受和记录一起看。" if self._language == "Chinese" else
                     "Which night's sleep or record do you mean? Once that is clear, I can relate your experience to it.")
            result["answer_validation"]["status"] = "experience_scope_clarification"
            current.append({"role": "assistant", "content": reply})
            return accept(reply)
        if plan.population_scope == "unclear" and plan.task in {"health", "combined"}:
            reply = ("你想了解的是你自己的睡眠，还是孩子或其他人的睡眠？这会影响现有资料是否适用。" if self._language == "Chinese" else "Whose sleep are you asking about: your own, the child's, or someone else's? This affects which evidence applies.")
            result["answer_validation"]["status"] = "subject_clarification"
            current.append({"role": "assistant", "content": reply})
            return accept(reply)
        if policy_enabled and plan.unavailable_measurement:
            text = explain_unavailable_measurement(plan.unavailable_measurement, self._language)
            result["answer_validation"]["status"] = "unavailable_measurement"
            result["citation_check"] = self.knowledge.check_citations(text, available_ids=available_ids)
            current.append({"role": "assistant", "content": text})
            return accept(text)
        if policy_enabled and plan.unsupported_window:
            text = ("目前支持已结束的单日或连续七天记录。请提供具体日期或七天的起止日期，也可以使用页面所选日期。" if self._language == "Chinese"
                    else "I can read a completed single date or seven-day window. Please specify a date or seven-day range, or use the selected dates.")
            result["answer_validation"]["status"] = "scope_clarification"
            current.append({"role": "assistant", "content": text})
            return accept(text)
        if policy_enabled and plan.special_population and plan.task in {"health", "combined"}:
            text = ("当前知识库主要是一般成年人的睡眠资料，缺少适用于你提到人群的针对性依据，不能直接套用成人建议。你可以向相应的专业人员咨询。" if self._language == "Chinese"
                    else "The current library mainly covers general adult sleep. It lacks population-specific evidence for this question, so I cannot directly apply adult guidance; seek appropriate professional advice.")
            result["answer_validation"]["status"] = "scope_clarification"
            current.append({"role": "assistant", "content": text})
            return accept(text)
        if self.prompt_revision >= 12 and plan.task == "definition":
            semantics = explain_blank_and_valid_zero(question, self._language) if self.prompt_revision >= 18 else None
            if semantics:
                result["answer_validation"]["status"] = "deterministic_record_semantics"
                result["citation_check"] = self.knowledge.check_citations(semantics, available_ids=available_ids)
                current.append({"role": "assistant", "content": semantics})
                return accept(semantics)
            explanation = explain_product_rules(question, self._language)
            if explanation:
                result["answer_validation"]["status"] = "deterministic_product_rule"
                result["rule_evaluation"] = {"provenance": "user_hypothetical_not_record_lookup",
                    "current_valid_nights": explanation.current_valid_nights,
                    "previous_valid_nights": explanation.previous_valid_nights,
                    "comparison_allowed": explanation.comparison_allowed}
                result["citation_check"] = self.knowledge.check_citations(explanation.text, available_ids=available_ids)
                current.append({"role": "assistant", "content": explanation.text})
                return accept(explanation.text)

        if policy_enabled and plan.date_source == "tonight_waking_date":
            reply = stage_assessment_reply(plan, self._language, today=berlin_today())
            if reply:
                result["answer_validation"].update(status="product_scope_answer", fallback="stage_assessment")
                result["reply_policy"] = policy_trace("data_missing", "date_unavailable")
                current.append({"role": "assistant", "content": reply})
                return accept(reply)

        try:
            for _ in range(3):
                remaining = 60 - (time.monotonic() - started)
                if remaining <= 0:
                    return fail("turn_timeout", "本轮达到60秒时限，未完成回答。")
                call_record = {"status": "started", "model": None, "prompt_tokens": None,
                               "completion_tokens": None, "total_tokens": None}
                result["model_calls"].append(call_record)
                try:
                    tools = [ANALYZE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA] if self.health_retrieval else [ANALYZE_TOOL_SCHEMA]
                    if planning_enabled:
                        tools = planned_tools(tools)
                    response = self.client.complete(messages, tools, timeout=remaining)
                except ModelError:
                    call_record["status"] = "error"
                    raise
                usage = response.usage
                call_record.update(status="completed", model=response.model,
                                   prompt_tokens=usage.prompt_tokens if usage else None,
                                   completion_tokens=usage.completion_tokens if usage else None,
                                   total_tokens=usage.total_tokens if usage else None)
                if time.monotonic() - started >= 60:
                    return fail("turn_timeout", "本轮已达到60秒时限，迟到结果不再用于回答。")
                if not response.choices:
                    return fail("empty_response", "模型没有返回可用结果。")
                choice = response.choices[0]
                if choice.finish_reason not in {"stop", "tool_calls"}:
                    return fail("incomplete_response", "模型响应未完整结束，本轮不计作成功。")
                message = choice.message
                # No reasoning_content or vendor internal reasoning is retained.
                assistant = message.model_dump(include={"role", "content", "tool_calls"}, exclude_none=True)
                current.append(assistant)
                messages.append(assistant)
                if message.tool_calls:
                    decoded = None
                    if planning_enabled:
                        try:
                            decoded = [unpack_arguments(call.function.arguments) for call in message.tool_calls]
                            proposals = [proposal for _, proposal in decoded if proposal is not None]
                            if proposals:
                                if any(proposal != proposals[0] for proposal in proposals):
                                    raise ValueError("The tool batch contains conflicting answer plans")
                                proposal = proposals[0]
                                if result["tool_events"] and proposal != accepted_proposal:
                                    raise ValueError("The answer plan cannot change after evidence execution")
                                refined = refine_query_plan(plan, proposal, question)
                                refined_skill = load_business_skill(refined)
                                plan = refined
                                accepted_proposal = proposal
                                result["query_plan"] = plan.as_dict()
                                result["response_plan"] = build_response_plan(question, plan, selected_query,
                                    source="model_tool_plan", intent=proposal["intent"], answer_format=proposal["answer_format"])
                                system = routing_system + "\nUSER_CONTEXT_DATA (validated task hints):\n" + json.dumps(plan.as_dict(), ensure_ascii=False)
                                if plan.experience_reply or experience_context["reports"]:
                                    system += "\nEXPERIENCE_CONTEXT_DATA (user reports, not measurements):\n" + json.dumps(experience_context, ensure_ascii=False)
                                system += "\n\n" + refined_skill.context
                                system += "\nANSWER_PLAN_DATA (validated answer requirements):\n" + json.dumps(result["response_plan"], ensure_ascii=False)
                                messages[0]["content"] = system
                                result["system_prompt"] = system
                                result["business_skill"] = refined_skill.trace()
                        except (ValueError, TypeError, SkillLoadError):
                            result["answer_validation"]["repairs"].append({"reason": "invalid_response_plan"})
                            current.pop()
                            messages.pop()
                            if len(result["model_calls"]) >= 3:
                                return fail("invalid_response_plan", "本轮问题理解未能通过校验，未执行这批查询。")
                            feedback = {"role": "user", "content": "APPLICATION VALIDATION: Invalid or conflicting response_plan/tool JSON. No calls in this batch were executed. Use the four-field response_plan schema, preserve requested facts and evidence, and do not revise the plan after evidence execution."}
                            current.append(feedback)
                            messages.append(feedback)
                            continue
                    if len(result["tool_events"]) + len(message.tool_calls) > 2:
                        if self.prompt_revision >= 10 and len(result["model_calls"]) < 3 and len(result["tool_events"]) < 2:
                            current.pop()
                            messages.pop()
                            feedback = {"role": "user", "content": (
                                "APPLICATION VALIDATION: Too many tool calls in that batch; none were executed. "
                                f"Only {2 - len(result['tool_events'])} tool calls remain. "
                                "Use one analyze_sleep call if needed and combine health topics into one search_sleep_knowledge query.")}
                            result["answer_validation"]["repairs"].append({"reason": "tool_batch_limit"})
                            current.append(feedback)
                            messages.append(feedback)
                            continue
                        return fail("tool_limit", "模型超过本轮最多2次工具调用的限制。")
                    for call_index, call in enumerate(message.tool_calls):
                        arguments = decoded[call_index][0] if decoded is not None else call.function.arguments
                        if (call.function.name == ANALYZE_TOOL_NAME and isinstance(arguments, dict)
                                and (plan.compare_previous is False or (plan.period and plan.period[0] == plan.period[1]))
                                and type(arguments.get("compare_previous")) is bool):
                            arguments = {**arguments, "compare_previous": False}
                        elif (call.function.name == ANALYZE_TOOL_NAME and isinstance(arguments, dict)
                                and "comparison" in plan.metrics
                                and not set(plan.metrics) & {"awakenings", "awake", "deep", "light", "rem", "stages", "sleep_onset", "wake_time"}
                                and type(arguments.get("compare_previous")) is bool):
                            arguments = {**arguments, "compare_previous": True}
                        event = {"tool": call.function.name, "tool_call_id": call.id,
                                 "executed": False, "validated_arguments": None, "result": None}
                        result["tool_events"].append(event)
                        allowed = {ANALYZE_TOOL_NAME, SEARCH_TOOL_NAME} if self.health_retrieval else {ANALYZE_TOOL_NAME}
                        if self.prompt_revision >= 13:
                            allowed = {schema["function"]["name"] for schema in tools}
                        if call.function.name not in allowed:
                            return fail("unknown_tool", "模型请求了未开放的工具，已拒绝执行。")
                        options = {}
                        if policy_enabled and call.function.name == SEARCH_TOOL_NAME:
                            options = {"excluded_topics": ("caffeine",) if plan.no_caffeine and not plan.caffeine_question else ()}
                        conflict = (planning_enabled and call.function.name == ANALYZE_TOOL_NAME and isinstance(arguments, dict) and
                                    ((plan.profile_id and arguments.get("profile_id") != plan.profile_id) or
                                     (plan.period and (arguments.get("start_date"), arguments.get("end_date")) != plan.period)))
                        try:
                            output = ({"status": "invalid_input", "error": "Requested profile/date conflicts with the validated question plan; no lookup was executed."}
                                      if conflict else dispatch_tool(call.function.name, arguments, **options))
                        except Exception as exc:
                            output = {"status": "tool_error", "error": {"code": "execution_failed", "exception_type": type(exc).__name__}}
                        if call.function.name == ANALYZE_TOOL_NAME:
                            self._record_history_blocked = True
                        if policy_enabled and call.function.name == ANALYZE_TOOL_NAME and output.get("current"):
                            if ((plan.profile_id and output["profile_id"] != plan.profile_id) or
                                    (plan.period and (output["period"]["start_date"], output["period"]["end_date"]) != plan.period)):
                                output = {"status": "invalid_input", "error": "Requested profile/date conflicts with the user's explicit query; retry with the requested parameters."}
                        event["result"] = output
                        if call.function.name == SEARCH_TOOL_NAME:
                            result["retrieved_evidence"].extend(output.get("passages", []))
                            available_ids.update(ref["citation_id"] for ref in output.get("passages", []))
                        if call.function.name == ANALYZE_TOOL_NAME and output.get("current") and output["status"] in USABLE_RESULTS:
                            record_output = output
                        elif call.function.name == ANALYZE_TOOL_NAME:
                            record_output = None
                        if call.function.name == ANALYZE_TOOL_NAME:
                            self._remember_record_result(output, plan, selected_query or {})
                        event["executed"] = output["status"] != "invalid_input"
                        if event["executed"]:
                            event["validated_arguments"] = (json.loads(arguments)
                                                            if isinstance(arguments, str)
                                                            else arguments)
                            if policy_enabled and call.function.name == SEARCH_TOOL_NAME and output.get("query"):
                                event["requested_arguments"] = event["validated_arguments"]
                                event["validated_arguments"] = {"query": output["query"]}
                        model_output = output
                        if self.prompt_revision >= 8 and call.function.name == ANALYZE_TOOL_NAME:
                            model_output = {key: value for key, value in output.items() if key not in {
                                "synthetic", "schema_version", "rule_version", "dataset_version", "timezone", "as_of_date"
                            }}
                            model_output["warnings"] = [warning for warning in output.get("warnings", [])
                                                        if warning["code"] != "descriptive_comparison_only"]
                            # Let the model select observations from the full scoped result.
                            event["model_result"] = model_output
                        if (call.function.name == ANALYZE_TOOL_NAME and output["status"] not in USABLE_RESULTS
                                and plan.task == "combined"):
                            model_output["answer_requirements"] = "Record lookup failed. Do not report personal values or use {{sleep_summary}}. Explain only general principles supported by actual health passages; the application will prepend the record failure explanation."
                        tool_message = {"role": "tool", "tool_call_id": call.id,
                                        "content": json.dumps(model_output, ensure_ascii=False, allow_nan=False)}
                        current.append(tool_message)
                        messages.append(tool_message)
                    scope = stage_response_scope(question, plan)
                    if (scope and not scope.independent_question
                            and scoped_record(record_output, plan, selected_query or {}) is not None):
                        # Known calculations and the current judgment limit do
                        # not need another interpretation generation.
                        result["answer_validation"]["status"] = "application_record_composition"
                        current.append({"role": "assistant", "content": ""})
                        return accept("")
                    continue
                if not message.content:
                    return fail("empty_answer", "模型没有返回文字回答。")
                # Completeness notes describe this candidate, not an earlier
                # rejected draft that may have been repaired successfully.
                result["answer_validation"].pop("warnings", None)
                if self.prompt_revision >= 17:
                    normalized = normalize_record_format(normalize_citation_format(message.content))
                    if normalized != message.content:
                        result["answer_validation"].setdefault("normalizations", []).append(
                            {"kind": "citation_and_record_format", "original": message.content})
                        message.content = normalized
                        current[-1]["content"] = normalized
                data_events = [event for event in result["tool_events"] if event["tool"] == ANALYZE_TOOL_NAME]
                failed_record_lookup = bool(data_events and data_events[-1]["result"]["status"] not in USABLE_RESULTS)
                if failed_record_lookup and plan.task != "combined" and not is_evidence_gap_answer(message.content):
                    result["candidate_answer"] = message.content
                    return fail("no_usable_tool_result", "本轮工具未提供可用统计，无法报告睡眠数值；请核对角色、日期或数据状态。")
                if result["tool_events"] and all(event["result"]["status"] not in USABLE_RESULTS | {"no_results"}
                                                  for event in result["tool_events"]) and not is_evidence_gap_answer(message.content):
                    return fail("knowledge_unavailable", "暂时没能读取相关资料，请稍后再试。")
                check = self.knowledge.check_citations(message.content, available_ids=available_ids)
                result["citation_check"] = check
                if check["status"] == "invalid":
                    if self.prompt_revision >= 12:
                        result["answer_validation"]["repairs"].append({"reason": "invalid_or_unavailable_citation", "candidate": message.content})
                        if len(result["model_calls"]) < 3:
                            current.pop()
                            messages.pop()
                            feedback = {"role": "user", "content": (
                                "APPLICATION VALIDATION: The citation IDs " + json.dumps(check["invalid"] + check["unavailable"]) +
                                " are invalid or have not been supplied. Correct the answer using actually supporting available evidence; "
                                "do not simply replace a tag on an unsupported claim. Available IDs: " + json.dumps(sorted(available_ids)))}
                            current.append(feedback)
                            messages.append(feedback)
                            continue
                        partial = accept_supported_part(message.content)
                        if partial is not None:
                            return partial
                        result["answer_validation"]["status"] = "blocked"
                    result.update(status="needs_review", answer="回答的资料引用未能核实，请重新提问。",
                                  candidate_answer=message.content)
                    return finish()
                final_answer = message.content
                if self.prompt_revision >= 10:
                    health_refs = {ref["citation_id"]: ref["text"] for ref in self.knowledge.references
                                   if ref["citation_id"] in available_ids and ref["source_id"].startswith("H")}
                    has_health_citation = any(ref["source_id"].startswith("H") for ref in check["references"])
                    needs_health = needs_health_evidence(question, message.content) or has_health_citation
                    if policy_enabled:
                        needs_health = (has_health_citation or plan.task in {"health", "combined"} or
                                        (needs_health_evidence("", message.content) if plan.task in {"records", "definition"} else needs_health))
                    if self.prompt_revision >= 16:
                        needs_health = needs_health_for_task(question, message.content, plan, has_health_citation)
                    if not has_health_citation and is_evidence_gap_answer(message.content):
                        needs_health = False
                    # Require health evidence for health claims actually made.
                    # A preliminary request for interpretation does not turn
                    # an otherwise grounded record-only answer into bad data.
                    no_requested_records = bool(record_output and (
                        not record_output["current"]["valid_nights"] or
                        (set(plan.metrics) & {"sleep_onset", "wake_time", "awakenings", "awake", "deep", "light", "rem", "stages"}
                         and not record_output["current"].get("detail_nights", 0))))
                    facts_only = not re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", message.content.replace(SUMMARY_TOKEN, "")).strip(" \t\n。.!，,")
                    if planning_enabled and no_requested_records and facts_only and not has_health_citation:
                        needs_health = False
                        result["response_plan"]["outcome"] = "requested_records_unavailable"
                    problem = None
                    if needs_health and not has_health_citation:
                        problem = "Sleep guidance needs supporting health passages and their exact citations."
                    elif needs_health:
                        health_review = review_health_text(message.content, health_refs, record_output=record_output,
                            policy_references={ref["citation_id"]: ref["text"] for ref in self.knowledge.references if ref["source_id"].startswith("B")})
                        problem = health_review.blocking_problem
                        if health_review.warnings:
                            result["answer_validation"].setdefault("warnings", []).extend(health_review.warnings)
                    if policy_enabled and contradicts_coffee_context(message.content, plan):
                        problem = "The user does not drink coffee. Do not recommend changing coffee use; other caffeine sources remain relevant when explicitly asked."
                    if policy_enabled and plan.focus_citations and has_health_citation:
                        cited = {ref["citation_id"] for ref in check["references"] if ref["source_id"].startswith("H")}
                        if not cited.issubset(set(plan.focus_citations)):
                            result["answer_validation"].setdefault("warnings", []).append({
                                "code": "followup_scope", "message": "The answer includes additional available sources beyond the focused point."})
                    clarifying = (bool(re.fullmatch(r"[^。！.!\n]{1,120}[？?]", message.content.strip())) or
                                  (bool(re.match(r"(?:请(?:选择|提供|确认|告诉)|please (?:select|provide|confirm))", message.content.strip(), re.I))
                                   and not re.search(r"平均|均值|\baverage\b|\bmean\b", message.content, re.I)))
                    if (policy_enabled and plan.task in {"records", "combined"} and record_output is None
                            and not failed_record_lookup
                            and (selected_query or (plan.profile_id and plan.period) or QUANTITY.search(message.content)
                                 or SUMMARY_TOKEN in message.content)
                            and not clarifying):
                        problem = "Obtain the requested record result with analyze_sleep before giving record facts; never reuse a different profile or period."
                    if (policy_enabled and set(plan.metrics).intersection({"extrema", "daily"}) and record_output
                            and not (record_output.get("daily_records") or {}).get("current")):
                        problem = "Load nightly records with analyze_sleep before answering nightly extrema; retained summary statistics do not contain daily rows."
                    numeric_problem = validate_record_text(message.content, record_output,
                        require_summary=False, health_references=health_refs,
                        policy_references={ref["citation_id"]: ref["text"] for ref in self.knowledge.references
                                           if ref["source_id"].startswith("B")})
                    problem = numeric_problem or problem
                    if not problem and (plan.sleep_overview or (result["response_plan"] or {}).get("needs_interpretation")) and record_output and not no_requested_records:
                        interpretation_problem = validate_interpretation(message.content, record_output, assessment=plan.personal_assessment)
                        if interpretation_problem:
                            result["answer_validation"].setdefault("warnings", []).append({
                                "code": "interpretation_incomplete", "source": "heuristic",
                                "visibility": "diagnostic", "message": interpretation_problem})
                    if problem:
                        result["answer_validation"]["repairs"].append({"reason": problem, "candidate": message.content})
                        # Discard rejected prose from successful conversation history.
                        current.pop()
                        messages.pop()
                        if needs_health and not has_health_citation and len(result["tool_events"]) < 2:
                            query = search_query(question, plan) if policy_enabled else (question + " " + message.content)[:500]
                            call_id = "guard-search-" + uuid4().hex
                            search_call = {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
                                "function": {"name": SEARCH_TOOL_NAME, "arguments": json.dumps({"query": query}, ensure_ascii=False)}}]}
                            output = dispatch_tool(SEARCH_TOOL_NAME, {"query": query},
                                                   excluded_topics=("caffeine",) if policy_enabled and plan.exclude_caffeine else ())
                            result["tool_events"].append({"tool": SEARCH_TOOL_NAME, "tool_call_id": call_id,
                                "initiated_by": "answer_guard", "executed": output["status"] != "invalid_input",
                                "validated_arguments": {"query": query}, "result": output})
                            result["retrieved_evidence"].extend(output.get("passages", []))
                            available_ids.update(ref["citation_id"] for ref in output.get("passages", []))
                            tool_message = {"role": "tool", "tool_call_id": call_id,
                                            "content": json.dumps(output, ensure_ascii=False)}
                            current.extend([search_call, tool_message])
                            messages.extend([search_call, tool_message])
                            health_refs.update({ref["citation_id"]: ref["text"] for ref in output.get("passages", [])})
                        # A successful lookup can still be answered from its
                        # records after removing an incidental health claim.
                        # Empty supplemental search is not a reason to discard
                        # that remaining repair slot. All output gates run again.
                        record_lookup_repair = (plan.task in {"records", "combined"} and record_output
                                                and not no_requested_records)
                        missing_health = needs_health and not has_health_citation and not health_refs
                        if (len(result["model_calls"]) >= 3 or
                                (missing_health and (not record_lookup_repair or numeric_problem is None))):
                            partial = accept_supported_part(message.content)
                            if partial is not None:
                                return partial
                            result["answer_validation"]["status"] = "blocked"
                            result.update(status="needs_review", candidate_answer=message.content,
                                answer=("本轮回答仍有未通过核对的内容，暂不展示分析结论。可以查看本轮工具记录与依据。" if self._language == "Chinese"
                                        else "This answer still contains unsupported claims, so I cannot present its conclusions. The retrieved records and evidence remain available."))
                            return finish()
                        feedback = {"role": "user", "content": "APPLICATION VALIDATION: " + problem +
                                    " Rewrite the specific unsupported claim using the actual records and sources. You may write verified values naturally; {{sleep_summary}} is optional. Preserve useful analysis and answer the user directly."}
                        if missing_health and record_lookup_repair:
                            feedback["content"] += (
                                " No supporting health passages were obtained. This is a record lookup: "
                                "answer the requested verified record facts and remove unrequested health "
                                "interpretation rather than withholding the records. Do not invent citations "
                                "or request further tools beyond the remaining budget.")
                        current.append(feedback)
                        messages.append(feedback)
                        continue
                    result["answer_validation"]["status"] = "passed"
                    if SUMMARY_TOKEN in final_answer:
                        facts = render_facts(record_output, plan, self._language) if policy_enabled else record_summary(record_output, self._language)
                        if re.match(r"\s*[。.!]", final_answer.split(SUMMARY_TOKEN, 1)[1]):
                            facts = facts.rstrip("。.")
                        final_answer = final_answer.replace(SUMMARY_TOKEN, facts)
                        # Future turns see precisely the answer displayed to the user.
                        current[-1]["content"] = final_answer
                if check["status"] == "not_provided":
                    result["validation_warnings"].append("No section citations; acceptable for clarification, otherwise review the evidence.")
                # Commit a whole successful turn, never dangling tool messages.
                return accept(final_answer)
            return fail("model_limit", "达到本轮最多3次模型请求的限制，未获得最终回答。")
        except ModelError as exc:
            return fail("model_error", str(exc))
        except (ValueError, TypeError, AttributeError, KeyError, OSError):
            return fail("invalid_response", "模型或工具响应格式异常，未生成可靠回答。")
