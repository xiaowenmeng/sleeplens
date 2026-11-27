"""Render validated record facts for chat and CLI; tool values stay unrounded."""

from dataclasses import replace
from datetime import datetime


WARNING_TEXT = {
    "zero_value_requires_verification": "有效0分钟记录已保留，但需核验；不能据此认定整夜未睡。",
    "incomplete_coverage": "有不可用记录，均值仅描述有效夜；缺失分布可能影响比较。",
    "descriptive_comparison_only": "差值只描述记录时长，不代表统计显著、变化原因、睡眠质量或诊断。",
    "comparison_requires_four_nights": "两段均至少4夜有效才比较，这是产品规则，不是医学标准。",
}

ERROR_TEXT = {
    "unknown_profile": "请选择P01、P02或P03。",
    "invalid_compare_previous": "比较选项必须是布尔值。",
    "invalid_date": "请输入真实日期，格式为YYYY-MM-DD。",
    "invalid_period": "请选择一个醒来日期，或正好包含7天的起止日期。",
    "single_day_comparison_not_supported": "单日查询请关闭与前7夜比较。",
    "date_out_of_range": "无法计算超出日历范围的前一周期。",
    "period_not_finished": "只能分析截至今天醒来日期（昨晚的睡眠）的记录。",
    "dataset_unavailable": "无法读取本地数据，未生成统计结果。",
}


def format_analysis(result: dict) -> str:
    lines = ["SleepLens · 离线分析（合成数据；未调用模型）", f"状态：{result['status']}"]
    if result["error"]:
        error = result["error"]
        lines.append("原因：" + ERROR_TEXT.get(error["code"], error["message"]))
        return "\n".join(lines)
    lines.extend([f"角色：{result['profile_id']}",
                  f"数据版本：{result['dataset_version']}；规则版本：{result['rule_version']}"])
    for scope, label in (("current", "本期"), ("previous", "前期")):
        stats = result[scope]
        if stats is None:
            continue
        period = result["period"] if scope == "current" else result["previous_period"]
        mean = "不可计算" if stats["mean_sleep_min"] is None else f"{stats['mean_sleep_min']:.1f}分钟"
        lines.append(
            f"{label} {period['start_date']}—{period['end_date']}："
            f"有效{stats['valid_nights']}/{stats['expected_nights']}夜，覆盖率{stats['coverage']:.1%}，"
            f"有效记录均值{mean}"
        )
    state = result["comparison_state"]
    if state == "available":
        lines.append(f"本期减前期：{result['difference_min']:+.1f}分钟")
    elif state == "insufficient_data":
        lines.append("两周差值：不可计算（至少一段有效记录不足4夜）")
    seen = set()
    for warning in result["warnings"]:
        code = warning["code"]
        if code not in seen:
            lines.append("提示：" + WARNING_TEXT.get(code, warning["message"]))
            seen.add(code)
    return "\n".join(lines)


def comparison_answer(output, language):
    """One sentence answering "more or less than the previous week?", or None.

    Uses only the validated difference; the amount is per night, to one decimal.
    """
    delta = output.get("difference_min")
    if not output.get("previous"):
        return None
    chinese = language == "Chinese"
    if delta is None:
        return ("还不能判断比前一周睡得多还是少：每周至少需要4晚有效记录才能比较。" if chinese else
                "I can't tell whether you slept more or less than the previous week: each week needs at least 4 recorded nights to compare.")
    if round(delta, 1) == 0:
        return "两周平均每晚的睡眠时长相同。" if chinese else "You slept the same amount per night as the previous week, on average."
    word_zh, word_en = ("多", "more") if delta > 0 else ("少", "less")
    if chinese:
        return f"比前一周睡得{word_zh}：平均每晚{word_zh}{abs(delta):.1f}分钟。"
    return f"You slept {word_en} than the previous week: {abs(delta):.1f} minutes {word_en} per night on average."


