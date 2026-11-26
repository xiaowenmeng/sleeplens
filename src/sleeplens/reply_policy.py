"""Application-owned public limits; diagnostics and rejected drafts stay separate."""

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date


POLICY_VERSION = "classified-replies-v2"

# No location or verified hotline lookup is available in this application.
# These safety messages deliberately contain no emergency or crisis numbers.
TEXT = {
    "emergency": (
        "听到你正面临这样的危险，我很担心你的安全。请立即联系当地紧急救援或前往急诊，并请身边可信任的人陪着你；如果安全可行，先远离可能伤害你的物品或地点。",
        "I'm concerned about your immediate safety. Please contact local emergency services or go to an emergency department now, and ask someone you trust to stay with you; if safe, move away from anything or anywhere that could cause harm.",
    ),
    "medical_emergency": (
        "你描述的情况可能需要立即处理，请现在联系当地紧急救援或前往急诊。请身边的人陪同，并把发生的情况告诉急救人员。",
        "What you describe may need immediate medical attention: contact local emergency services or go to an emergency department now. Ask someone nearby to stay with you and tell the emergency team what happened.",
    ),
    "medical_boundary": (
        "我无法提供诊断或个人用药方案，建议向医生或药师确认。我可以帮你整理近期睡眠记录，方便咨询。",
        "I cannot diagnose you or choose or adjust medication for you; please check with a doctor or pharmacist. I can help organize your recent sleep records for that conversation.",
    ),
    "out_of_scope": (
        "这个问题超出了我的睡眠分析范围。你可以让我解读睡眠记录、比较近期时长变化，或解释记录里的指标。",
        "This request is outside my sleep-analysis scope. I can interpret sleep records, compare recent sleep duration, or explain the recorded metrics.",
    ),
    "knowledge_insufficient": (
        "目前我还不能可靠判断这个问题。你可以让我查看已有的睡眠记录，或总结一个已结束的七天周期内的变化。",
        "I cannot reliably judge this from the available information. I can look at existing sleep records or summarize changes within a completed seven-day period.",
    ),
    "record_read_failure": (
        "这次睡眠记录读取失败，请稍后再试。你也可以先了解记录中各项指标的含义。",
        "I could not read the sleep records this time; please retry later. You can also ask what the recorded metrics mean.",
    ),
    "service_failure": (
        "这次没能完成睡眠问答，请稍后重试。你仍可以查看页面已有的睡眠记录。",
        "I could not finish this sleep question; please retry later. You can still view the sleep records already shown on the page.",
    ),
    "knowledge_read_failure": (
        "这次没能读取睡眠资料，暂时无法完成相关解释。你仍可以查看已有睡眠记录，或稍后重试。",
        "I could not read the sleep information, so I cannot finish that explanation. You can still view existing sleep records or retry later.",
    ),
    "unqueried": (
        "本次尚未取得所请求的睡眠记录，暂时无法确认数值。你可以指定档案和已结束的醒来日期后重试。",
        "I have not obtained the requested sleep records, so I cannot confirm their values. Select a profile and a completed waking date, then retry.",
    ),
    "stage_limit": (
        "目前我没有足够依据判断这个比例是否正常。",
        "I don't have enough evidence to judge whether that percentage is normal.",
    ),
    "advice_limit": (
        "这次还无法可靠提供针对这些记录的改善建议。你可以先查看已核实的记录，或比较另一个已结束的七天周期。",
        "I cannot reliably offer improvement advice for these records this time. You can view the verified records or compare another completed seven-day period.",
    ),
    "interpretation_limit": (
        "这次还无法可靠解释这些记录反映的情况。你可以先查看已核实的记录，或比较另一个已结束的七天周期。",
        "I cannot reliably interpret what these records mean this time. You can view the verified records or compare another completed seven-day period.",
    ),
    "answer_unavailable": (
        "这次未能完成文字说明，先展示已核实的记录。你也可以继续查看其他日期的记录。",
        "I could not finish the written explanation; the verified records are shown below. You can also explore records for other dates.",
    ),
    "cause_limit": (
        "目前还不能根据这些记录确定睡不好的原因。你可以查看其他日期的记录，或比较一个已结束的七天周期。",
        "These records do not let me determine the cause of the sleep difficulty. You can explore other dates or compare a completed seven-day period.",
    ),
}


