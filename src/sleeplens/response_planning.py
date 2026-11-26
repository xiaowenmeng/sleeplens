"""Observable answer requirements; never hidden reasoning or tool authority.

An application plan exists before the first request. The model can refine it
inside its first evidence-tool call without an extra model round trip.
"""
import copy
import json
import re
from datetime import date
from dataclasses import replace

from sleeplens.query_policy import requested_detail_metrics
from sleeplens.reply_policy import stage_response_scope


METRICS = ("mean", "coverage", "comparison", "extrema", "shortest", "longest", "daily",
           "sleep_onset", "wake_time", "awakenings", "awake", "deep", "light", "rem", "stages")
INTENTS = ("lookup", "nightly", "comparison", "interpretation", "explanation", "advice", "followup", "clarification")
FORMATS = ("short", "table", "summary_with_nights", "comparison", "explanation", "advice")
PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "metrics": {"type": "array", "items": {"type": "string", "enum": list(METRICS)}, "maxItems": len(METRICS)},
        "evidence": {"type": "array", "items": {"type": "string", "enum": ["records", "knowledge"]}, "maxItems": 2},
        "answer_format": {"type": "string", "enum": list(FORMATS)},
    }, "required": ["intent", "metrics", "evidence", "answer_format"],
}


def build_response_plan(question, plan, selection=None, *, source="application", intent=None, answer_format=None):
    selection = selection or {}
    records = plan.task in {"records", "combined"}
    knowledge = plan.task in {"health", "combined", "sources"}
    stage_scope = stage_response_scope(question, plan)
    closed_stage = bool(stage_scope and not stage_scope.independent_question)
    if closed_stage:
        knowledge = False
        intent = "lookup" if stage_scope.intent == "lookup" else "explanation"
    metrics = list(dict.fromkeys(plan.metrics))
    if intent is None:
        if plan.application_dialogue:
            intent = "explanation"
        elif plan.experience_reply:
            intent = "followup" if plan.period else "clarification"
        elif plan.task == "combined" and not plan.wants_improvement:
            intent = "interpretation"
        elif plan.wants_improvement and knowledge:
            intent = "advice"
        elif "daily" in metrics:
            intent = "nightly"
        elif "comparison" in metrics:
            intent = "comparison"
        elif plan.task in {"health", "definition", "sources", "capability"}:
            intent = "explanation"
        elif plan.followup:
            intent = "followup"
        else:
            intent = "lookup"
    if answer_format is None:
        answer_format = ("short" if plan.application_dialogue else
                         "summary_with_nights" if intent == "interpretation" and "daily" in metrics else
                         "table" if "daily" in metrics else
                         "comparison" if intent == "comparison" else
                         "advice" if intent == "advice" else
                         "explanation" if intent in {"interpretation", "explanation", "clarification"} else "short")
    if records and "daily" in metrics and answer_format not in {"table", "summary_with_nights"}:
        answer_format = "summary_with_nights" if intent == "interpretation" else "table"
    period = plan.period or ((selection["start_date"], selection["end_date"]) if records and selection else None)
    single_day = bool(period and period[0] == period[1])
    two_weeks = bool(period and (date.fromisoformat(period[1]) - date.fromisoformat(period[0])).days == 13)
    if single_day:
        answer_format = ("advice" if intent == "advice" else
                         "explanation" if intent == "interpretation" or plan.wants_analysis else "short")
    profile = plan.profile_id or (selection.get("profile_id") if records else None)
    missing = []
    if records:
        if not profile:
            missing.append("profile_id")
        if not period:
            missing.append("period")
    time_scope = ("single_day" if single_day else
                  "last_14_days" if re.search(r"(?:最近|过去|近)(?:两|二|2)(?:个)?(?:周|星期)|(?:最近|过去|近)(?:十四|14)天|(?:last|past) (?:two weeks|2 weeks|fortnight|fourteen days|14 days)", question, re.I) else
                  "last_7_days" if re.search(r"(?:最近|过去|近)[一1]周|(?:最近|过去)[七7]天|last (?:seven|7) days|past (?:week|seven days|7 days)", question, re.I) else
                  "last_calendar_week" if plan.period and re.search(r"上周|上一周|last week", question, re.I) else
                  "explicit_dates" if plan.period and len(re.findall(r"\d{4}-\d{2}-\d{2}", question)) == 2 else
                  "confirmed_history" if plan.period else "selected_week" if period else "unspecified")
    result = {
        "version": "response-plan-v1", "source": source, "intent": intent,
        "task": plan.task, "metrics": metrics,
        "profile_id": profile, "period": list(period) if period else None,
        "period_source": "question_or_confirmed_history" if plan.period else "page_selection" if period else "unspecified",
        "time_scope": time_scope,
        "evidence": (["records"] if records else []) + (["knowledge"] if knowledge else []),
        "granularity": "day" if single_day else "two_weeks" if two_weeks else "week" if period else None,
        "answer_format": answer_format, "include_nightly": records and (single_day or "daily" in metrics),
        "needs_interpretation": not closed_stage and (intent == "interpretation" or (records and plan.wants_analysis)), "missing": missing,
        "requirements": (["requested_facts", "actual_dates"] if records else []) +
                        (["coverage"] if records and "coverage" in metrics else []) +
                        (["nightly_records"] if records and "daily" in metrics else []) +
                        (["grounded_interpretation"] if intent == "interpretation" or (records and plan.wants_analysis) else []) +
                        (["product_rule_explanation"] if plan.include_rule_explanation else []) +
                        (["supporting_sources"] if knowledge else []),
    }
    if intent == "comparison" and records:
        result["requirements"].append("direction_and_amount")
        result["comparison_goal"] = (
            "Answer the question directly in the first sentence: say whether the selected period's mean sleep was "
            "more, less, or the same as the previous period, and by how many minutes per night, from difference_min. "
            "Then give both means and their dates. If comparison_state is not available, say plainly that the "
            "comparison cannot be made and why, instead of implying a direction.")
    if closed_stage:
        result["requirements"] = [item for item in result["requirements"] if item != "grounded_interpretation"]
        result["stage_goal"] = (
            "The application composes the requested stages from validated records, with percentages to one decimal. "
            "Query the required records. A pure lookup has no health disclaimer or advice. An unsupported normality judgment "
            "ends with the current evidence gap and at most one feasible next step; do not add causes, grading or general stage theory. "
            "Only an explicit full distribution requests all stages. Independent knowledge requests remain separate.")
    if plan.include_rule_explanation:
        result["rule_goal"] = ("Explain the requested product rule from supplied B passages and obtain the requested "
                               "personal records in this turn. Preserve explicit dates, profile and metrics; "
                               "do not ask the user to repeat them. State any unfinished part specifically.")
    if plan.experience_reply:
        result["followup_goal"] = (
            "First acknowledge what the new user report adds and update the prior understanding. "
            "Use only the few record facts needed for this update; omit onset, wake time and stages unless newly requested. "
            "User experience is not a device measurement: do not infer minutes or that every awakening was the same. "
            "Distinguish good daytime recovery from continued fatigue without diagnosis or inferring a long-term pattern. "
            "Ask at most one useful unanswered question, only if it changes interpretation or next steps. "
            "When the user is done, requests only a summary or declines more questions, end naturally. "
            "An unreported subjective feeling is not a failed record lookup or unfinished record analysis. "
            "If no confirmed record scope exists, clarify which night instead of assigning page defaults.")
    if result["needs_interpretation"]:
        result["interpretation_goal"] = (
            "Answer in one or two short paragraphs by default, including for weekly overviews. "
            "Choose one to three useful record-linked observations; metrics are available evidence, not mandatory sections. "
            "Check source population, profile_age, time scope and applicability internally; "
            "state only conditions that affect the requested conclusion. "
            "Lead with the overall picture, then a noteworthy record and, when helpful, one modest concrete next step; "
            "adapt to the question rather than enforcing a layout or follow-up. "
            "Explain what the observations mean; include only uncertainty that affects this conclusion. "
            "Omit mismatched reference comparisons instead of appending routine daily-sleep or unknown-nap caveats; "
            "explain a scope gap briefly only if needed to answer an explicit reference question. "
            "Do not infer overall quality from duration. "
            "Sleep stages are optional unless asked; do not mechanically grade a single night's deep sleep or REM. "
            "Do not introduce insomnia or disease screening for routine analysis without an explicit question or relevant risk. "
            "Ask at most one core question, only when its answer would materially change interpretation or next steps; "
            "do not ask an answered question or continue after the user declines. "
            "A list of values or a generic limitation alone is not an interpretation. "
            "Do not append an unrequested habit-change program.")
    if intent == "advice":
        result["advice_goal"] = (
            "Give one or two concrete, feasible actions supported by the supplied passages. "
            "For a record-specific request, connect each action to a relevant observation instead of repeating all fields. "
            "State missing context briefly and conditionally; do not assume unreported habits or prescribe personal treatment. "
            "A record recap or a generic limitation alone does not answer a request for advice.")
    return result