def record_summary(output, language, *, lead_with_change=False):
    """Render personal statistics solely from the validated Python result.

    With lead_with_change, a comparison opens with the direct "more/less" answer.
    """
    chinese = language == "Chinese"
    lead = comparison_answer(output, language) if lead_with_change else None
    def period(label, stats):
        count, expected = stats["valid_nights"], stats["expected_nights"]
        mean = stats["mean_sleep_min"]
        hours, minutes = divmod(round(mean, 1), 60) if mean is not None else (0, 0)
        if chinese:
            return (f"{label}有{count}/{expected}晚有效记录" +
                    (f"，平均每晚睡了{int(hours)}小时{minutes:g}分钟（{mean:.1f}分钟）" if mean is not None else "，暂无可用均值"))
        return (f"{label}: {count}/{expected} recorded nights" +
                (f", averaging {mean:.1f} minutes" if mean is not None else ", no available average"))
    dates = output.get("period") or {}
    date_range = f"{dates.get('start_date', '')}—{dates.get('end_date', '')}"
    if output["current"]["expected_nights"] == 14:
        label = f"你查看的这两周（{date_range}）" if chinese else f"The 14 nights you selected ({date_range})"
    else:
        label = f"你查看的这一周（{date_range}）" if chinese else f"The seven nights you selected ({date_range})"
    text = period(label, output["current"])
    if output.get("previous"):
        text += ("；" if chinese else "; ") + period("此前一周" if chinese else "The preceding seven nights", output["previous"])
        difference = output.get("difference_min")
        if lead:
            pass  # The opening sentence already answers the comparison.
        elif difference is None:
            text += "。有效记录不足，暂不比较这两周的变化" if chinese else ". Too few recorded nights to compare the weeks"
        elif chinese:
            text += f"。平均每晚比此前一周{'多' if difference > 0 else '少'}{abs(difference):.1f}分钟" if round(difference, 1) else "。两周平均时长相同"
        elif round(difference, 1):
            text += f". That is {abs(difference):.1f} minutes {'more' if difference > 0 else 'less'} per night than the preceding seven nights"
        else:
            text += ". Both weeks have the same mean"
    text += "。" if chinese else "."
    return f"{lead}{'' if chinese else ' '}{text}" if lead else text


def render_detail_facts(output, requested, language, *, daily=False, include_means=False):
    """Render extended measurements without having the model copy numbers."""
    zh = language == "Chinese"
    stats = output["current"]
    count = stats.get("detail_nights", 0)
    dates = output.get("period") or {}
    if not count:
        text = (f"{dates.get('start_date')}—{dates.get('end_date')}没有可用的详细记录，暂时无法计算这些指标。" if zh else
                f"No usable detailed records are available for {dates.get('start_date')}–{dates.get('end_date')}; these metrics cannot be calculated.")
        available = output.get("available_period")
        if available:
            text += (f"目前已有记录的日期范围是{available['start_date']}—{available['end_date']}，可以另行指定这段时间查询。" if zh else
                     f" Available records cover {available['start_date']}–{available['end_date']}; you can request those dates separately.")
        return text
    items = []
    specs = [("sleep_onset", "mean_sleep_onset", "平均入睡时刻", "Mean sleep onset", ""),
             ("wake_time", "mean_wake_time", "平均最终醒来时刻", "Mean final wake-up", ""),
             ("awakenings", "mean_night_awakenings", "平均每晚夜醒", "Mean awakenings per night", "次" if zh else " awakenings"),
             ("awake", "mean_awake_min", "平均每晚夜间清醒", "Mean awake time per night", "分钟" if zh else " min"),
             ("deep", "mean_deep_sleep_min", "平均每晚深睡", "Mean deep sleep per night", "分钟" if zh else " min"),
             ("light", "mean_light_sleep_min", "平均每晚浅睡", "Mean light sleep per night", "分钟" if zh else " min"),
             ("rem", "mean_rem_sleep_min", "平均每晚REM睡眠", "Mean REM sleep per night", "分钟" if zh else " min")]
    selected = [spec for spec in specs if spec[0] in requested or ("stages" in requested and spec[0] in {"deep", "light", "rem"})]
    for metric, key, chinese, english, unit in selected:
        value = stats.get(key)
        if value is not None:
            formatted = value if isinstance(value, str) else f"{value:.1f}"
            items.append(f"{chinese if zh else english}：{formatted}{unit}")
    intro = f"{dates.get('start_date')}—{dates.get('end_date')}"
    text = "" if daily and not include_means else intro + "\n" + ("；" if zh else "; ").join(items) + ("。" if zh else ".")
    expected = stats["expected_nights"]
    if count < expected:
        text += (f"\n{count}/{expected}晚有详细记录，缺失未补零。" if zh else
                 f"\n{count}/{expected} nights have detailed records; missing nights were not filled with zero.")
    if daily:
        fields = {"sleep_onset": "sleep_onset", "wake_time": "wake_time", "awakenings": "night_awakenings",
                  "awake": "awake_min", "deep": "deep_sleep_min", "light": "light_sleep_min", "rem": "rem_sleep_min"}
        headings = {"sleep_onset": ("入睡时刻", "Sleep onset"), "wake_time": ("最终醒来", "Final wake-up"),
                    "awakenings": ("夜醒次数", "Awakenings"), "awake": ("清醒分钟数", "Awake minutes"),
                    "deep": ("深睡分钟数", "Deep minutes"), "light": ("浅睡分钟数", "Light minutes"), "rem": ("REM分钟数", "REM minutes")}
        header = ["醒来日期" if zh else "Waking date"] + [headings[metric][0 if zh else 1] for metric, *_ in selected]
        text += ("\n\n" if text else "") + "| " + " | ".join(header) + " |\n| " + " | ".join("---" for _ in header) + " |"
        for row in (output.get("daily_records") or {}).get("current") or []:
            cells = [row["record_date"]]
            for metric, *_ in selected:
                value = row.get(fields[metric])
                cells.append(str(value) if value is not None else ("缺少记录" if zh else "Unavailable"))
            text += "\n| " + " | ".join(cells) + " |"
    return text + "\n\n" if daily else text


