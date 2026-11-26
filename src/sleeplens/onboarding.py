"""First-use information from the same validated data provider as record tools."""

import argparse
from collections import Counter
from datetime import date, timedelta

from sleeplens import analysis
from sleeplens.data import DETAIL_FIELDS, PROFILE_IDS, DataQualityError
from sleeplens.knowledge import load_knowledge


COPY = {
    "中文": {
        "intro": "SleepLens 是面向成年用户的睡眠记录分析助手，帮助你查询记录、理解指标，并比较近期记录的变化。它结合睡眠知识资料与查询、计算工具，减少翻找记录和手动计算的负担。",
        "demo": "当前版本使用合成数据进行课程演示，档案不对应真实个人。",
        "examples": "可以这样提问", "prepare_hint": "点击示例仅填入问题；确认后发送才会开始问答。可从左上角展开侧栏，选择档案与日期。",
        "data": "数据详情", "about": "关于 SleepLens / 使用说明", "classroom": "课堂测试示例",
        "classroom_hint": "用于检查系统如何处理限制；点击仅填入问题，不自动发送。",
        "about_text": "面向希望看懂睡眠记录的成年用户，可查询单晚数据、计算阶段占比、汇总连续七天的记录，并比较相邻两周的平均睡眠时长。记录查询取得实际数值，计算工具负责统计，睡眠知识资料支持一般解释；三者用途不同。\n\n回答下方的参考依据可查看实际引用的资料，计算详情可核对日期、所用数据和已完成的运算。缺少记录或可靠依据时会说明限制；不提供疾病诊断或个人用药方案。\n\n本项目使用合成示例，当前测试不能证明产品能改善睡眠或产生临床效果。切换查询后开始新的对话，也可在侧栏点击“清空对话”。",
        "date_rule": "日期以醒来日为准，例如所选日期的记录对应当天最终醒来的那次睡眠；只支持今天之前的醒来日期。",
        "data_rule": "日期范围不代表每天都有完整数据。无记录、标记不可用和缺少字段分开统计，缺失不会按 0 处理；时刻沿用 Europe/Berlin 当地时间及实际时区偏移。",
        "not_recorded": "当前没有上床时间、入睡潜伏期、分期时间线或诊断评分，不能据此推算这些指标。",
        "raw": "原始记录字段", "computed": "可计算的指标", "metric": "名称", "meaning": "含义", "unit": "单位",
        "profile": "当前档案", "dates": "可查询的记录日期", "empty_dates": "当前没有可查询的记录日期",
        "counts": "{unique}个唯一记录日期 · {valid}晚有效 · {missing}天无记录 · {unavailable}晚标记不可用",
        "date_lists": "缺失日期与记录完整性", "missing": "范围内没有记录的日期", "unavailable": "已存在但标记不可用的日期",
        "incomplete": "有效记录中详细字段不完整的日期", "duplicates": "重复日期", "none": "无",
        "source_counts": "源文件共{rows}条记录、{unique}个唯一日期，覆盖{calendar}个日历日；其中{complete}晚详细字段齐全。",
        "read_error": "睡眠数据暂时无法读取，概览和数据示例暂不可用。你仍可阅读使用说明或了解指标含义。",
        "duplicate_record": "睡眠数据中存在重复日期，暂时无法提供可靠概览。请更正数据后重试。",
        "incomplete_data": "睡眠数据存在不完整字段，暂时无法提供可靠概览。请更正数据后重试。",
        "invalid_data": "睡眠数据存在无效或不一致的记录，暂时无法提供可靠概览。请更正数据后重试。",
        "labels": {"duration": "查单晚睡眠时长", "deep": "计算深睡占比", "stages": "看完整阶段分布", "period": "看七天均值或变化", "knowledge": "深睡是什么意思？", "normality": "检查判断边界", "no_records": "无记录日期", "medical": "诊断边界", "outside": "范围外问题"},
    },
    "English": {
        "intro": "SleepLens is an adult sleep-record assistant for looking up nights, understanding metrics and comparing recent records. It combines sleep information with data queries and calculations to reduce manual searching and arithmetic.",
        "demo": "This course demonstration uses synthetic data. Profiles do not represent real people.",
        "examples": "Try a question", "prepare_hint": "An example only fills the input; review and send it to start a response. Open the sidebar at the top left to choose a profile and dates.",
        "data": "Data details", "about": "About SleepLens / How to use", "classroom": "Classroom test examples",
        "classroom_hint": "Use these to check how the system handles limits. Clicking only prepares a question; it does not send it.",
        "about_text": "For adults who want to understand sleep records: look up a night, calculate stage percentages, summarize seven consecutive days, or compare mean sleep duration across adjacent weeks. Record queries provide measurements, calculation tools produce statistics, and sleep information supports general explanations.\n\nSources below an answer show the material actually cited. Calculation details let you check dates, data and completed calculations. Missing records or insufficient evidence are explained; SleepLens does not diagnose disease or provide personal medication plans.\n\nThese are synthetic examples. Current tests do not establish improved sleep or clinical effects. Changing the record selection starts a fresh conversation; you can also use Clear conversation in the sidebar.",
        "date_rule": "Dates refer to the day of final awakening: a record belongs to the date you woke up. Only waking dates before today are supported.",
        "data_rule": "A date range does not mean every day has complete data. Absent rows, unavailable records and missing fields are counted separately; missing values are never replaced with zero. Times use Europe/Berlin with the actual UTC offset.",
        "not_recorded": "Bedtime, sleep latency, stage timelines and diagnostic scores are not recorded and cannot be inferred from these fields.",
        "raw": "Recorded fields", "computed": "Calculated metrics", "metric": "Name", "meaning": "Meaning", "unit": "Unit",
        "profile": "Current profile", "dates": "Queryable record dates", "empty_dates": "No record dates can currently be queried",
        "counts": "{unique} unique record dates · {valid} valid nights · {missing} absent days · {unavailable} unavailable nights",
        "date_lists": "Missing dates and record completeness", "missing": "Dates with no record", "unavailable": "Existing records marked unavailable",
        "incomplete": "Valid records with incomplete detailed fields", "duplicates": "Duplicate dates", "none": "None",
        "source_counts": "The file has {rows} rows on {unique} unique dates across {calendar} calendar days; {complete} nights have complete detailed fields.",
        "read_error": "Sleep data is temporarily unavailable, so the overview and record examples cannot be prepared. You can still read the guide or ask about metric meanings.",
        "duplicate_record": "Duplicate dates were found in the sleep data, so a reliable overview is unavailable. Please correct the data and retry.",
        "incomplete_data": "Some sleep-data fields are incomplete, so a reliable overview is unavailable. Please correct the data and retry.",
        "invalid_data": "Some sleep records are invalid or inconsistent, so a reliable overview is unavailable. Please correct the data and retry.",
        "labels": {"duration": "Look up one night", "deep": "Calculate deep sleep %", "stages": "View all sleep stages", "period": "Explore a seven-day period", "knowledge": "What is deep sleep?", "normality": "Check a judgment boundary", "no_records": "A date with no record", "medical": "Diagnosis boundary", "outside": "An unrelated request"},
    },
}

