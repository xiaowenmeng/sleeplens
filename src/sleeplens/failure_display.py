"""Render scoped evidence with current-lookup priority and valid history reuse."""

from dataclasses import replace
from copy import deepcopy
from datetime import date, timedelta
import re

from sleeplens.query_policy import render_facts, requested_detail_metrics
from sleeplens.reply_policy import (
    data_gap_reply, message, policy_trace, record_issue, stage_facts, stage_question,
    stage_values, unavailable_period_reply, field_labels,
    stage_response_scope, stage_limitation, comparison_available,
    stage_record_gap,
    stage_display_values,
)


def period_limit_text(output, language):
    today = date.fromisoformat(output["as_of_date"])
    period = output.get("period") or {}
    return unavailable_period_reply((period.get("start_date"), period.get("end_date")), today, language)


def expected_record_scope(plan, selection):
    profile = plan.profile_id or selection.get("profile_id")
    period = plan.period or ((selection.get("start_date"), selection.get("end_date")) if selection else None)
    comparison = plan.compare_previous
    if comparison is None and "comparison" in plan.metrics:
        comparison = True
    if period and period[0] == period[1]:
        comparison = False
    return {"profile_id": profile, "period": list(period) if period else None, "compare_previous": comparison}


def scoped_record(output, plan, selection):
    """Reuse only a usable matching scope; a failed lookup is never evidence."""
    expected = expected_record_scope(plan, selection)
    period = expected["period"]
    if (plan.task not in {"records", "combined"} or not output or not output.get("current")
            or output.get("status") not in {"ok", "partial_data", "no_data"}
            or not period or output.get("profile_id") != expected["profile_id"]
            or output.get("period") != {"start_date": period[0], "end_date": period[1]}):
        return None
    if expected["compare_previous"] is True:
        start = date.fromisoformat(period[0])
        prior = {"start_date": (start-timedelta(days=7)).isoformat(), "end_date": (start-timedelta(days=1)).isoformat()}
        if not output.get("previous") or output.get("previous_period") != prior:
            return None
    if expected["compare_previous"] is False and output.get("previous_period"):
        output = deepcopy(output)
        output.update(previous=None, previous_period=None, difference_min=None, comparison_state="not_requested")
        output["daily_records"]["previous"] = None
    return output


def stage_assessment_reply(plan, language, *, record=None, lookup=None, selection=None, today=None):
    """Compatibility entry for the centralized stage and data reply policy."""
    if not stage_question(plan):
        return None
    period = expected_record_scope(plan, selection or {})["period"] if plan.task == "combined" else plan.period
    if today is None and lookup and lookup.get("as_of_date"):
        today = date.fromisoformat(lookup["as_of_date"])
    if not record and period and today and date.fromisoformat(period[1]) > today:
        return unavailable_period_reply(period, today, language)
    issue = record_issue(record, lookup, plan, language)
    values = stage_values(plan, record, language)[0] if record else []
    facts = stage_facts(values, language)
    if issue:
        return "\n\n".join(part for part in (facts, issue[2]) if part)
    if not record and not plan.knowledge_only:
        return message("unqueried", language)
    limitation = stage_limitation(language, can_compare=bool(record and comparison_available(record)))
    return "\n\n".join(part for part in (facts, limitation) if part)