def render_facts(output, plan, language):
    """Select facts without asking the LLM to copy or convert any numbers."""
    period = output.get("period") or {}
    if period.get("start_date") and period.get("start_date") == period.get("end_date"):
        return render_single_record(output, plan, language)
    zh = language == "Chinese"
    metrics = set(plan.metrics)
    details = metrics & {"sleep_onset", "wake_time", "awakenings", "awake", "deep", "light", "rem", "stages"}
    if details:
        text = render_detail_facts(output, details, language, daily="daily" in metrics,
                                   include_means=plan.include_detail_means)
        remaining = metrics - details - {"daily"}
        if remaining:
            text += "\n" + render_facts(output, replace(plan, metrics=tuple(remaining)), language)
        return text
    if (plan.brief_record_recap or plan.lead_change) and output.get("difference_min") is not None:
        cur, prev, delta = output["current"], output["previous"], output["difference_min"]
        if zh:
            change = f"平均每晚比此前一周{'少' if delta < 0 else '多'}{abs(delta):.1f}分钟" if delta else "两周平均时长相同"
            means = f"这一周平均{cur['mean_sleep_min']:.1f}分钟、此前一周{prev['mean_sleep_min']:.1f}分钟"
            return (change + "，" + means if plan.lead_change else means + "，" + change) + "。"
        change = (f"{abs(delta):.1f} minutes {'more' if delta > 0 else 'less'} per night" if round(delta, 1)
                  else "the same mean per night")
        return f"The selected period averaged {cur['mean_sleep_min']:.1f} minutes, versus {prev['mean_sleep_min']:.1f} previously: {change}."
    if not metrics or "comparison" in metrics:
        # A comparison question gets its "more or less" answer first.
        return record_summary(output, language, lead_with_change="comparison" in metrics)
    current = output["current"]
    parts = []
    if "mean" in metrics:
        mean = current["mean_sleep_min"]
        if mean is None:
            parts.append("所选期间没有有效记录，暂无可用均值。" if zh else "No valid records are available for an average.")
        else:
            hours, minutes = divmod(round(mean, 1), 60)
            duration = f"{int(hours)}小时{minutes:g}分钟" if zh else f"{int(hours)} h {minutes:g} min"
            dates = output.get("period") or {}
            span = "这两周" if current["expected_nights"] == 14 else "这一周"
            label = f"你查看的{span}（{dates.get('start_date', '')}—{dates.get('end_date', '')}）"
            parts.append(f"{label}平均每晚睡了{duration}（{mean:.1f}分钟）。" if zh else f"Average recorded sleep: {duration} ({mean:.1f} minutes).")
            expected = current["expected_nights"]
            if current["valid_nights"] < expected:
                parts.append(f"均值仅依据{current['valid_nights']}/{expected}晚有效记录。" if zh else f"Based on {current['valid_nights']}/{expected} recorded nights only.")
    if "coverage" in metrics:
        n, expected = current["valid_nights"], current["expected_nights"]
        parts.append(f"有{n}/{expected}晚有效记录，缺少{expected-n}晚，覆盖率{current['coverage']:.1%}。" if zh else f"{n}/{expected} recorded nights; {expected-n} unavailable; coverage {current['coverage']:.1%}.")
    daily = (output.get("daily_records") or {}).get("current") or []
    valid = [row for row in daily if row["sleep_valid"]]
    if "extrema" in metrics:
        if valid:
            choices = []
            if "longest" not in metrics or "shortest" in metrics:
                choices.append(("最短" if zh else "Shortest", min(r["sleep_min"] for r in valid)))
            if "shortest" not in metrics or "longest" in metrics:
                choices.append(("最长" if zh else "Longest", max(r["sleep_min"] for r in valid)))
            for label, value in choices:
                dates = ", ".join(row["record_date"] for row in valid if row["sleep_min"] == value)
                parts.append(f"{label}：{dates}，{value}分钟。" if zh else f"{label}: {dates}, {value} minutes.")
        else:
            parts.append("暂无有效逐夜记录可比较。" if zh else "No valid nightly records are available to compare.")
    if "daily" in metrics:
        parts.extend(f"{r['record_date']}: " + (f"{r['sleep_min']} min" if r["sleep_valid"] else ("无记录" if zh else "unavailable")) for r in daily)
    return "\n".join(parts) or record_summary(output, language)


