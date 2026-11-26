"""Offline application replays with authored candidates, not model quality scores."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from streamlit.testing.v1 import AppTest

from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.answer_validation import validate_health_text, validate_record_text
from sleeplens.config import Settings
from sleeplens.experience_context import feedback_fields
from sleeplens.knowledge import load_knowledge
from sleeplens.query_policy import plan_query, search_query


DAY = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-19", compare_previous=False)
QUESTION = "你好，帮我分析一下2026年10月19日的睡眠记录。"
FEEDBACK = "我醒来后很容易就入睡了。"
FIRST = ("这晚记录到睡眠7小时45分钟，夜间醒来2次，中途清醒合计8分钟。"
         "记录中的清醒时间较短；结合醒后能否再睡着，可以进一步理解这些夜醒对你的影响。[H8:NightWaking] "
         "你醒来后容易再次入睡吗？")
SECOND = ("你补充说醒后容易再睡着，结合记录中清醒合计8分钟，目前的信息没有提示夜醒让你长时间难以继续睡。"
          "[H8:NightWaking] 第二天醒来后，你觉得精神恢复得怎么样？")
GOOD = "那你的恢复感也不错。你没有报告长时间难以继续睡，第二天也觉得精神不错。"
TIRED = ("那疲惫就是还需要关注的部分。容易再睡着补充了夜醒后的体验，但不能替代第二天的恢复感。"
         "[H1:Quality] 这次疲惫只出现在第二天，还是最近也常有？")


class Client:
    def __init__(self, *items):
        self.items = list(items)
        self.requests = []

    def complete(self, messages, tools, timeout):
        self.requests.append(deepcopy(messages))
        assert self.items, messages[-1]
        item = self.items.pop(0)
        message = ChatCompletionMessage(role="assistant", content=item) if isinstance(item, str) else item
        return SimpleNamespace(model="offline-authored-experience", usage=None,
                               choices=[SimpleNamespace(message=message, finish_reason="stop")])

    def close(self):
        pass


def evidence(args=DAY, *, search=True, proposal=None):
    record_args = dict(args)
    if proposal:
        record_args["response_plan"] = proposal
    calls = [{"id": "records", "type": "function", "function": {
        "name": "analyze_sleep", "arguments": json.dumps(record_args)}}]
    if search:
        calls.append({"id": "knowledge", "type": "function", "function": {
            "name": "search_sleep_knowledge", "arguments": json.dumps({"query": "night waking sleep quality"})}})
    return ChatCompletionMessage(role="assistant", tool_calls=calls)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 24))


def seed(*tail):
    client = Client(evidence(), FIRST, *tail)
    session = ChatSession(client)
    first = session.ask(QUESTION, selected_query=DAY)
    assert first["status"] == "answered", first
    return session, client, first


@pytest.mark.parametrize("feedback,answer", [
    ("第二天精神挺好的，不用再问了。", GOOD),
    ("第二天还是很疲惫。", TIRED),
])
def test_three_turn_updates_keep_date_reports_and_answered_topics(feedback, answer):
    session, client, first = seed(SECOND, answer)
    second = session.ask(FEEDBACK, selected_query=DAY)
    third = session.ask(feedback, selected_query=DAY)
    assert first["answer"] == FIRST and "失眠" not in first["answer"]
    assert first["record_availability"] == {"state": "available", "message": None}
    assert second["status"] == third["status"] == "answered"
    assert second["answer"] == SECOND and third["answer"] == answer
    assert not second["tool_events"] and not third["tool_events"]
    assert not second["answer_validation"]["repairs"] and not third["answer_validation"]["repairs"]
    assert second["response_plan"]["intent"] == third["response_plan"]["intent"] == "followup"
    assert second["query_plan"]["metrics"] == ("awake",)
    for turn in (second, third):
        assert turn["record_context"]["source"] == "history"
        assert turn["record_context"]["scope_matches"]
        assert turn["response_plan"]["period"] == ["2026-10-19", "2026-10-19"]
        assert "EXPERIENCE_CONTEXT_DATA" in turn["system_prompt"]
        assert "followup" in turn["business_skill"]["sections"]
    reports = third["experience_context"]["reports"]
    assert reports["return_to_sleep"] == {"text": FEEDBACK, "turn": 2, "source": "user_report"}
    assert reports["daytime"]["text"] == feedback
    assert set(third["experience_context"]["answered_fields"]) == {"return_to_sleep", "daytime"}
    assert not third["experience_context"]["pending_questions"]
    assert first["experience_context"]["pending_questions"] == ["return_to_sleep"]
    assert second["experience_context"]["pending_questions"] == ["daytime"]
    # The source remains available even when a simple acknowledgment cites none.
    assert "H8:NightWaking" in third["available_health_ids"]
    assert len(client.requests) == 4


def test_elliptical_answer_requires_one_pending_question():
    assert feedback_fields("很容易。", ["return_to_sleep"]) == ("return_to_sleep",)
    assert not feedback_fields("还好。", ["return_to_sleep", "daytime"])
    assert not feedback_fields("解释醒来后再次入睡的机制")
    session, _, _ = seed(SECOND)
    result = session.ask("很容易。", selected_query=DAY)
    assert result["query_plan"]["experience_reply"]
    assert result["experience_context"]["reports"]["return_to_sleep"]["text"] == "很容易。"


def test_model_plan_refinement_keeps_raw_subjective_context():
    proposal = {"intent": "followup", "metrics": ["awake"],
                "evidence": ["records", "knowledge"], "answer_format": "short"}
    call = ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "followup-search", "type": "function", "function": {
            "name": "search_sleep_knowledge", "arguments": json.dumps({
                "query": "night waking", "response_plan": proposal})}}])
    session, client, _ = seed(call, SECOND)
    result = session.ask(FEEDBACK, selected_query=DAY)
    assert result["status"] == "answered"
    assert result["response_plan"]["source"] == "model_tool_plan"
    assert "EXPERIENCE_CONTEXT_DATA" in client.requests[-1][0]["content"]
    assert FEEDBACK in client.requests[-1][0]["content"]


def test_english_feedback_is_scoped_without_full_metric_inheritance():
    previous = {"task": "combined", "profile_id": "P01", "resolved_period": ["2026-10-19"] * 2,
                "metrics": ["mean", "deep", "light", "rem", "awakenings"],
                "experience_context": {"pending_questions": ["return_to_sleep"]}}
    plan = plan_query("I fell back asleep easily.", previous=previous, selected_query=DAY)
    assert plan.followup and plan.experience_reply
    assert plan.period == ("2026-10-19", "2026-10-19")
    assert plan.metrics == ("awake",)
    assert "insomnia" not in plan.topics


@pytest.mark.parametrize("next_question", ["深睡是多少分钟？", "为什么白天还是困？"])
def test_feedback_and_new_question_preserve_both_parts(next_question):
    previous = {"task": "combined", "profile_id": "P01", "resolved_period": ["2026-10-19"] * 2,
                "metrics": ["mean", "deep", "light", "rem", "awakenings"]}
    plan = plan_query(FEEDBACK + next_question, previous=previous, selected_query=DAY)
    assert plan.experience_reply and plan.followup
    assert "return_to_sleep" in plan.experience_fields
    assert plan.period == ("2026-10-19", "2026-10-19")
    if "深睡" in next_question:
        assert "deep" in plan.metrics
    else:
        assert plan.metrics == ("awake",)


def test_unbound_subjective_reply_does_not_assume_page_date():
    client = Client()
    result = ChatSession(client).ask(FEEDBACK, selected_query=DAY)
    assert result["answer_validation"]["status"] == "experience_scope_clarification"
    assert "哪一天" in result["answer"] and result["answer"].count("？") == 1
    assert not result["tool_events"] and not client.requests
    assert result["experience_context"]["association"] == "needs_clarification"


@pytest.mark.parametrize("change", [
    {"profile_id": "P03"}, {"start_date": "2026-10-20", "end_date": "2026-10-20"},
])
def test_changed_page_scope_does_not_attach_old_experience(change):
    session, client, _ = seed(SECOND, "你指的是哪次醒来后的感受？")
    session.ask(FEEDBACK, selected_query=DAY)
    result = session.ask("很容易。", selected_query={**DAY, **change})
    assert result["experience_context"]["reports"] == {}
    assert result["record_context"]["source"] == "none"
    assert not result["query_plan"]["experience_reply"]
    # A page change removes pending context rather than treating this as an
    # answer about the new record. Script just acknowledges ambiguous feedback.


def test_explicit_new_night_clears_reports_and_queries_new_record():
    other = {**DAY, "start_date": "2026-10-20", "end_date": "2026-10-20"}
    row = analyze_sleep(**other)["daily_records"]["current"][0]
    session, _, _ = seed(SECOND, evidence(other, search=False), f"这晚记录睡眠{row['sleep_min']}分钟，值得结合自己的感受看。")
    session.ask(FEEDBACK, selected_query=DAY)
    result = session.ask("再分析一下2026年10月20日的睡眠记录。", selected_query=DAY)
    assert result["status"] == "answered"
    assert result["tool_events"][0]["validated_arguments"] == other
    assert not result["experience_context"]["reports"]
    session.reset()
    assert not session._query_memory and session._verified_record is None


def test_night_waking_search_does_not_inject_insomnia_but_risk_stays_routed():
    plan = plan_query(QUESTION, selected_query=DAY)
    assert "insomnia" not in search_query(QUESTION, plan)
    risk = plan_query("我长期失眠，还有呼吸暂停，应该怎么办？")
    assert {"persistent_insomnia", "breathing"}.issubset(set(risk.topics))
    assert "insomnia" in search_query("", risk)


@pytest.mark.parametrize("fault,answer,state", [
    ("missing", "这天没有可用睡眠记录，无法解读这天的数据。", "no_records"),
    ("tool_error", "这次没能读取记录，无法确认这天的睡眠情况。", "lookup_failed"),
    ("data_quality_error", "这次记录未通过完整性校验，无法确认睡眠情况。", "lookup_failed"),
    ("details", "这晚记录到睡眠465分钟，可以先结合第二天的精神感受理解。", "missing_details"),
])
def test_actual_record_gaps_are_preserved(monkeypatch, fault, answer, state):
    if fault == "missing":
        from sleeplens.data import load_dataset
        dataset = load_dataset()
        dataset = replace(dataset, records=tuple(r for r in dataset.records
                          if not (r.profile_id == "P01" and r.record_date == date(2026, 10, 19))))
        monkeypatch.setattr("sleeplens.analysis.load_dataset", lambda: dataset)
    elif fault == "details":
        from sleeplens.data import DETAIL_FIELDS, load_dataset
        dataset = load_dataset()
        dataset = replace(dataset, records=tuple(replace(r, **dict.fromkeys(DETAIL_FIELDS))
                          if r.profile_id == "P01" and r.record_date == date(2026, 10, 19) else r
                          for r in dataset.records))
        monkeypatch.setattr("sleeplens.analysis.load_dataset", lambda: dataset)
    else:
        from sleeplens.data import DataQualityError
        def failed_read():
            if fault == "tool_error":
                raise OSError("Internal path must not be shown")
            raise DataQualityError("stage_sum_mismatch", "Internal path must not be shown")
        monkeypatch.setattr("sleeplens.analysis.load_dataset", failed_read)
    result = ChatSession(Client(evidence(search=False), answer)).ask(QUESTION, selected_query=DAY)
    assert result["record_availability"]["state"] == state
    assert result["record_context"]["scope_matches"] == (fault in {"missing", "details"})
    assert "Internal path" not in result["answer"]
    if fault == "details":
        assert "缺少入睡" in result["record_availability"]["message"]
    elif fault == "missing":
        assert "没有可用" in result["record_availability"]["message"]
    else:
        assert "失败" in result["answer"] or "无效" in result["answer"]
        assert result["reply_policy"]["category"] in {"data_missing", "tool_failure"}


def test_numeric_units_medical_and_invented_latency_guards_remain():
    output = analyze_sleep(**DAY)
    health = {ref["citation_id"]: ref["text"] for ref in load_knowledge().references if ref["source_id"].startswith("H")}
    for bad in ["这晚睡了999分钟。", "中途清醒8小时。", "你每次夜醒都在4分钟内重新入睡。",
                "你每次夜醒后8分钟内就重新入睡了。"]:
        assert validate_record_text(bad, output, require_summary=False, health_references=health)
    for bad in ["你已经患有失眠。", "建议服用10毫克安眠药。", "你的深睡67分钟已经达标。[H6:Pattern]"]:
        assert validate_health_text(bad, health, record_output=output)


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("language", ["Chinese", "English"])
def test_actual_ui_uses_conversation_language_and_only_real_gap_notices(monkeypatch, tmp_path, missing, language):
    monkeypatch.chdir(tmp_path)
    if missing:
        args = {**DAY, "start_date": "2026-09-19", "end_date": "2026-09-19"}
        question = "帮我分析2026年9月19日的睡眠记录。"
        answer = "所请求日期没有可用记录，无法解读这天的数据。"
    else:
        args, question = DAY, QUESTION
        # Deliberately value-only candidate: the heuristic remains observable
        # in diagnostics without being presented as a failed whole task.
        answer = "这晚记录睡眠7小时45分钟。"
    if language == "English":
        question = f"Please analyze the sleep record for {args['start_date']}."
        answer = ("There are no usable records for this date, so I cannot interpret it." if missing else
                  "This night recorded 7 hours 45 minutes of sleep.")
    client = Client(evidence(args, search=False), answer)
    monkeypatch.setattr("sleeplens.dashboard.create_model", lambda: (client, Settings(api_key="offline")))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    app.chat_input[0].set_value(question).run()
    assert not app.exception
    turn = app.session_state["dashboard"].turns[-1]
    assert turn["status"] == "answered" and turn["answer_language"] == language
    captions = "\n".join(item.value for item in app.caption)
    assert "record interpretation is incomplete" not in captions
    assert "Available information is shown below" not in captions
    if missing:
        shown = "\n".join(item.value for item in app.markdown)
        assert ("没有可用的睡眠记录" if language == "Chinese" else "No usable sleep records are available") in shown
        assert turn["reply_policy"]["category"] == "data_missing"
    else:
        assert turn["answer_validation"]["warnings"][0]["source"] == "heuristic"
        assert not turn["record_availability"]["message"]