SCENARIOS_ZH = {
    "Variable timing with occasional shorter nights.": "示例作息时间有波动，个别夜晚睡眠较短。",
    "Later, more variable timing with three scattered record gaps.": "示例作息较晚、波动较大，有三处分散的记录缺口。",
    "Relatively steady timing with ordinary variation and an occasional shorter night.": "示例作息相对稳定，保留日常波动与个别较短夜晚。",
}

FIELDS = {
    "sleep_min": ("总睡眠时长", "Total sleep", "记录的睡着总时长，不含中途清醒", "Recorded sleeping time, excluding intermediate awake time", "分钟", "min"),
    "sleep_onset": ("入睡时刻", "Sleep onset", "开始睡着的时刻，不是上床时间", "When sleep began, not bedtime", "当地时刻（Europe/Berlin）", "Local time (Europe/Berlin)"),
    "wake_time": ("最终醒来时刻", "Final awakening", "这次睡眠最后醒来的时刻，不是离床时间", "Final awakening, not getting out of bed", "当地时刻（Europe/Berlin）", "Local time (Europe/Berlin)"),
    "night_awakenings": ("夜醒次数", "Night awakenings", "入睡后、最终醒来前的中途醒来次数", "Intermediate awakenings; excludes final awakening", "次", "count"),
    "awake_min": ("夜间清醒时长", "Awake time", "中途醒来期间的累计时长", "Total time awake during intermediate awakenings", "分钟", "min"),
    "deep_sleep_min": ("深睡时长", "Deep sleep", "深睡阶段的总时长（N3）", "Total deep-sleep duration (N3)", "分钟", "min"),
    "light_sleep_min": ("浅睡时长", "Light sleep", "浅睡阶段的总时长（N1 + N2）", "Combined light-sleep duration (N1 + N2)", "分钟", "min"),
    "rem_sleep_min": ("REM时长", "REM sleep", "快速眼动睡眠阶段的总时长", "Total REM sleep duration", "分钟", "min"),
}