def planned_tools(schemas):
    schemas = copy.deepcopy(schemas)
    for schema in schemas:
        schema["function"]["parameters"]["properties"]["response_plan"] = {
            **copy.deepcopy(PLAN_SCHEMA),
            "description": "Optional answer requirements, not reasoning. If used, attach once in the FIRST tool batch; copies in that batch must be identical. Later calls should omit it (an identical accepted plan may be repeated). Do not first introduce or revise a plan after tool events. Omission uses the application plan.",
        }
    return schemas


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate argument or plan field")
        obj[key] = value
    return obj


def unpack_arguments(arguments):
    args = json.loads(arguments, object_pairs_hook=_unique) if isinstance(arguments, str) else copy.deepcopy(arguments)
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be an object")
    proposed = args.pop("response_plan", None)
    if proposed is not None:
        if not isinstance(proposed, dict) or set(proposed) != set(PLAN_SCHEMA["required"]):
            raise ValueError("Response plan requires exactly four fields")
        if proposed["intent"] not in INTENTS or proposed["answer_format"] not in FORMATS:
            raise ValueError("Unknown intent or presentation")
        for key, allowed in (("metrics", METRICS), ("evidence", ("records", "knowledge"))):
            values = proposed[key]
            if not isinstance(values, list) or any(type(v) is not str or v not in allowed for v in values) or len(values) != len(set(values)):
                raise ValueError("Unknown or repeated plan metric/evidence")
    return args, proposed