def message(key, language):
    return TEXT[key][0 if language == "Chinese" else 1]


@dataclass(frozen=True)
class RequestPolicy:
    categories: tuple[str, ...] = ()
    remaining: str = ""
    reason: str | None = None


def _clauses(text):
    # Keep comma-linked subjects and symptoms together. Split independent
    # requests, not the words inside metrics or decimal quantities.
    return [part.strip(" ，,。；;!?！？") for part in re.split(
        r"[。；;!?！？\n]+|\.(?=\s+[A-Za-z])|(?<!\d)\.(?!\d)|(?:顺便|另外|同时|以及|并且|而且|但是|但(?=现在)|\band also\b)|"
        r"[，,]\s*(?=(?:再|也|还)?(?:帮我|给我|请|查|解释|分析|比较|我(?:应该|该|能不能|是不是)|diagnose|please|show|write))|"
        r"并(?=写|查|解释|分析|告诉|帮我|给我|判断|诊断|确诊)|"
        r"\band\s+(?=(?:please |can you |could you )?(?:write|diagnose|tell|show|look|explain|what|why|how)\b)", text, flags=re.I)
        if part.strip(" ，,。；;!?！？")]


def _urgent_reason(text):
    # Contextual frames require a person, present intent/action or an acute
    # symptom combination. A mention of a diagnosis or risk term is insufficient.
    # Quoted educational/historical material is not a current personal report.
    subject_seen = False
    for clause in re.split(r"[。；;!?！？\n]+|但是|但(?=现在)|(?<=[，,])(?=我现在|现在我)|\bbut\b", text, flags=re.I):
        if re.search(r"小说|台词|翻译|举例|假如|假设|如果有人|\b(?:novel|quote|translate|hypothetical)\b", clause, re.I):
            continue
        person = re.search(r"我|朋友|家人|他|她|有人|\b(?:i|my friend|he|she|someone)\b", clause, re.I)
        subject_seen = subject_seen or bool(person)
        if re.search(r"去年|以前|曾经|昨晚|昨天|\b(?:last year|used to|last night|yesterday)\b", clause, re.I):
            continue
        person = person or (subject_seen and re.match(r"\s*(?:现在|马上|准备|打算|正在|now|about to)", clause, re.I))
        if not person:
            continue
        current = re.search(r"现在|马上|立刻|今晚|准备|打算|正在|已经|刚刚|刚才|\b(?:now|tonight|about to|going to|just|already)\b", clause, re.I)
        harm_pattern = r"自杀(?!式)|自伤|轻生|伤害自己|结束(?:自己|我的)?(?:的)?生命|不想活|kill (?:myself|himself|herself)|end my life|hurt myself|suicide"
        harm = re.search(harm_pattern, clause, re.I)
        intent = re.search(r"(?:现在|马上|今晚|准备|打算|想|要|正在|right now|about to|going to|want to|intend to).{0,8}(?:" + harm_pattern + ")", clause, re.I)
        denied = re.search(r"(?:没有|没|不想|不打算|不会|不会去|不准备).{0,6}(?:自杀|自伤|轻生|伤害自己)|"
                           r"\b(?:not|never|no longer)\b.{0,20}(?:suicid|kill|hurt|end my life)", clause, re.I)
        if current and harm and intent and not denied:
            return "immediate_self_harm"
        overdose = re.search(r"(?:已经|刚刚|刚才|正在).{0,8}(?:吞|吃|服).{0,8}(?:很多|大量|一把|整瓶|过量).{0,8}(?:药|安眠|褪黑素)|"
                             r"(?:已经|刚刚|刚才).{0,4}过量服.{0,12}(?:药|安眠|褪黑素)|"
                             r"\b(?:just|already)\b.{0,20}(?:overdos|(?:swallowed|took).{0,12}(?:many|bottle|too many).{0,12}(?:pills|medicine))", clause, re.I)
        negated_event = re.search(r"没有(?:吞|吃|服)|并未|没(?:有)?过量|did not|didn't", clause, re.I)
        acute = re.search(r"喘不过气|无法呼吸|不能呼吸|呼吸不了|失去意识|昏迷|can't breathe|cannot breathe|unconscious", clause, re.I)
        present_acute = re.search(r"我(?:现在|正|突然)?(?:真的)?(?:喘不过气|无法呼吸|不能呼吸|呼吸不了)|\bi (?:can't|cannot) breathe\b", clause, re.I)
        resolved = re.search(r"现在(?:已经)?(?:好了|没事|恢复了|安全了|能正常呼吸)|now.{0,10}(?:fine|safe|recovered)", clause, re.I)
        if not negated_event and not resolved and (overdose or (acute and (current or present_acute))):
            return "medical_emergency"
        height_intent = re.search(r"(?:楼顶|阳台|桥边|桥上|楼上).{0,20}(?:准备|打算|要).{0,6}跳(?:下去|楼|桥)", clause)
        violence = re.search(r"(?:正在|现在).{0,8}(?:被|遭).{0,12}(?:持刀威胁|袭击|勒住)", clause)
        if height_intent or violence:
            return "immediate_danger"
        if current and re.search(r"胸痛|胸口.{0,4}痛|chest pain", clause, re.I) and re.search(r"呼吸困难|shortness of breath", clause, re.I):
            return "medical_emergency"
    return None


