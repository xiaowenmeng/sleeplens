"""Small observable query hints, not an extra classification model."""

import re
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta

from sleeplens.knowledge import TOPIC_TERMS, term_matches
from sleeplens.application_dialogue import application_dialogue_kind, product_field_kind, split_introduction
from sleeplens.date_resolution import explicit_period
from sleeplens.experience_context import feedback_fields
from sleeplens.reply_policy import named_stage_metrics


def matches(term, text):
    return term_matches(term, text.lower())


@dataclass(frozen=True)
class QueryPlan:
    task: str = "conversation"
    metrics: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    no_caffeine: bool = False
    no_coffee: bool = False
    caffeine_question: bool = False
    profile_id: str | None = None
    period: tuple[str, str] | None = None
    brief: bool = False
    followup: bool = False
    unsupported_window: bool = False
    focus_citations: tuple[str, ...] = ()
    special_population: bool = False
    knowledge_only: bool = False
    compare_sources: bool = False
    brief_record_recap: bool = False
    lead_change: bool = False
    causality_question: bool = False
    personal_assessment: bool = False
    wants_improvement: bool = False
    wants_analysis: bool = False
    sleep_overview: bool = False
    unavailable_measurement: str | None = None
    application_dialogue: str | None = None
    date_error: str | None = None
    date_source: str | None = None
    product_field: str | None = None
    intro_requested: bool = False
    population_scope: str = "adult"
    compare_previous: bool | None = None
    include_rule_explanation: bool = False
    include_detail_means: bool = False
    experience_reply: bool = False
    experience_fields: tuple[str, ...] = ()

    @property
    def exclude_caffeine(self):
        return (self.no_coffee or self.no_caffeine) and not self.caffeine_question

    def as_dict(self):
        return asdict(self)