def overview_facts(output, plan, language):
    """Keep a failed broad interpretation's record recap readable and scoped."""
    zh = language == "Chinese"
    lines = (["| 日期 | 有效记录 | 平均睡眠 |", "| --- | --- | --- |"] if zh else
             ["| Dates | Recorded nights | Mean sleep |", "| --- | --- | --- |"])
    for scope, period_key in (("current", "period"), ("previous", "previous_period")):
        stats, period = output.get(scope), output.get(period_key)
        if not stats or not period:
            continue
        value = stats["mean_sleep_min"]
        mean = (f"{value:.1f}" + ("分钟" if zh else " min")) if value is not None else ("无记录" if zh else "Unavailable")
        lines.append(f"| {period['start_date']}–{period['end_date']} | {stats['valid_nights']}/{stats['expected_nights']} | {mean} |")
    if output.get("previous"):
        delta = output.get("difference_min")
        if output.get("comparison_state") == "available" and delta is not None:
            lines.append(f"\n平均时长变化：{delta:+.1f}分钟。" if zh else f"\nMean duration change: {delta:+.1f} min.")
        else:
            lines.append("\n有效记录不足，暂不比较两周变化。" if zh else "\nToo few recorded nights to compare the weeks.")
    details = [("sleep_onset", "mean_sleep_onset", "入睡时刻", "Sleep onset", "", ""),
               ("wake_time", "mean_wake_time", "最终醒来", "Final wake-up", "", ""),
               ("awakenings", "mean_night_awakenings", "夜醒次数", "Awakenings", "次", " / night"),
               ("awake", "mean_awake_min", "中途清醒", "Awake time", "分钟", " min"),
               ("deep", "mean_deep_sleep_min", "深睡", "Deep sleep", "分钟", " min"),
               ("light", "mean_light_sleep_min", "浅睡", "Light sleep", "分钟", " min"),
               ("rem", "mean_rem_sleep_min", "REM", "REM", "分钟", " min")]
    metrics = set(plan.metrics)
    if "stages" in metrics:
        metrics.update(("deep", "light", "rem"))
    selected = [item for item in details if item[0] in metrics and output["current"].get(item[1]) is not None]
    if selected:
        lines += (["\n| 所选期间的详细指标 | 每晚平均 |", "| --- | --- |"] if zh else
                  ["\n| Selected period details | Nightly mean |", "| --- | --- |"])
        for _, key, cn, en, cn_unit, en_unit in selected:
            value = output["current"][key]
            formatted = value if isinstance(value, str) else f"{value:.1f}"
            lines.append(f"| {cn if zh else en} | {formatted}{cn_unit if zh else en_unit} |")
        count = output["current"].get("detail_nights", 0)
        if count != output["current"]["valid_nights"]:
            lines.append(f"\n详细指标依据{count}晚记录。" if zh else f"\nDetail means use {count} nights.")
    elif metrics.intersection(item[0] for item in details):
        lines.append("\n这些日期没有可用的详细指标记录。" if zh else "\nDetailed metrics are unavailable for these dates.")
    return "\n".join(lines)