def _medical_request(clause):
    clause = re.sub(r"(?:不用|不要|不需要)诊断(?:我)?|不问用药|不需要用药|do not diagnose(?: me)?|don't diagnose(?: me)?", "", clause, flags=re.I)
    diagnosis = re.search(r"(?:帮我|给我|替我|为我).{0,12}(?:诊断|确诊)|(?:诊断|确诊)我|我.{0,6}(?:是不是|是否)(?:患有|得了)|"
                          r"我.{0,4}(?:是不是|是否)(?:有|得了|患有)?(?:失眠|抑郁症|睡眠呼吸暂停)|"
                          r"我(?:这|这样|这晚|现在)?.{0,3}算(?:不算)?失眠|"
                          r"\b(?:can|could|would) you (?:please )?diagnos\w*|\bdiagnos\w*.{0,25}(?:from|using|based on) my (?:records|sleep)|"
                          r"\b(?:does|would|could).{0,20}mean i have\b|"
                          r"\bdiagnose me\b|tell me (?:if|whether) i have", clause, re.I)
    medication = re.search(r"药|褪黑素|melatonin|medication|medicine|sleeping pills?|dose", clause, re.I)
    personal_action = re.search(r"(?:我|给我).{0,14}(?:该|应该|能不能|可以|需要|推荐|选择|加到|减到|加量|减量)|"
                                r"(?:该|应该|推荐|选).{0,8}(?:吃什么|哪种|什么).{0,5}(?:药|褪黑素)|"
                                r"(?:增加|减少|调整|加到|减到|停用).{0,10}(?:剂量|片|药)|"
                                r"(?:剂量|药量).{0,8}(?:增加|减少|调整)|"
                                r"(?:推荐|选择|挑选).{0,10}(?:安眠药|助眠药|睡眠药|褪黑素)|"
                                r"\b(?:should i|can i|which.{0,20}should i|how much.{0,20}should i|recommend.{0,15}(?:me|pill|medication))\b", clause, re.I)
    return bool(diagnosis or (medication and personal_action))