def refine_query_plan(plan, proposal, question):
    """Refinement cannot remove explicit facts, dates, constraints or scope gates."""
    if plan.application_dialogue or plan.unsupported_window:
        return plan
    required = set(proposal["evidence"])
    intent = proposal["intent"]
    if plan.wants_analysis and plan.task in {"records", "combined"} and intent == "lookup":
        raise ValueError("An explicit analysis request must retain an interpretation, not become a fact-only lookup")
    if "records" in required and (plan.knowledge_only or (plan.task == "health" and not plan.period and not plan.followup and not re.search(r"我|所选|这周|本周|上周|\bmy\b|\bselected\b|p0[123]", question, re.I))):
        raise ValueError("A general knowledge question must not silently become a personal-record lookup")
    if re.search(r"只(?:要|说|看).*(?:平均|均值)|only.*(?:mean|average)", question, re.I) and (intent != "lookup" or "daily" in proposal["metrics"]):
        raise ValueError("Preserve the explicit request for the average alone")
    if intent in {"nightly", "comparison", "interpretation"} and not required:
        raise ValueError("This intent needs evidence")
    if intent in {"nightly", "comparison"} and "records" not in required:
        raise ValueError("A nightly/comparison request needs record evidence")
    if intent == "advice" and "knowledge" not in required:
        raise ValueError("Advice needs supporting knowledge")
    if intent == "interpretation" and "records" not in required:
        raise ValueError("Personal interpretation requires record evidence")
    explicit_records = bool(plan.period or plan.profile_id or plan.wants_analysis or plan.personal_assessment or plan.sleep_overview or re.search(r"查|平均|均值|逐夜|逐晚|比较|compare|average|show.*records", question, re.I))
    if plan.task in {"records", "combined"} and explicit_records and "records" not in required:
        raise ValueError("Cannot drop requested record evidence")
    stage_scope = stage_response_scope(question, plan)
    closed_stage = bool(stage_scope and not stage_scope.independent_question)
    if not closed_stage and (plan.personal_assessment or plan.wants_improvement or re.search(r"正常|健康|标准|normal|healthy|standard", question, re.I)) and "knowledge" not in required:
        raise ValueError("Cannot drop requested interpretation evidence")
    metrics = tuple(dict.fromkeys(proposal["metrics"]))
    requested = requested_detail_metrics(question)
    if plan.task == "records" and intent == "lookup" and requested:
        metrics = tuple(dict.fromkeys((*plan.metrics, *requested)))
    if intent == "nightly" and "daily" not in metrics:
        metrics += ("daily",)
    if intent == "comparison" and not set(metrics) & {"awakenings", "deep", "light", "rem", "stages"}:
        metrics = tuple(dict.fromkeys((*metrics, "comparison")))
    # Explicitly named detailed metrics must survive a model's abstraction.
    if required & {"records"}:
        metrics = tuple(dict.fromkeys((*metrics, *requested_detail_metrics(question))))
    stage_scope = stage_response_scope(question, plan)
    if stage_scope and "stages" not in stage_scope.metrics:
        metrics = tuple(m for m in metrics if m not in {"deep", "light", "rem", "stages"} or m in stage_scope.metrics)
    task = "combined" if required == {"records", "knowledge"} else "records" if required == {"records"} else "health" if required == {"knowledge"} else plan.task
    topics = set(plan.topics)
    if "knowledge" in required:
        mapping = {"awakenings": "night_waking", "awake": "night_waking", "deep": "deep_sleep",
                   "light": "light_sleep", "rem": "rem_sleep", "stages": "sleep_stages", "sleep_onset": "circadian"}
        topics.update(mapping[metric] for metric in metrics if metric in mapping)
        if intent == "interpretation" and set(metrics) & {"deep", "light", "rem", "stages"}:
            topics.add("stage_distribution")
    return replace(plan, task=task, metrics=metrics, topics=tuple(sorted(topics)))