def plan_query(question, *, previous=None, today=None, selected_query=None):
    text = question.lower()
    dialogue = application_dialogue_kind(question)
    if dialogue:
        return QueryPlan(task="capability" if dialogue == "capabilities" else "conversation", application_dialogue=dialogue)
    introduction, remaining = split_introduction(question)
    if introduction:
        return replace(plan_query(remaining, previous=previous, today=today, selected_query=selected_query), intro_requested=True)
    field = product_field_kind(question, include_implicit=True)
    if field:
        return QueryPlan(task="definition", product_field=product_field_kind(question))
    previous = previous or {}
    prior_selection = previous.get("page_selection") or {}
    if selected_query and prior_selection:
        selected_scope = (selected_query.get("profile_id"), selected_query.get("start_date"), selected_query.get("end_date"))
        prior_scope = (prior_selection.get("profile_id"), prior_selection.get("start_date"), prior_selection.get("end_date"))
        resolved_scope = (previous.get("profile_id"), *(previous.get("resolved_period") or (None, None)))
        if selected_scope != prior_scope and selected_scope != resolved_scope:
            previous = {}
    profile = re.search(r"(?<![a-z0-9])p0[123](?![a-z0-9])", text)
    if profile and previous.get("profile_id") and profile.group().upper() != previous["profile_id"]:
        previous = {}
    from sleeplens.analysis import berlin_today
    explicit, date_source, date_error = explicit_period(question, today=today or berlin_today(), selection=selected_query, previous=previous)
    experience = previous.get("experience_context") or {}
    reply_fields = feedback_fields(question, experience.get("pending_questions", ()))
    # Recognize a substantive answer before falling through to generic chat or
    # health routing. No page default alone establishes which night it describes.
    experience_reply = bool(reply_fields) and not (
        previous.get("task") in {"health", "sources"} and not previous.get("resolved_period"))
    no_caffeine = previous.get("no_caffeine", False)
    no_coffee = previous.get("no_coffee", False)
    coffee_negative = r"不喝(?:含)?咖啡(?!因)|(?:戒了|戒掉|戒).*?咖啡(?!因)|咖啡(?!因).*?戒了|不碰咖啡(?!因)|(?:stopped|quit)(?: drinking)? coffee|(?:don't|do not|never) (?:drink|have) coffee"
    caffeine_negative = r"不(?:喝|摄入|碰)(?:含)?咖啡因|(?:don't|do not|never) (?:drink|use|have|consume) caffeine|no caffeine|caffeine.free"
    if re.search(coffee_negative, text):
        no_coffee = True
    elif re.search(r"(?:其实|现在|开始|仍然).*喝咖啡(?!因)|i (?:do drink|drink|have).*coffee", text):
        no_coffee = False
    if re.search(caffeine_negative, text):
        no_caffeine = True
    elif re.search(r"(?:现在|开始|其实).*摄入咖啡因|i (?:do consume|consume).*caffeine", text):
        no_caffeine = False
    current_topic_text = re.sub(caffeine_negative, "", re.sub(coffee_negative, "", text))
    caffeine_question = any(matches(term, current_topic_text) for term in TOPIC_TERMS["caffeine"])
    topics = {name for name, terms in TOPIC_TERMS.items() if any(matches(term, text) for term in terms)}
    if re.search(r"(?:凌晨|午夜|夜里).{0,8}(?:入睡|睡着|睡觉)|入睡.{0,6}(?:太晚|很晚)|(?:早睡|晚睡)(?:习惯|好吗|正常|影响|有什么)|(?:我|经常|总是)(?:早睡|晚睡)", text):
        topics.add("circadian")
    knowledge_only = not profile and bool(re.search(r"不查个人档案|不查.*个人记录|只问.*规则|一般.*成人|general adults?|without.*personal records", text))
    compare_sources = bool(re.search(r"一份.*另一份|适用情境|适用范围.*(?:不同|区别)|来源.*(?:不同|冲突)|sources.*(?:differ|disagree)|compare.*sources", text))
    if knowledge_only and re.search(r"小时|hours?|睡眠时长|sleep duration", text):
        topics.add("duration")
    if knowledge_only and re.search(r"质量|quality", text):
        topics.add("quality")
    if (no_coffee or no_caffeine) and not caffeine_question:
        topics.discard("caffeine")
    followup = bool(re.search(r"那怎么办|再解释|第二条|第[一二三]条|继续|那.*呢|我不喝|不摄入|don't drink|no caffeine|those|that advice|second (?:tip|point)|tell me more|what about|again", text))
    followup = followup or bool(re.search(r"刚才|按刚才|那天|那晚|那一晚|这么|这样|that night|that day|previous answer|as above|that many|is that normal", text))
    record_reference = bool(re.search(r"这(?:一)?(?:段|份|组|些|次|周|期)(?:的)?(?:睡眠)?(?:记录|数据)|上述(?:记录|数据)|刚才(?:的)?(?:记录|数据)|these records|those records|this (?:record|period)|selected records", text, re.I))
    followup = followup or (record_reference and not knowledge_only)
    followup = followup or (experience_reply and bool(previous.get("resolved_period")))
    if followup or ((no_coffee or no_caffeine) and topics <= {"general_advice"}):
        topics.update(previous.get("topics", ()))
        if (no_coffee or no_caffeine) and not caffeine_question:
            topics.discard("caffeine")
    ordinal = re.search(r"第([一二三123])条|\b(first|second|third) (?:tip|point)\b", text)
    focus = ()
    if ordinal:
        value = ordinal.group(1) or ordinal.group(2)
        number = {"一": 0, "二": 1, "三": 2, "1": 0, "2": 1, "3": 2, "first": 0, "second": 1, "third": 2}[value]
        sections = previous.get("answer_sections", [])
        if number < len(sections):
            section = sections[number]
            if not ((no_coffee or no_caffeine) and not caffeine_question and "caffeine" in section.get("topics", [])):
                focus = tuple(section["citation_ids"])
                topics = set(section.get("topics", []))
    record = bool(re.search(r"记录|平均|均值|覆盖|缺失|哪.*[天晚夜]|最[长短少多]|睡了多久|睡眠.*比较|比较.*睡眠|(?:这周|本周|上周).*睡|最近.*睡眠|\bp0[123]\b|\b(?:record|records|average|coverage|compare|shortest|longest)\b", text))
    record = record or bool(profile)
    # The week being compared against ("than last week", "vs the previous week",
    # "跟上周比"). Its spans also tell the period logic below that such a
    # "last week" is the baseline, not the week the user is asking about.
    baseline_spans = [match.span() for match in re.finditer(
        r"(?:跟|和|与|比).{0,4}(?:前一周|此前一周|上周)"
        r"|(?:\bthan\b|\bcompared?\b|\bcomparing\b|\bcomparison\b|\bvs\.?|\bversus\b|\bagainst\b)[^.?!。？！]{0,40}?"
        r"(?:(?:the\s+)?(?:previous|preceding|prior|last)\s+week|the\s+week\s+before)", text)]
    comparison_request = bool(baseline_spans or re.search(r"compare.*(?:preceding|previous)|compared with.*week", text))
    comparison_request = comparison_request or bool(re.search(r"比较(?:一下|下)?(?:前一周|上周)", text))
    if comparison_request and previous.get("resolved_period") and not knowledge_only:
        followup = True
    record = record or comparison_request
    if record and previous.get("resolved_period") and not explicit and not profile and not knowledge_only:
        followup = True
    if knowledge_only:
        record = False
    personal_assessment = not knowledge_only and bool(re.search(
        r"(?:我的|我现在的|我目前的|我这周的).{0,12}睡眠.{0,18}(?:正常|健康|够|达标|好不好)|"
        r"我.{0,6}睡.{0,12}(?:正常吗|够吗|够不够)|(?:is|does).{0,10}my sleep.{0,15}(?:normal|healthy|enough)|"
        r"(?:am i getting|do i get|do i sleep) enough", text))
    if not knowledge_only and re.search(r"(?:记录|数据|这一天|这晚|那晚|所选|my|this night)", text, re.I) and re.search(r"是否符合|是否正常|睡眠标准|成人.*标准|正常成人|adult.*(?:reference|normal|standard)", text, re.I):
        personal_assessment = True
    analysis_request = bool(re.search(
        r"(?:分析|解读|评估).{0,40}(?:睡眠|睡得|记录|数据|夜醒|深睡|浅睡|REM)|"
        r"(?:睡眠|记录|数据|夜醒|深睡|浅睡|REM).{0,30}(?:分析|解读|评估)|"
        r"(?:analy[sz]e|interpret|assess|review).{0,40}(?:sleep|records|data|awakenings)", text, re.I))
    # Explaining a person's dated records is interpretation. Explaining a
    # general concept/field does not bind the page's selected profile.
    personal_context = bool(explicit or profile or (followup and previous.get("resolved_period"))
                            or re.search(r"我的|我这|这周|本周|上周|这一天|这晚|当晚|那晚|所选|当前|这份|这条|\bmy\b|this night|selected", text))
    personal_explanation = (not knowledge_only and personal_context
                            and re.search(r"解释|讲解|说明|\bexplain\b|help me understand", text)
                            and re.search(r"睡眠|睡得|记录|数据|夜醒|深睡|浅睡|rem|\bsleep\b|\brecords?\b|\bdata\b|awakenings", text))
    analysis_request = analysis_request or bool(personal_explanation)
    if re.search(r"不(?:用|要|需要)(?:再)?(?:分析|解读|评估|解释|讲解|说明)|(?:no|without) (?:analysis|interpretation|explanation)|just (?:show|list)", text, re.I):
        analysis_request = False
    overview = not knowledge_only and (bool(re.search(
        r"(?:这周|本周|上周|最近|我的|这[七7]天).{0,10}睡眠.{0,8}(?:如何|怎么样|怎样)|"
        r"(?:这周|本周|上周).{0,6}睡得.{0,4}(?:如何|怎么样|怎样)|"
        r"how (?:was|is|has|did).{0,20}(?:sleep|slept)|sleep (?:overview|summary)", text)) or
        (analysis_request and not requested_detail_metrics(text)))
    if overview:
        record = True
        topics.update({"duration", "quality"})
        if analysis_request and not re.search(r"平均|时长|duration|mean|average", text):
            topics.add("night_waking")
    if personal_assessment:
        record = True
        topics.update({"duration", "quality"})
    blank_zero = bool(re.search(r"blank|missing|空白|缺失", text) and re.search(r"zero|零", text) and re.search(r"average|coverage|平均|覆盖", text) and not profile)
    product_definition = bool(re.search(r"sleeplens|本产品|这个(?:产品|应用)|本系统", text, re.I) and re.search(r"定义|什么意思|什么是|是什么|含义|what.*mean|definition", text, re.I))
    definition = product_definition or blank_zero or bool(re.search(r"sleep_min|指标|医学标准|门槛|四夜|计算规则|展示规则|显示规则|分母|four.night|what does.*mean|metric|字段|calculation rule|comparison rule|denominator", text))
    if analysis_request and not re.search(r"计算规则|怎么算|计算公式|字段.{0,5}(?:含义|定义)|是什么意思|what.*mean", text, re.I):
        definition = False
    compound_rule = bool(definition and not knowledge_only
        and re.search(r"查|看看|查看|读取|列出|告诉我|给出|报出|算出|\bshow\b|look up|tell me|give me|calculate", text, re.I)
        and (explicit or profile or re.search(r"我的|我这|这周|本周|上周|所选|\bmy\b|\bselected\b", text, re.I)))
    if compound_rule:
        definition = False  # A field explanation must not consume a requested lookup.
        record = True
    source = bool(re.search(r"根据什么|来源|出处|source|reference", text))
    advice = bool(re.search(r"建议|改善|改进|怎么办|怎么.*睡|如何.*睡|计划|advice|recommend|sleep better|improve|plan", text))
    concept = bool(re.search(r"是什么(?!时候)|什么是|什么意思|什么区别|区别是什么|有何区别|what (?:is|are)|what does.*mean|difference between", text))
    detail_metrics = requested_detail_metrics(text) if not definition else ()
    for metric in set(detail_metrics) & {"deep", "light", "rem", "stages"}:
        topics.add({"deep": "deep_sleep", "light": "light_sleep", "rem": "rem_sleep", "stages": "sleep_stages"}[metric])
    if (advice and not knowledge_only and not definition
            and (explicit or profile or re.search(r"这一天|这晚|那晚|当天|当晚|所选|当前(?:睡眠|记录|档案)|这(?:份|条)(?:睡眠)?(?:记录|数据)|结合.{0,8}记录|this (?:night|day|record)|my records", text))):
        record = True
        topics.add("general_advice")
    detail_personal = bool(profile or explicit or (followup and previous.get("resolved_period")) or re.search(r"我|所选|这周|本周|上周|最近|近[一1]周|\bmy\b|\bselected\b|\bthis week\b|\blast week\b", text))
    interpretation = analysis_request or bool(re.search(r"正常|健康|够不够|够吗|才够|太少|偏少|太多|多吗|少吗|算多|算少|频繁|不足|越多越好|好吗|好不好|准确|靠谱吗|是否可靠|影响|(?:算|是|是否).{0,4}失眠|\bnormal\b|\bhealthy\b|\benough\b|too (?:little|much)|a lot|frequent|accurate|reliable|insomnia", text))
    if not detail_metrics and not personal_assessment and interpretation and followup and previous.get("resolved_period"):
        detail_metrics = tuple(metric for metric in previous.get("metrics", ()) if metric in {
            "sleep_onset", "wake_time", "awakenings", "awake", "deep", "light", "rem", "stages"})
        topics.update(previous.get("topics", ()))
    detail_lookup = bool(re.search(r"多少|多久|几点|几次|时长|分钟|占比|比例|分布|percentage|percent|proportion|distribution|\bmean\b|\baverage\b|how long|how much|\bshow\b", text))
    total_duration = bool(re.search(r"睡眠时长|(?<![深浅])睡了多久|(?<![深浅])睡多久|(?<!deep )(?<!light )(?<!rem )sleep duration|how much sleep", text))
    if detail_metrics and not total_duration:
        topics.discard("duration")
    if concept and re.search(r"入睡.*上床|上床.*入睡|sleep onset.*bedtime|bedtime.*sleep onset", text):
        topics.add("sleep_diary")
    clinical_definition = concept and not product_definition and bool(topics & {"sleep_stages", "deep_sleep", "light_sleep", "rem_sleep", "circadian", "night_waking", "sleep_diary", "wearables"})
    if interpretation and topics & {"deep_sleep", "light_sleep", "rem_sleep", "sleep_stages"}:
        topics.add("stage_distribution")
    if personal_assessment and advice:
        topics.add("general_advice")
    health_topics = topics - {"duration", "quality", "general_advice"}
    combined = record and (advice or health_topics or personal_assessment or overview) and not definition
    if (re.search(r"提醒|闹钟|连接.*手表|实时同步|remind|alarm|connect.*watch|real.time", text)
            or (not (health_topics - {"wearables"}) and re.search(r"计算公式|手表.*算法|algorithm|formula", text))):
        task = "capability"
    elif definition:
        task = "definition"
    elif combined:
        task = "combined"
    elif source:
        task = "sources"
    elif record:
        task = "records"
    elif advice or health_topics or re.search(r"成人|睡多久|几小时.*够|how (?:much|many).*sleep", text):
        task = "health"
    elif followup:
        task = previous.get("task", "conversation")
    else:
        task = "conversation"
    if clinical_definition and not detail_personal and task != "capability":
        task = "health"
        detail_metrics = ()
    elif detail_metrics:
        if not detail_personal and (interpretation or advice or not detail_lookup):
            task = "health"
            detail_metrics = ()
        else:
            task = "combined" if advice or interpretation else "records"
        if interpretation:
            personal_assessment = False  # Stage/count questions need their own evidence, not the duration-only template.
    metrics = []
    for name, pattern in (
        ("mean", r"平均|均值|average|mean|睡.*多久"),
        ("coverage", r"覆盖|缺.*[天晚夜]|几[天晚夜].*(?:记录|缺)|coverage|missing|valid nights"),
        ("comparison", r"比较|前[一期周]|上周.*(?:比|好)|差值|变化|compare|previous|difference|change"),
        ("extrema", r"哪.*[天晚夜].*(?:短|长|少|多)|最[长短少多]|shortest|longest"),
        ("daily", r"逐[天夜]|每天.*(?:记录|醒|睡)|哪几[天晚夜]|各[天晚夜]|daily|night.by.night|which nights"),
    ):
        if re.search(pattern, text):
            metrics.append(name)
    if clinical_definition and task == "health":
        metrics = []
    if not metrics and followup and not detail_metrics:
        metrics = list(previous.get("metrics", ()))
    if detail_metrics:
        if total_duration and "mean" not in metrics:
            metrics.append("mean")
        if not total_duration:
            metrics = [metric for metric in metrics if metric not in {"mean", "comparison"}]
        metrics.extend(detail_metrics)
        if "awakenings" in detail_metrics and interpretation and task == "combined":
            metrics.extend(metric for metric in ("awake",) if metric not in metrics)
    if "extrema" in metrics:
        if re.search(r"最[短少]|shortest", text):
            metrics.append("shortest")
        if re.search(r"最[长多]|longest", text):
            metrics.append("longest")
    if comparison_request and "comparison" not in metrics:
        metrics.append("comparison")
    profile = re.search(r"(?<![a-z0-9])p0[123](?![a-z0-9])", text)
    period = None
    # "Last week" names the requested period unless it only appears as the
    # comparison baseline ("compare this week to last week").
    named_last_week = any(not any(start <= begin and end <= stop for start, stop in baseline_spans)
                          for begin, end in (m.span() for m in re.finditer(r"上周|上一周|last week", text)))
    if today and named_last_week and not re.search(r"比上周|和上周|与上周|with last week|than last week", text):
        end = today - timedelta(days=today.weekday() + 1)
        period = ((end - timedelta(days=6)).isoformat(), end.isoformat())
    elif today and re.search(r"(?:最近|过去|近)(?:两|二|2)(?:个)?(?:周|星期)|(?:最近|过去|近)(?:十四|14)天|(?:last|past) (?:two weeks|2 weeks|fortnight|fourteen days|14 days)", text):
        period = ((today - timedelta(days=13)).isoformat(), today.isoformat())
    elif today and re.search(r"最近[七7]天|过去[七7]天|(?:最近|过去|近)[一1]周|last (?:seven|7) days|past (?:week|seven days|7 days)", text):
        period = ((today - timedelta(days=6)).isoformat(), today.isoformat())
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if len(dates) == 2:
        period = tuple(dates)
    elif followup and not period and previous.get("resolved_period"):
        period = tuple(previous["resolved_period"])
    unsupported = task in {"records", "combined"} and bool(re.search(r"一个月|整月|月报|monthly|last month", text))
    if explicit or date_error:
        period = explicit
        if not knowledge_only and task not in {"definition", "capability"}:
            task = "combined" if advice or interpretation or overview else "records"
        if explicit:
            unsupported = False
    if task == "combined" and interpretation and "awakenings" in metrics:
        topics.add("night_waking")
        metrics.extend(metric for metric in ("awake",) if metric not in metrics)
    if personal_assessment and "mean" not in metrics:
        metrics.append("mean")
    recap = bool(re.search(r"一句话.*(?:回顾|概括|总结)|one sentence.*recap", text))
    unavailable = unavailable_measurement(text)
    if unavailable:
        task = "capability"
    comparison = True if comparison_request or "comparison" in metrics else None
    if record_reference and followup and previous.get("resolved_period") and not explicit and not knowledge_only:
        comparison = previous.get("compare_previous", comparison)
    if re.search(r"不(?:用|要|需要)?(?:再)?比较|只看本期|without comparison|do not compare", text, re.I):
        comparison = False
        metrics = [metric for metric in metrics if metric != "comparison"]
    if period and period[0] == period[1]:
        comparison = False
    # While viewing the 14-day window, "compare with the previous week" means
    # its newer week against its older week, both of which are in the window.
    window = period or ((selected_query or {}).get("start_date"), (selected_query or {}).get("end_date"))
    try:
        window_days = (date.fromisoformat(window[1]) - date.fromisoformat(window[0])).days + 1
    except (TypeError, ValueError):
        window_days = None
    if window_days == 14:
        if comparison and not explicit:
            period = ((date.fromisoformat(window[1]) - timedelta(days=6)).isoformat(), window[1])
        else:
            comparison = False
    if experience_reply and not knowledge_only and not explicit and not profile:
        if previous.get("resolved_period"):
            task = "combined"
            period = tuple(previous["resolved_period"])
            # Feedback is an update, not a request for the previous metric list.
            supporting = ["awake"] if "return_to_sleep" in reply_fields else []
            if requested_detail_metrics(text) and (detail_lookup or interpretation or advice):
                metrics = list(dict.fromkeys((*metrics, *supporting)))
            elif not analysis_request:
                metrics = supporting
            # Keep explicit risk topics; an ordinary report of falling asleep
            # easily must not acquire an insomnia workflow from the word 入睡.
            if not re.search(r"失眠|insomnia|睡不着|can't sleep|cannot sleep", text):
                topics.discard("insomnia")
            topics.update({"night_waking"} if "return_to_sleep" in reply_fields else {"quality", "daytime"})
        else:
            task = "conversation"
    return QueryPlan(task=task, metrics=tuple(metrics), topics=tuple(sorted(topics)), no_caffeine=no_caffeine,
                     experience_reply=experience_reply, experience_fields=reply_fields,
                     include_rule_explanation=compound_rule,
                     include_detail_means=bool("daily" in metrics and re.search(r"平均|均值|\bmean\b|\baverage\b", text)),
                     date_error=date_error, date_source=date_source,
                     no_coffee=no_coffee, caffeine_question=caffeine_question,
                     profile_id=profile.group().upper() if profile else (previous.get("profile_id") if followup and not knowledge_only else None), period=period,
                     compare_previous=comparison,
                     brief=bool(re.search(r"一句话|简短|简单说|one sentence|brief|short answer", text)) and not recap,
                     followup=followup, unsupported_window=unsupported, focus_citations=focus,
                     special_population=population_scope(text) == "special",
                     population_scope=population_scope(text),
                     knowledge_only=knowledge_only, compare_sources=compare_sources, brief_record_recap=recap,
                     lead_change=bool(re.search(r"先.*变化|lead with.*change", text)),
                     personal_assessment=personal_assessment, wants_improvement=advice,
                     wants_analysis=analysis_request,
                     sleep_overview=overview,
                     unavailable_measurement=unavailable,
                     causality_question=bool(re.search(r"(?:记录|数据).*(?:能不能|能否|是否).*(?:判断|证明)|是不是.*造成|caused|causal", text)))