def add_verified_fallback(result, plan, *, health_available, history_record=None, today=None):
    language = result["answer_language"]
    zh = language == "Chinese"
    lookups = [event["result"] for event in result["tool_events"]
               if event["tool"] == "analyze_sleep" and isinstance(event.get("result"), dict)]
    raw = lookups[-1] if lookups else history_record
    selection = result.get("selected_query") or {}
    latest = scoped_record(raw, plan, selection)
    result["record_context"] = {
        "source": "current_tool" if lookups else "history" if history_record else "none",
        "status": raw.get("status") if raw else None,
        "scope_matches": latest is not None,
        "scope": expected_record_scope(plan, selection),
    }
    availability = {"state": "not_queried", "message": None}
    if raw and latest is None:
        availability["state"] = ("lookup_failed" if lookups and raw.get("status") not in {"ok", "partial_data", "no_data"}
                                 else "scope_unavailable")
    if latest:
        stats = latest["current"]
        if stats["valid_nights"] == 0:
            availability.update(state="no_records", message=(
                "所请求日期没有可用睡眠记录，无法完成这部分记录解读。" if zh else
                "No usable sleep records are available for the requested dates."))
        elif any(s.get("detail_nights", 0) < s["valid_nights"]
                 for s in (latest["current"], latest.get("previous")) if s):
            order = ("sleep_onset", "wake_time", "night_awakenings", "awake_min", "deep_sleep_min", "light_sleep_min", "rem_sleep_min")
            missing = [name for name in order if any(row.get("sleep_valid") and row.get(name) is None
                       for rows in (latest.get("daily_records") or {}).values() for row in rows or [])]
            labels = ("、" if zh else ", ").join(field_labels(missing, language)) or ("详细指标" if zh else "detailed metrics")
            availability.update(state="missing_details", message=(
                f"部分记录缺少{labels}；解读仅使用已有字段。" if zh else
                f"Some records lack {labels}; interpretation uses the available fields."))
        elif any(s["valid_nights"] < s["expected_nights"]
                 for s in (latest["current"], latest.get("previous")) if s):
            availability.update(state="partial_records", message=(
                "所请求日期中有记录缺失，解读仅覆盖已有记录。" if zh else
                "Some requested dates have no records; interpretation covers the available records only."))
        else:
            availability["state"] = "available"
    result["record_availability"] = availability
    issue = record_issue(latest, raw if lookups else None, plan, language)
    scope = stage_response_scope(result["question"], plan)
    # Compose known calculations and the requested judgment as separate parts.
    # Model prose about the same unresolved judgment has no continuation slot.
    if scope and latest:
        focused = replace(plan, metrics=scope.metrics)
        issue = record_issue(latest, raw if lookups else None, focused, language)
        values, _, _ = stage_values(focused, latest, language)
        values = stage_display_values(values, result["question"])
        facts = stage_facts(values, language)
        if issue:
            notice = issue[2]
            if issue[1] in {"no_records", "unavailable_record"}:
                notice = stage_record_gap(latest, scope.metrics, language, issue[1])
            tail = notice
            category, reason = issue[:2]
        else:
            tail = stage_limitation(language, can_compare=comparison_available(latest)) if scope.intent == "assessment" else ""
            category, reason = ("knowledge_insufficient", "stage_normality") if tail else ("record_answer", "stage_lookup")
        base = ((facts + (" " if not zh else "") + tail) if facts and tail and "|" not in facts else
                "\n\n".join(part for part in (facts, tail) if part))
        parts = [part for part in (base, result.get("independent_stage_answer")) if part]
        extra_metrics = tuple(m for m in requested_detail_metrics(result["question"]) if m in {"sleep_onset", "wake_time", "awakenings", "awake"})
        if extra_metrics:
            parts.append(render_facts(latest, replace(plan, metrics=extra_metrics), language))
        result["answer"] = "\n\n".join(parts)
        result["calculations"] = values
        result["stage_response"] = {"intent": scope.intent, "metrics": list(scope.metrics)}
        result.pop("verified_record_facts", None)
        if (not latest["current"]["valid_nights"] and plan.compare_previous is True
                and (latest.get("previous") or {}).get("valid_nights")):
            previous_values = stage_values(focused, {"daily_records": {"current": latest["daily_records"]["previous"]}}, language)[0]
            if previous_values:
                result["verified_record_facts"] = ("此前七天已核实的记录：\n\n" if zh else "Verified records for the preceding seven days:\n\n") + stage_facts(previous_values, language)
                result["calculations"] += previous_values
        result["answer_validation"]["fallback"] = "stage_assessment" if scope.intent == "assessment" else "stage_lookup"
        result["reply_policy"] = policy_trace(category, reason, partial=bool(tail and values))
        if values and not scope.independent_question:
            result["status"] = "answered"
        return
    failed = result["status"] != "answered"
    partial = result["answer_validation"].get("status") == "partial"
    record_missing = result.get("record_part_missing")
    searches = [e.get("result") or {} for e in result["tool_events"] if e["tool"] == "search_sleep_knowledge"]
    requested_health = plan.task in {"health", "combined"} and (
        plan.wants_improvement or plan.causality_question or plan.wants_analysis or stage_question(plan))
    explicit_gap = re.search(r"(?:无法|不能|还没有|没有|缺少|不足).{0,25}(?:判断|解释|原因|建议|依据|确定)|"
                             r"\b(?:cannot|can't|could not|couldn't|no evidence|insufficient)\b", result["answer"], re.I)
    health_gap = (not failed and requested_health and searches and not health_available and not explicit_gap
                  and any(s.get("status") in {"no_results", "tool_error"} for s in searches))
    if health_gap:
        partial = True
        result["answer_validation"]["status"] = "partial"
    if not failed and not partial and not record_missing and not issue:
        return
    # Input/scope clarification already has a specific, safe response. Do not
    # replace it with a service or knowledge failure.
    code = (result.get("error") or {}).get("code")
    if code in {"invalid_question", "invalid_fixture_flag", "date_clarification"}:
        return
    prior_facts = ""
    if latest and not latest["current"]["valid_nights"] and (latest.get("previous") or {}).get("valid_nights"):
        prior = deepcopy(latest)
        prior.update(period=latest["previous_period"], current=latest["previous"], previous=None, previous_period=None,
                     difference_min=None, comparison_state="not_requested")
        prior["daily_records"] = {"current": latest["daily_records"]["previous"], "previous": None}
        prior_plan = replace(plan, compare_previous=False, metrics=tuple(m for m in plan.metrics if m != "comparison"))
        prior_facts = (stage_facts(stage_values(prior_plan, prior, language)[0], language) if stage_question(plan) else
                       render_facts(prior, prior_plan, language))
        if prior_facts:
            result["verified_record_facts"] = ("此前七天已核实的记录：\n\n" if zh else "Verified records for the preceding seven days:\n\n") + prior_facts
    if stage_question(plan) and (failed or partial or issue):
        reply = stage_assessment_reply(plan, language, record=latest, lookup=raw if lookups else None,
                                       selection=selection, today=today)
        if reply:
            values = stage_values(plan, latest, language)[0] if latest else []
            supported = result.get("independent_stage_answer", "")
            if supported and result.get("record_failure_notice"):
                supported = supported.removeprefix(result["record_failure_notice"]).strip()
            result["calculations"] = values
            if issue:
                category, reason = issue[:2]
            elif code:
                category, reason = "tool_failure", "service_failure"
                if not latest:
                    reply = message("service_failure", language)
            elif not latest and not plan.knowledge_only:
                category, reason = "data_missing", "record_not_obtained"
            else:
                category, reason = "knowledge_insufficient", "stage_normality"
            result["answer"] = reply + ("\n\n" + supported if supported else "")
            if not prior_facts:
                result.pop("verified_record_facts", None)
            result["answer_validation"]["fallback"] = "stage_assessment"
            result["reply_policy"] = policy_trace(category, reason, partial=bool(values or supported or prior_facts))
            return
    # A successful local lookup is independent of the quality of model prose.
    if latest and latest["current"]["valid_nights"] and (failed or record_missing or (issue and issue[1] in {"missing_fields", "invalid_fields"})):
        metrics = plan.metrics
        if plan.wants_improvement and plan.compare_previous is True and "comparison" not in metrics:
            metrics += ("comparison",)
        if "mean" in metrics and "coverage" not in metrics:
            metrics += ("coverage",)
        if plan.sleep_overview and latest["period"]["start_date"] != latest["period"]["end_date"] and "daily" not in metrics:
            result["verified_record_facts"] = overview_facts(latest, plan, language)
        else:
            result["verified_record_facts"] = render_facts(latest, replace(plan, metrics=metrics), language)
        result["answer_validation"]["fallback"] = "verified_current_records"
    if issue:
        category, reason, notice = issue
        if not failed and record_missing:
            if not prior_facts:
                result["verified_record_facts"] = notice
            result["reply_policy"] = policy_trace(category, reason, partial=True)
            return
        if not failed and result.get("record_failure_notice"):
            # accept() already prepended this notice to checked health content.
            pass
        elif not failed and re_has_health_citation(result["answer"]):
            result["answer"] = notice + "\n\n" + result["answer"]
        else:
            result["answer"] = notice
        if latest and not latest["current"]["valid_nights"]:
            result["answer_validation"]["fallback"] = "no_current_records"
        result["reply_policy"] = policy_trace(category, reason, partial=not failed or bool(result.get("verified_record_facts")))
        return
    if not failed:
        # Retain revalidated paragraphs; explain the omitted health conclusion.
        if partial and plan.task in {"health", "combined"}:
            knowledge_error = health_gap and any(s.get("status") == "tool_error" for s in searches)
            key = ("knowledge_read_failure" if knowledge_error else "advice_limit" if plan.wants_improvement else
                   "cause_limit" if plan.causality_question else "interpretation_limit")
            result["answer"] += "\n\n" + message(key, language)
            result["reply_policy"] = policy_trace("tool_failure" if knowledge_error else "knowledge_insufficient", key, partial=True)
        return
    if code:
        key = "knowledge_read_failure" if code in {"skill_unavailable", "knowledge_unavailable"} else "service_failure"
        result["answer"] = message(key, language)
        result["reply_policy"] = policy_trace("tool_failure", key, partial=bool(result.get("verified_record_facts")))
    else:
        record_only = plan.task == "records" and not plan.wants_analysis and not plan.wants_improvement
        key = ("answer_unavailable" if record_only else "advice_limit" if plan.wants_improvement else "interpretation_limit") if result.get("verified_record_facts") else "knowledge_insufficient"
        result["answer"] = message(key, language)
        result["reply_policy"] = policy_trace("tool_failure" if key == "answer_unavailable" else "knowledge_insufficient",
                                             "answer_unavailable" if key == "answer_unavailable" else None,
                                             partial=bool(result.get("verified_record_facts")))


def re_has_health_citation(text):
    return bool(re.search(r"\[H\d+:[A-Za-z0-9_-]+\]", text))