def _outside_request(clause):
    # A task in a clearly unrelated domain is required. Sleep-related
    # explanations about weather, games, shift work, drugs, etc. remain in scope.
    sleep = re.search(r"睡|入眠|夜醒|作息|褪黑素|咖啡|困倦|疲惫|\bsleep|\brem\b|bedtime|insomnia|caffeine|fatigue|tired", clause, re.I)
    outside = re.search(r"天气(?:怎么样|如何|预报)|(?:北京|上海|明天|后天).{0,6}天气|股票|自动交易|股价|炒股|旅游攻略|"
                        r"法国首都|写.{0,8}(?:程序|代码|诗|论文)|\b(?:stock|trading|weather forecast|write.{0,15}(?:code|poem|essay)|capital of)\b", clause, re.I)
    return bool(outside and not sleep)


def classify_request(question, *, urgent_context=False):
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        return RequestPolicy(remaining=question)
    text = unicodedata.normalize("NFKC", question).lower()
    urgent = _urgent_reason(text)
    if (not urgent and urgent_context and re.search(r"(?:我|i).{0,12}(?:现在|马上|right now|about to).{0,12}(?:动手|这么做|行动|do it|act)", text, re.I)
            and not re.search(r"不会|不想|没有|不再|will not|won't|not going", text, re.I)):
        urgent = "immediate_self_harm"
    if urgent:
        return RequestPolicy(("emergency",), reason=urgent)
    categories, remaining = [], []
    for clause in _clauses(question):
        if _medical_request(clause.lower()):
            categories.append("medical_boundary")
        elif _outside_request(clause.lower()):
            categories.append("out_of_scope")
        else:
            remaining.append(clause)
    # An incidental symptom preface isn't a second, answerable request.
    if categories and remaining and not any(re.search(
            r"查|解释|解读|分析|比较|总结|是什么|什么意思|多少|多久|几点|几次|怎么样|\b(?:show|look|explain|compare|summari[sz]e|what|how)\b", c, re.I) for c in remaining):
        remaining = []
    return RequestPolicy(tuple(dict.fromkeys(categories)), "；".join(remaining) if categories else question)


def boundary_reply(policy, language):
    if policy.categories == ("emergency",):
        return message("medical_emergency" if policy.reason == "medical_emergency" else "emergency", language)
    return "\n\n".join(message(category, language) for category in policy.categories)


def policy_trace(category, reason=None, *, partial=False):
    return {"version": POLICY_VERSION, "category": category, "reason": reason or category, "partial": partial}


def unavailable_period_reply(period, today, language):
    last = today.isoformat()
    if language == "Chinese":
        return f"所问睡眠归入醒来日期{period[1]}，这晚的睡眠还没有结束；目前最多可以查到{last}醒来的那次睡眠（昨晚）。你可以选择一个已有记录的醒来日期。"
    return (f"The requested sleep belongs to waking date {period[1]} and hasn't happened yet; the latest night available "
            f"is the one you woke from on {last} (last night). Please choose a waking date with a record.")


STAGES = (("deep", "deep_sleep_min", "深睡", "Deep sleep"),
          ("light", "light_sleep_min", "浅睡", "Light sleep"), ("rem", "rem_sleep_min", "REM", "REM"))
FIELD_LABELS = {
    "sleep_min": ("总睡眠时长", "total sleep duration"), "deep_sleep_min": ("深睡时长", "deep sleep minutes"),
    "light_sleep_min": ("浅睡时长", "light sleep minutes"), "rem_sleep_min": ("REM时长", "REM minutes"),
    "sleep_onset": ("入睡时刻", "sleep-onset time"), "wake_time": ("最终醒来时刻", "final wake time"),
    "night_awakenings": ("夜醒次数", "awakening count"), "awake_min": ("清醒时长", "awake minutes"),
}


def field_labels(fields, language):
    return [FIELD_LABELS[f][0 if language == "Chinese" else 1] for f in fields if f in FIELD_LABELS]