def population_scope(question):
    """Bind a mentioned population to the sleep subject within its clause."""
    text = re.sub(r"没有怀孕|未怀孕|不是孕妇|非孕期|\bnot pregnant\b", "", question.lower())
    special = r"孩子|儿童|宝宝|孕期|怀孕|孕妇|青少年|\bchild(?:ren)?\b|\bbaby\b|\bpregnan\w*|\bteen\w*"
    if not re.search(special, text):
        return "adult"
    if re.search(r"我(?:正在|已经|目前|现在)?(?:怀孕|处于孕期)|我是(?:青少年|儿童)|\bi (?:am|'m) (?:pregnant|a teen)", text):
        return "special"
    sleep = r"睡|失眠|夜醒|sleep|insomnia|awaken|nap"
    adult = r"我自己|我本人|本人|成年人|成人|我的睡眠|我(?!(?:家|的)?(?:孩子|宝宝))|my own|my sleep|\bi\b|\badults?\b"
    adult_target = special_target = False
    for clause in re.split(r"[，,。.!！？?；;\n]|但是|不过|而是|但|\bbut\b", text):
        concern = re.search(sleep + r"|也一样|也有同样问题", clause)
        if not concern:
            continue
        subject_text = clause[:concern.start()]
        special_mentions = list(re.finditer(special, subject_text))
        adult_mentions = list(re.finditer(adult, subject_text))
        has_special = bool(special_mentions)
        has_adult = bool(adult_mentions)
        joint = bool(re.search(r"(?:我|成人).{0,4}(?:和|与|跟|及).{0,4}(?:孩子|宝宝|儿童)|(?:孩子|宝宝).{0,4}(?:和|与|跟).{0,4}我|\b(?:i and my child|my child and i)\b", clause))
        if joint:
            adult_target = special_target = True
        elif has_special and has_adult:
            if adult_mentions[-1].start() > special_mentions[-1].start():
                adult_target = True
            else:
                special_target = True
        elif has_special:
            special_target = True
        elif has_adult:
            adult_target = True
    if adult_target and special_target:
        return "mixed"
    if adult_target:
        return "adult"
    if special_target:
        return "special"
    return "unclear"