def data_catalogue(profile_id, *, today=None, dataset=None):
    today = today or analysis.berlin_today()
    base = {"status": "unavailable", "profile_id": profile_id, "issue": "read_error", "as_of_date": today.isoformat()}
    try:
        dataset = dataset if dataset is not None else analysis.load_dataset()
        profile = next(p for p in dataset.profiles if p.profile_id == profile_id)
        source = sorted((r for r in dataset.records if r.profile_id == profile_id), key=lambda r: r.record_date)
        counts = Counter(r.record_date for r in source)
        if any(count > 1 for count in counts.values()):
            return {**base, "issue": "duplicate_record"}
        days = sorted(counts)
        eligible = [r for r in source if r.record_date < today]
        valid = [r for r in eligible if r.sleep_valid]
        source_valid = [r for r in source if r.sleep_valid]
        calendar = [days[0] + timedelta(days=i) for i in range((days[-1] - days[0]).days + 1)] if days else []
        return {"status": "ok", "profile_id": profile_id, "name": profile.name, "scenario": profile.scenario,
            "as_of_date": today.isoformat(), "dataset_version": dataset.version, "generation": dataset.generation,
            "record_rows": len(source), "unique_dates": len(days), "calendar_days": len(calendar),
            "source_start": days[0].isoformat() if days else None, "source_end": days[-1].isoformat() if days else None,
            "queryable_start": eligible[0].record_date.isoformat() if eligible else None,
            "queryable_end": eligible[-1].record_date.isoformat() if eligible else None,
            "queryable_unique_dates": len(eligible), "valid_nights": len(source_valid), "queryable_valid_nights": len(valid),
            "missing_dates": [d.isoformat() for d in calendar if d not in counts],
            "unavailable_dates": [r.record_date.isoformat() for r in source if not r.sleep_valid],
            "incomplete_dates": [r.record_date.isoformat() for r in source if r.sleep_valid and any(getattr(r, f) is None for f in DETAIL_FIELDS)],
            "complete_detail_nights": sum(all(getattr(r, f) is not None for f in DETAIL_FIELDS) for r in source_valid),
            "duplicate_dates": [], "fields": {field: sum(getattr(r, field) is not None for r in valid) for field in FIELDS},
            "rows": [{"date": r.record_date.isoformat(), "sleep_valid": r.sleep_valid, "sleep_min": r.sleep_min,
                      **{field: getattr(r, field) for field in DETAIL_FIELDS}} for r in eligible]}
    except DataQualityError as exc:
        issue = "duplicate_record" if exc.code == "duplicate_record" else "incomplete_data" if exc.missing else "invalid_data"
        return {**base, "issue": issue}
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return base


def metric_rows(info, language):
    index = 0 if language == "中文" else 1
    return [{"field": field, "name": labels[index], "meaning": labels[2 + index], "unit": labels[4 + index]}
            for field, labels in FIELDS.items() if info.get("fields", {}).get(field, 0)]