def named_stage_metrics(text):
    """User-named stages, including hyphenated English; never model defaults."""
    all_stages = re.search(r"(?:完整|全部|所有).{0,10}(?:阶段|分期)|(?:full|complete|all).{0,20}(?:stage|distribution|breakdown)", text, re.I)
    generic_stages = re.search(r"睡眠阶段|睡眠分期|阶段分布|sleep[- ]stages?\b", text, re.I)
    specific = re.search(r"深睡|浅睡|\b(?:deep|light)[- ]sleep\b|\brem\b|快速眼动", text, re.I)
    if all_stages or (generic_stages and not specific):
        return ("stages",)
    result = []
    ratio = re.search(r"占比|比例|百分比|percentage|percent|proportion|fraction|share", text, re.I)
    for metric, pattern in (("deep", r"深睡|\bdeep[- ]sleep\b"), ("light", r"浅睡|\blight[- ]sleep\b"),
                            ("rem", r"\brem\b|快速眼动")):
        if re.search(pattern, text, re.I) or (ratio and re.search(r"\b" + metric + r"\b", text, re.I)):
            result.append(metric)
    return tuple(result)


@dataclass(frozen=True)
class StageResponseScope:
    intent: str
    metrics: tuple[str, ...]
    independent_question: str = ""


def stage_response_scope(question, plan):
    """Bind composition to the actual requested calculation/judgment."""
    if plan.task not in {"records", "combined"} or plan.knowledge_only or plan.wants_improvement:
        return None
    metrics = named_stage_metrics(question)
    ratio = re.search(r"占比|比例|百分比|分布|percentage|percent|proportion|fraction|share|distribution|breakdown", question, re.I)
    assessment = re.search(r"正常|异常|达标|够不够|太少|偏少|健康|\bnormal\b|\babnormal\b|\benough\b|too (?:little|much)|healthy", question, re.I)
    if not metrics or not (ratio or assessment):
        return None
    independent, requested = [], []
    judgment_requested = False
    for clause in _clauses(question):
        named = named_stage_metrics(clause)
        is_stage_part = named and re.search(
            r"占比|比例|百分比|分布|正常|异常|达标|够不够|太少|健康|percentage|percent|proportion|distribution|breakdown|normal|enough|healthy", clause, re.I)
        if not is_stage_part:
            independent.append(clause)
        else:
            requested.extend(named)
            judgment_requested |= bool(re.search(r"正常|异常|达标|够不够|太少|偏少|健康|normal|enough|healthy", clause, re.I))
    if not requested:
        return None
    return StageResponseScope("assessment" if judgment_requested else "lookup", tuple(dict.fromkeys(requested)), "；".join(independent))


def comparison_available(record):
    """An available completed data window, not a promise of a completed comparison."""
    available = record.get("available_period") or {}
    try:
        known_details = sum((record.get(scope) or {}).get("detail_nights", 0) for scope in ("current", "previous"))
        return known_details >= 2 and (date.fromisoformat(available["end_date"]) - date.fromisoformat(available["start_date"])).days >= 6
    except (KeyError, TypeError, ValueError):
        return False


def stage_limitation(language, *, can_compare=False):
    text = message("stage_limit", language)
    if can_compare:
        if language == "Chinese":
            return text[:-1] + "，可以帮你与附近七天的已有记录作比较。"
        return text + " I can compare it with available records from the surrounding week."
    return text


def stage_record_gap(record, metrics, language, reason):
    labels = [cn if language == "Chinese" else en.lower() for metric, _, cn, en in STAGES if metric in metrics]
    metric = ((labels[0] + ("占比" if language == "Chinese" else " percentage")) if len(labels) == 1 else
              ("睡眠阶段占比" if language == "Chinese" else "sleep stage percentages"))
    period = record["period"]
    days = period["start_date"] if period["start_date"] == period["end_date"] else f"{period['start_date']}–{period['end_date']}"
    if language == "Chinese":
        state = "没有可用的睡眠记录" if reason == "no_records" else "的睡眠记录被标记为不可用"
        return f"{days}{state}，暂时无法计算{metric}。你可以选择已有记录的日期查看。"
    state = f"No usable sleep record is available for {days}" if reason == "no_records" else f"The sleep record for {days} is marked unavailable"
    return f"{state}, so I cannot calculate the {metric}. You can choose a date with an existing record."