def unavailable_measurement(question):
    """Recognize factual clock-time/latency lookups, not general sleep advice."""
    text = question.lower()
    if re.search(r"建议|改善|怎么办|应该|合适|正常|为什么|原因|什么意思|是什么(?:意思|含义)|定义|区别|"
                 r"advice|recommend|should|improve|why|what does.*mean|definition|difference between", text):
        return None
    if not re.search(r"我的?|上周|这周|本周|昨晚|记录|平均|p0[123]|几点|my|last week|last night|average|what time|when did", text):
        return None
    # A mixed question still goes through the model, which can answer its
    # supported part and explain the missing fields from the supplied B rules.
    if re.search(r"睡眠时长|睡了多久|睡多久|sleep duration|how (?:long|much).*(?:did i sleep|i slept)", text):
        return None
    if re.search(r"入睡潜伏期|多久.{0,6}(?:入睡|睡着)|(?:入睡|睡着).{0,6}(?:多久|多长)|sleep latency|how long.*(?:fall|fell).*asleep", text):
        return "sleep_latency"
    if re.search(r"就寝时间|上床时间|几点.{0,4}上床|(?:average|my) bedtime|(?:what time|when).*(?:go|went).*bed", text):
        return "bedtime"
    if re.search(r"起床时间|几点.{0,4}起床|(?:average|my) (?:get.up time|rise time)", text):
        return "get_up_time"
    return None