def computed_rows(info, language):
    zh = language == "中文"
    rows = []
    if info.get("fields", {}).get("sleep_min"):
        rows += [("七天平均睡眠时长", "有效时长之和 ÷ 有效夜数；缺失不参与", "分钟") if zh else
                 ("Seven-day mean sleep", "Valid sleep minutes divided by valid nights; missing nights excluded", "min"),
                 ("覆盖率", "有效夜数 ÷ 所请求夜数", "%") if zh else ("Coverage", "Valid nights divided by requested nights", "%")]
        rows += [("相邻两周时长变化", "两周各至少四晚有效时，比较平均睡眠时长", "分钟") if zh else
                 ("Adjacent-week duration change", "Difference of means, only with at least four valid nights in each week", "min")]
    stages = [FIELDS[f][0 if zh else 1] for f in ("deep_sleep_min", "light_sleep_min", "rem_sleep_min") if info.get("fields", {}).get(f)]
    if stages:
        rows.append(("阶段占比", "阶段时长 ÷ 同一组记录的睡眠总时长，保留一位小数", "%") if zh else
                    ("Stage percentages", "Stage minutes divided by total sleep minutes from the same records; one decimal", "%"))
    return rows


def _query(info, start, end=None, compare=False):
    return dict(profile_id=info["profile_id"], start_date=start, end_date=end or start, compare_previous=compare)


def _week(info, selection=None):
    rows = {r["date"]: r for r in info.get("rows", [])}
    if not rows:
        return None
    starts = [date.fromisoformat(info["queryable_end"]) - timedelta(days=6+i) for i in range(max(0, info["calendar_days"]-6))]
    if selection and selection.get("end_date") and selection.get("start_date"):
        chosen = date.fromisoformat(selection["start_date"])
        if (date.fromisoformat(selection["end_date"]) - chosen).days == 6:
            starts = [chosen] + starts
    count = lambda start: sum(rows.get((start+timedelta(days=i)).isoformat(), {}).get("sleep_valid", False) for i in range(7))
    for start in starts:
        end = start + timedelta(days=6)
        if start.isoformat() < info["queryable_start"] or end.isoformat() > info["queryable_end"] or count(start) < 4:
            continue
        return _query(info, start.isoformat(), end.isoformat(), count(start-timedelta(days=7)) >= 4)
    return None


def question_examples(info, language, selection=None):
    zh = language == "中文"
    examples = []
    label = COPY[language]["labels"]
    profile = info["profile_id"]
    rows = [r for r in info.get("rows", []) if r["sleep_valid"] and r["sleep_min"] and r["sleep_min"] > 0]
    if selection:
        rows.sort(key=lambda r: (selection["start_date"] <= r["date"] <= selection["end_date"], r["date"]))
    if rows:
        day = rows[-1]["date"]
        examples.append(dict(id="duration", label=label["duration"], question=(f"{profile}在{day}睡了多久？" if zh else f"How long did {profile} sleep on {day}?"), query=_query(info, day)))
    detailed = [r for r in rows if all(r.get(f) is not None for f in ("deep_sleep_min", "light_sleep_min", "rem_sleep_min"))]
    if detailed:
        day = detailed[-1]["date"]
        for key, cn, en in [("deep", f"{profile}在{day}的深睡占比是多少？", f"What was {profile}'s deep sleep percentage on {day}?"),
                            ("stages", f"列出{profile}在{day}完整的睡眠阶段分布和占比。", f"Show the full sleep stage distribution and percentages for {profile} on {day}.")]:
            examples.append(dict(id=key, label=label[key], question=cn if zh else en, query=_query(info, day)))
    period = _week(info, selection)
    if period:
        start, end = period["start_date"], period["end_date"]
        question = (f"比较{profile}在{start}至{end}的平均睡眠时长与前一周的变化。" if period["compare_previous"] else
                    f"{profile}在{start}至{end}的平均睡眠时长是多少？") if zh else (
                    f"Compare {profile}'s mean sleep duration for {start} to {end} with the previous week." if period["compare_previous"] else
                    f"What was {profile}'s mean sleep duration from {start} to {end}?")
        examples.append(dict(id="period", label=label["period"], question=question, query=period))
    try:
        if any(r["citation_id"] == "H6:NREM" for r in load_knowledge().references):
            examples.append(dict(id="knowledge", label=label["knowledge"], question="深睡是什么？" if zh else "What is deep sleep?", query=None))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    if detailed:
        day = detailed[-1]["date"]
        examples.append(dict(id="normality", label=label["normality"], question=(f"{profile}在{day}的深睡占比正常吗？" if zh else
                             f"Was {profile}'s deep sleep percentage normal on {day}?"), query=_query(info, day)))
    return examples