def medical_boundary_reply(language, *, record=None):
    if not record:
        return message("medical_boundary", language)
    rows = (record.get("daily_records") or {}).get("current") or []
    if len(rows) != 1 or not rows[0].get("sleep_valid") or type(rows[0].get("sleep_min")) is not int:
        return message("medical_boundary", language)
    row = rows[0]
    hours, minutes = divmod(row["sleep_min"], 60)
    if language == "Chinese":
        return ("仅凭这晚的记录，我无法作出诊断或提供个人用药方案。"
                f"{row['record_date']}记录的睡眠时长为{hours}小时{minutes}分钟；建议向医生或药师确认。"
                "我可以帮你整理近期记录，方便沟通。")
    return ("I cannot diagnose you or provide a personal medication plan from this night's record. "
            f"Your recorded sleep on {row['record_date']} was {hours} hours {minutes} minutes; please consult a doctor or pharmacist. "
            "I can help organize recent records for that conversation.")


def stage_question(plan):
    return (plan.task in {"health", "combined"} and "stage_distribution" in plan.topics and not plan.wants_improvement)


def stage_values(plan, record, language):
    """Calculate only from a valid numerator and denominator on the same row."""
    zh = language == "Chinese"
    wanted = set(plan.metrics)
    if not wanted.intersection({"deep", "light", "rem", "stages"}):
        wanted.update(m for m, _, _, _ in STAGES if m + "_sleep" in plan.topics)
    if "stages" in wanted or not wanted.intersection({"deep", "light", "rem"}):
        wanted.update({"deep", "light", "rem"})
    values, missing, invalid = [], set(), set()
    rows = (record.get("daily_records") or {}).get("current") or []
    for row in rows:
        if not row.get("sleep_valid"):
            continue
        for metric, field, cn, en in STAGES:
            if metric not in wanted:
                continue
            label = cn if zh else en
            numerator, denominator = row.get(field), row.get("sleep_min")
            if numerator is None or denominator is None:
                if numerator is None:
                    missing.add(label + ("时长" if zh else " minutes"))
                if denominator is None:
                    missing.add("总睡眠时长" if zh else "total sleep duration")
                continue
            good = lambda v: type(v) in {int, float} and math.isfinite(v)
            if not good(denominator) or not 0 < denominator <= 1440:
                invalid.add("总睡眠时长" if zh else "total sleep duration")
                continue
            if not good(numerator) or not 0 <= numerator <= denominator:
                invalid.add(label + ("时长" if zh else " minutes"))
                continue
            percentage = numerator / denominator * 100
            values.append({"waking_date": row["record_date"], "stage": label,
                           "stage_minutes": numerator, "sleep_minutes": denominator, "percentage": round(percentage, 1)})
    return values, sorted(missing), sorted(invalid)


def stage_facts(values, language):
    if not values:
        return ""
    if len(values) == 1:
        v = values[0]
        return (f"{v['waking_date']}的记录中，{v['stage']}为{v['stage_minutes']:g}分钟，总睡眠时长为{v['sleep_minutes']:g}分钟，{v['stage']}占比约为{v['percentage']:.1f}%。" if language == "Chinese" else
                f"Your recorded {v['stage'].lower()} percentage on {v['waking_date']} was {v['percentage']:.1f}% — {v['stage_minutes']:g} minutes out of {v['sleep_minutes']:g} minutes of sleep.")
    lines = (["| 醒来日期 | 阶段 | 阶段时长 | 睡眠总时长 | 占比 |", "| --- | --- | --- | --- | --- |"] if language == "Chinese" else
             ["| Waking date | Stage | Stage minutes | Total sleep minutes | Percentage |", "| --- | --- | --- | --- | --- |"])
    lines.extend(f"| {v['waking_date']} | {v['stage']} | {v['stage_minutes']:g} | {v['sleep_minutes']:g} | {v['percentage']:.1f}% |" for v in values)
    return "\n".join(lines)