def requested_detail_metrics(text):
    patterns = {
        "sleep_onset": r"入睡(?:时间|时刻)|几点.{0,4}(?:入睡|睡着|睡觉)|sleep.onset|(?:what time|when).*(?:fall|fell).*asleep",
        "wake_time": r"(?:醒来|醒觉)(?:时间|时刻)|几点.{0,4}醒来|wake.up time|wake time|(?:what time|when).*(?:wake|woke).*up",
        "awakenings": r"夜间醒来|夜醒|醒了几次|醒来次数|night.*awakenings|awakening count|how many times.*(?:wake|woke)",
        "awake": r"夜间清醒|清醒时长|awake (?:minutes|time|duration)",
    }
    return tuple(name for name, pattern in patterns.items() if re.search(pattern, text, re.I)) + named_stage_metrics(text)


def explain_unavailable_measurement(measurement, language):
    labels = {"bedtime": ("几点上床", "bedtime"),
              "sleep_latency": ("平均需要多久才能入睡", "average time taken to fall asleep"),
              "get_up_time": ("几点离床起床", "get-up time")}
    if measurement not in labels:
        return None
    zh = language == "Chinese"
    label = labels[measurement][0 if zh else 1]
    if zh:
        return (f"你问的是“{label}”。目前已有入睡和最终醒来的时刻，但没有上床、离床时间，所以还不能计算这一项。"
                "入睡时刻不等于上床时刻，醒来也不等于已经起床。[B1:Fields]\n\n"
                "可以查询平均几点入睡、几点醒来、夜醒次数，以及深睡、浅睡和REM时长。")
    return (f"You're asking for your {label}. Sleep onset and final wake-up are recorded, but bedtime and get-up time are not, "
            "so this result cannot be calculated. Falling asleep is distinct from going to bed, and waking is distinct from getting out of bed. [B1:Fields]\n\n"
            "I can report mean sleep-onset and wake-up times, awakening counts, and deep/light/REM durations.")