def render_single_record(output, plan, language):
    """Describe the requested row without aggregating or substituting dates."""
    zh = language == "Chinese"
    day = output["period"]["start_date"]
    rows = (output.get("daily_records") or {}).get("current") or []
    row = next((r for r in rows if r["record_date"] == day), None)
    if not row or not row["sleep_valid"]:
        return (f"{day}没有可用的睡眠记录，无法判断当天的睡眠情况。" if zh else
                f"No usable sleep record is available for {day}.")
    metrics = set(plan.metrics) - {"daily", "coverage", "comparison", "extrema", "shortest", "longest"}
    if not metrics:
        metrics = {"mean", "sleep_onset", "wake_time", "awakenings", "awake", "stages"}
    if "stages" in metrics:
        metrics.update({"deep", "light", "rem"})
    parts = []
    if "mean" in metrics:
        hours, minutes = divmod(row["sleep_min"], 60)
        parts.append(f"睡眠时长{hours}小时{minutes}分钟" if zh else f"Sleep duration: {hours} h {minutes} min")
    fields = [("sleep_onset", "sleep_onset", "入睡", "Sleep onset"), ("wake_time", "wake_time", "最终醒来", "Final wake-up"),
              ("awakenings", "night_awakenings", "夜间醒来", "Awakenings"), ("awake", "awake_min", "夜间清醒", "Awake"),
              ("deep", "deep_sleep_min", "深睡", "Deep sleep"), ("light", "light_sleep_min", "浅睡", "Light sleep"),
              ("rem", "rem_sleep_min", "REM睡眠", "REM sleep")]
    for metric, field, cn, en in fields:
        if metric not in metrics:
            continue
        value = row.get(field)
        if value is None:
            description = "缺少记录" if zh else "unavailable"
        elif metric in {"sleep_onset", "wake_time"}:
            description = datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        else:
            description = f"{value}" + (("次" if metric == "awakenings" else "分钟") if zh else (" times" if metric == "awakenings" else " min"))
        parts.append(f"{cn if zh else en}：{description}")
    if not parts:
        parts.append("当天有有效记录" if zh else "A valid record is available")
    return (f"{day}的睡眠记录：\n" if zh else f"Sleep record for {day}:\n") + ("；" if zh else "; ").join(parts) + ("。时间为Europe/Berlin当地时间。" if zh else ". Times are local to Europe/Berlin.")