def stage_display_values(values, question):
    """A period share uses matching stage/total minutes, never a clinical target."""
    dates = sorted({v["waking_date"] for v in values})
    if len(dates) <= 1 or re.search(r"逐[夜晚天]|每[夜晚天]|各[夜晚天]|daily|night.by.night|each night", question, re.I):
        return values
    grouped = {}
    for value in values:
        item = grouped.setdefault(value["stage"], {"waking_date": f"{dates[0]}–{dates[-1]}", "stage": value["stage"],
            "stage_minutes": 0, "sleep_minutes": 0, "contributing_dates": []})
        item["stage_minutes"] += value["stage_minutes"]
        item["sleep_minutes"] += value["sleep_minutes"]
        item["contributing_dates"].append(value["waking_date"])
    for item in grouped.values():
        item["percentage"] = round(item["stage_minutes"] / item["sleep_minutes"] * 100, 1)
    return list(grouped.values())


def data_gap_reply(reason, language, *, label="", fields=()):
    zh = language == "Chinese"
    subject = (f"{label}的记录" if label else "这条记录") if zh else (f"The record for {label}" if label else "This record")
    if reason == "no_records":
        return (f"{label}没有可用的睡眠记录，暂时无法计算所问指标。你可以换一天查看，或先看看已有的睡眠数据。" if zh else
                f"No usable sleep records are available for {label}, so I cannot calculate the requested metric. Try another date or view the existing sleep data.")
    if reason == "unavailable_record":
        return (f"{label}的记录被标记为不可用，暂时无法计算所问指标。你可以换一天查看，或先看看已有的睡眠数据。" if zh else
                f"The record for {label} is marked unavailable. Try another date or view the existing sleep data.")
    names = ("、" if zh else ", ").join(fields) or ("所需字段" if zh else "required fields")
    if reason == "missing_fields":
        return (f"{subject}缺少{names}，暂时无法计算所问指标。你可以换一天查看，或先看看已有的睡眠数据。" if zh else
                f"{subject} is missing {names}, so I cannot calculate the requested metric. Try another date or view the available data.")
    return (f"这份记录的{names}无效，暂时无法计算所问指标；缺失或无效的数值没有当成零。你可以换一天查看已有的有效记录。" if zh else
            f"The {names} in this record cannot be used for that calculation; missing or invalid values were not treated as zero. Try another date with valid data.")