def classroom_examples(info, language):
    zh = language == "中文"
    profile = info["profile_id"]
    result = []
    if info.get("status") == "ok" and info.get("source_start"):
        missing = info["missing_dates"] or [(date.fromisoformat(info["source_start"])-timedelta(days=1)).isoformat()]
        day = next((d for d in missing if d < info["as_of_date"]), None)
        if day:
            result.append(dict(id="no_records", question=(f"查询{profile}在{day}的睡眠时长。" if zh else
                               f"Look up {profile}'s sleep duration on {day}."), query=_query(info, day)))
    result += [dict(id="medical", question="请根据我的睡眠记录给我确诊失眠。" if zh else "Diagnose me with insomnia from my sleep records.", query=None),
               dict(id="outside", question="帮我写一首关于春天的诗。" if zh else "Write a poem about spring.", query=None)]
    return result


def default_query():
    info = data_catalogue(PROFILE_IDS[0])
    week = _week(info)
    if week:
        return week
    day = info.get("queryable_end") or (analysis.berlin_today()-timedelta(days=1)).isoformat()
    return _query(info, day)


def render_data_guide(language="中文"):
    """Used by documentation and the CLI; no separate coverage constants."""
    text = COPY[language]
    lines = ["# SleepLens", "", text["intro"], "", text["demo"], "", text["date_rule"], "", text["data_rule"]]
    for profile in PROFILE_IDS:
        info = data_catalogue(profile)
        lines += ["", "## " + profile]
        if info["status"] != "ok":
            lines.append(text[info["issue"]]); continue
        scenario = SCENARIOS_ZH.get(info["scenario"], info["scenario"]) if language == "中文" else info["scenario"]
        if scenario:
            lines.append(scenario)
        dates = f"{text['dates']}: {info['queryable_start']} – {info['queryable_end']}" if info["queryable_start"] else text["empty_dates"]
        lines += [dates,
                  text["source_counts"].format(rows=info["record_rows"], unique=info["unique_dates"], calendar=info["calendar_days"], complete=info["complete_detail_nights"])]
        for key, field in [("missing", "missing_dates"), ("unavailable", "unavailable_dates"), ("incomplete", "incomplete_dates"), ("duplicates", "duplicate_dates")]:
            lines.append(text[key] + ": " + (", ".join(info[field]) or text["none"]))
        lines += ["", f"| {text['metric']} | {text['meaning']} | {text['unit']} |", "| --- | --- | --- |"]
        lines += [f"| {r['name']} | {r['meaning']} | {r['unit']} |" for r in metric_rows(info, language)]
        lines += ["", text["computed"] + ":"] + [f"- {name}: {meaning} ({unit})" for name, meaning, unit in computed_rows(info, language)]
        lines += ["", text["examples"] + ":"] + ["- " + e["question"] for e in question_examples(info, language)]
        if info["generation"]:
            lines += ["", ("生成参数" if language == "中文" else "Generation metadata") + ": " + str(info["generation"])]
    return "\n".join(lines) + "\n"


def main():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Print current SleepLens data and examples without a model.")
    parser.add_argument("--language", choices=["zh", "en"], default="zh")
    args = parser.parse_args()
    print(render_data_guide("中文" if args.language == "zh" else "English"))


if __name__ == "__main__":
    main()