def search_query(question, plan):
    """Search the user's topic, never the rejected model's invented claims."""
    topics = set(plan.topics)
    if plan.exclude_caffeine:
        topics.discard("caffeine")
    if plan.task in {"health", "combined"} and not topics:
        topics.add("general_advice")
    # Canonical topics work with both Chinese and English source metadata.
    terms = {"general_advice": "sleep advice routine relaxation", "night_waking": "night waking return to sleep daytime impact",
             "persistent_insomnia": "persistent insomnia CBT-I seek help", "breathing": "sleep apnea breathing pauses",
             "medication": "medication melatonin sleep aids", "cbti": "CBT-I", "duration": "how much sleep", "quality": "sleep quality",
             "sleep_stages": "sleep stages", "deep_sleep": "deep sleep", "light_sleep": "light sleep",
             "rem_sleep": "REM", "stage_distribution": "stage distribution", "wearables": "wearable tracker",
             "circadian": "circadian body clock", "sleep_diary": "sleep diary", "naps": "nap",
             "screens": "screen", "relaxation": "relax wind down", "routine": "routine schedule",
             "daytime": "daytime sleep tired", "help": "seek help"}
    if topics:
        return " ".join(terms.get(topic, topic.replace("_", " ")) for topic in sorted(topics))[:500]
    return question[:500]