def record_issue(record, raw, plan, language):
    """Report a real result state, not an inference from rejected prose."""
    if raw and not record:
        status = raw.get("status")
        if status in {"ok", "partial_data", "no_data"}:
            return None  # A successful unsolicited lookup isn't an execution failure.
        error = raw.get("error") or {}
        code = error.get("code") if isinstance(error, dict) else None
        if status == "data_quality_error":
            if error.get("missing_fields"):
                text = data_gap_reply("missing_fields", language, fields=field_labels(error["missing_fields"], language))
                text = text.replace("这条记录", "这份数据中有记录").replace("This record is missing", "Some records in this dataset are missing")
                return "data_missing", "missing_fields", text
            fields = {"invalid_sleep_minutes": ("总睡眠时长", "total sleep duration"),
                      "invalid_sleep_stages": ("睡眠阶段时长与总时长的一致性", "consistency of stage and total sleep minutes")}
            label = fields.get(code, ("字段或数据一致性", "record fields or consistency"))[0 if language == "Chinese" else 1]
            names = field_labels(error.get("invalid_fields", ()), language) or [label]
            return "data_missing", "invalid_fields", data_gap_reply("invalid_fields", language, fields=names)
        if code == "period_not_finished" and raw.get("as_of_date") and raw.get("period"):
            period = raw["period"]
            return "data_missing", "date_unavailable", unavailable_period_reply((period["start_date"], period["end_date"]), date.fromisoformat(raw["as_of_date"]), language)
        if status in {"invalid_input", "unsupported_period"}:
            return "data_missing", "invalid_query", ("本次档案或日期范围不可用，尚未取得记录。请选择有效档案和已结束的单日或连续七天后重试。" if language == "Chinese" else
                                                       "The requested profile or dates cannot be used. Choose a valid profile and a completed day or seven-day period, then retry.")
        return "tool_failure", "record_read_failure", message("record_read_failure", language)
    if record:
        period = record["period"]
        label = period["start_date"] if period["start_date"] == period["end_date"] else f"{period['start_date']}–{period['end_date']}"
        if not record["current"]["valid_nights"]:
            rows = (record.get("daily_records") or {}).get("current") or []
            reason = "unavailable_record" if rows and all(r.get("record_state") == "unavailable_record" for r in rows) else "no_records"
            return "data_missing", reason, data_gap_reply(reason, language, label=label)
        if stage_question(plan):
            _, missing, invalid = stage_values(plan, record, language)
            if invalid or missing:
                reason = "invalid_fields" if invalid else "missing_fields"
                if invalid == ["总睡眠时长" if language == "Chinese" else "total sleep duration"] and any(
                        row.get("sleep_valid") and row.get("sleep_min") == 0 for row in (record.get("daily_records") or {}).get("current") or []):
                    notice = ("记录的总睡眠时长为零，暂时无法计算阶段占比，这个零值需要核实。你可以换一天查看，或先看看其他已有睡眠数据。" if language == "Chinese" else
                              "The recorded total sleep duration is zero, so it cannot be a stage-percentage denominator and needs checking. Try another date or view the other available sleep data.")
                    return "data_missing", reason, notice
                return "data_missing", reason, data_gap_reply(reason, language, label=label, fields=invalid or missing)
        required = {"sleep_onset": "sleep_onset", "wake_time": "wake_time", "awakenings": "night_awakenings",
                    "awake": "awake_min", "deep": "deep_sleep_min", "light": "light_sleep_min", "rem": "rem_sleep_min"}
        fields = {required[metric] for metric in plan.metrics if metric in required}
        if "stages" in plan.metrics:
            fields.update({"deep_sleep_min", "light_sleep_min", "rem_sleep_min"})
        missing = [field for field in FIELD_LABELS if field in fields and any(
            row.get("sleep_valid") and row.get(field) is None
            for row in (record.get("daily_records") or {}).get("current") or [])]
        if missing:
            return "data_missing", "missing_fields", data_gap_reply("missing_fields", language, label=label,
                                                                      fields=field_labels(missing, language))
    return None


def public_calculations(result):
    """Allowlist successful values; never expose exceptions, prompts or tool JSON."""
    details = []
    for event in result.get("tool_events", []):
        out = event.get("result") or {}
        usable = any((out.get(scope) or {}).get("valid_nights") for scope in ("current", "previous"))
        if event.get("tool") != "analyze_sleep" or out.get("status") not in {"ok", "partial_data"} or not usable:
            continue
        visible = {key: out[key] for key in ("profile_id", "period", "previous_period", "difference_min") if out.get(key) is not None}
        for key in ("current", "previous"):
            if out.get(key):
                allowed = {"expected_nights", "valid_nights", "unavailable_nights", "coverage", "mean_sleep_min", "detail_nights", "detail_coverage", "total_night_awakenings"}
                allowed.update("mean_" + field for field in FIELD_LABELS)
                scope = result.get("stage_response")
                if scope:
                    metrics = set(scope["metrics"])
                    if "stages" in metrics:
                        metrics.update({"deep", "light", "rem"})
                    allowed = {"expected_nights", "valid_nights", "coverage", "detail_nights", "mean_sleep_min"}
                    allowed.update("mean_" + field for metric, field, _, _ in STAGES if metric in metrics)
                visible[key] = {name: value for name, value in out[key].items() if name in allowed and (
                    value is None or type(value) in {int, float} or (name in {"mean_sleep_onset", "mean_wake_time"} and isinstance(value, str) and re.fullmatch(r"\d{2}:\d{2}", value)))}
        details.append(visible)
    if result.get("calculations"):
        details.append({"stage_percentages": result["calculations"]})
    if result.get("medical_record_fact"):
        details.append({"verified_sleep_duration": result["medical_record_fact"]})
    return details
