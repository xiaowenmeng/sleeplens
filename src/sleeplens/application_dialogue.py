"""Application-owned introductions and social replies, not health guidance."""
import re
import unicodedata


def application_dialogue_kind(question):
    if not isinstance(question, str):
        return None
    text = unicodedata.normalize("NFKC", question).lower()
    compact = re.sub(r"[\W_]", "", text)
    prefix = r"(?:(?:你好|您好|嗨|哈喽|hi|hello))?(?:(?:请问|请|想问一下|我想知道|我想了解|告诉我))?"
    subject = r"(?:你|您|你们|这个助手|这个agent|sleeplens)"
    predicates = (
        r"(?:能(?:够)?|可以)(?:(?:帮助|帮)我)?(?:做些什么|做什么|干什么|做哪些事(?:情)?|提供什么帮助|提供哪些帮助)",
        r"(?:能(?:够)?|可以|会)(?:帮我)?(?:分析|解读|回答|处理)(?:哪些|什么)(?:睡眠问题|睡眠记录|睡眠数据|睡眠指标|指标|问题|数据)",
        r"有(?:哪些|什么)(?:功能|作用|能力)",
        r"能帮我(?:什么忙|做哪些事(?:情)?)",
        r"是(?:谁|什么助手|什么agent)",
        r"叫什么(?:名字)?",
    )
    predicate = "(?:" + "|".join(predicates) + ")"
    introduction = r"(?:简单|简短)?介绍(?:一下|下)?(?:你自己|自己|你|sleeplens|你的功能)|自我介绍(?:一下|下)?"
    ending = r"(?:呢|呀|啊|吗)?"
    first = "(?:" + subject + predicate + "|" + introduction + ")" + ending
    continuation = "(?:" + subject + ")?" + predicate
    # Accept several complete introduction clauses, including an omitted
    # repeated subject. Full matching keeps any added data/health request out
    # of this application-owned answer path.
    further = r"(?:(?:以及|还有|并且|另外|顺便|和|也|再)?" + prefix + "(?:" + continuation + "|" + introduction + ")" + ending + ")*"
    if re.fullmatch(prefix + first + further, compact):
        return "capabilities"
    english = re.sub(r"[^a-z\s']", " ", text)
    english = re.sub(r"\s+", " ", english).strip()
    english_clause = r"(?:please )?(?:what can you (?:do|help me with)|what (?:are|is) your (?:capabilities|features)|what(?: is|'s) your name|(?:which|what) sleep (?:metrics|data) can you (?:analyze|analyse|show)|who are you|introduce yourself|tell me about (?:yourself|your (?:capabilities|features))|how can you help(?: me)?|what do you do)"
    if re.fullmatch(r"(?:(?:hi|hello|hey) )?" + english_clause + r"(?: (?:(?:and also|and|also|then) )?" + english_clause + r")*", english):
        return "capabilities"
    if re.fullmatch(r"你好|您好|嗨|哈喽|早上好|晚上好|hi|hello|hey|good morning|good evening", text.strip(" \t\n!?！？。.")):
        return "greeting"
    if re.fullmatch(r"谢谢(?:你|您|啦)?|多谢|感谢(?:你|您)?|thanks(?: a lot)?|thank you(?: very much)?", text.strip(" \t\n!?！？。.")):
        return "thanks"
    return None


def split_introduction(question):
    """Separate only a complete introduction prefix from the remaining task."""
    for boundary in reversed(list(re.finditer(r"[，,。！？!?；;\n]+", question))):
        prefix, rest = question[:boundary.start()], question[boundary.end():].strip()
        if rest and application_dialogue_kind(prefix) == "capabilities":
            rest = re.sub(r"^(?:顺便|另外|再|以及|and\b|also\b)\s*", "", rest, flags=re.I)
            return prefix, rest
    return None, question


FIELD_DESCRIPTIONS = {
    "night_awakenings": (r"夜醒次数|night_awakenings|night awakenings|awakening count", "夜醒次数记录入睡后、最终醒来前的中途醒来次数，不包含最终醒来。", "Night awakenings count recorded intermediate awakenings after sleep onset and before final wake-up; final wake-up is excluded."),
    "sleep_min": (r"sleep_min|睡眠时长", "睡眠时长字段记录睡着的总分钟数，不包含中途清醒时间。", "sleep_min records total sleeping minutes, excluding intermediate awake time."),
    "awake_min": (r"awake_min|清醒分钟数|夜间清醒时长", "清醒分钟数记录入睡后、最终醒来前的中途清醒总时长。", "awake_min records total intermediate awake minutes between sleep onset and final awakening."),
    "deep_sleep_min": (r"deep_sleep_min|深睡时长", "深睡时长字段记录深睡阶段的总分钟数。", "deep_sleep_min records the total deep-sleep minutes."),
    "light_sleep_min": (r"light_sleep_min|浅睡时长", "浅睡时长字段记录浅睡阶段的总分钟数。", "light_sleep_min records the total light-sleep minutes."),
    "rem_sleep_min": (r"rem_sleep_min|REM时长", "REM时长字段记录REM阶段的总分钟数。", "rem_sleep_min records the total REM minutes."),
    "sleep_onset": (r"sleep_onset|入睡时刻", "入睡时刻记录开始睡着的时间，不等于上床时间。", "sleep_onset records when sleep began; it is distinct from bedtime."),
    "wake_time": (r"wake_time|最终醒来时刻", "最终醒来时刻记录这次睡眠最后醒来的时间，不等于离床时间。", "wake_time records final awakening, which is distinct from getting out of bed."),
}


def product_field_kind(question, *, include_implicit=False):
    text = unicodedata.normalize("NFKC", question).strip(" \t\n?？。.!！").lower()
    if not include_implicit and not re.search(r"字段|指标|\bfield\b|\bmetric\b", text):
        return None
    for name, (aliases, _, _) in FIELD_DESCRIPTIONS.items():
        field = "(?:" + aliases.lower() + ")"
        if (re.fullmatch(r"(?:请)?(?:解释|说明|介绍)(?:一下)?" + field + r"(?:这个|这一|该)?(?:字段|指标)?(?:的)?(?:含义|定义)?", text)
                or re.fullmatch(field + r"(?:这个|这一|该)?(?:字段|指标)?(?:是?什么意思|含义是什么|记录什么|记录的是什么|如何定义)", text)
                or re.fullmatch(r"what does (?:the )?" + field + r"(?: field)? (?:mean|record)", text)):
            return name
    return None


def product_field_reply(field, language):
    return FIELD_DESCRIPTIONS[field][1 if language == "Chinese" else 2] + " [B1:Fields]"


def is_product_description(text):
    """Recognize product operations/field semantics, never a health conclusion."""
    plain = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]|[*#`]", "", text)
    if re.search(r"建议|应该|尽量|避免|服用|导致|改善|正常|健康|失眠|治愈|\b(?:should|recommend|take|avoid|causes?|improves?|normal|healthy|insomnia|cure)\b", plain, re.I):
        return False
    clauses = [c.strip(" -:\t") for c in re.split(r"[，,。.!！？?；;\n]+", plain) if c.strip(" -:\t")]
    if not clauses:
        return False
    operation = r"(?:我(?:还)?(?:可以|能|会)|(?:也)?可以|支持)(?:帮你|为你)?(?:展示|查看|查询|列出|显示|读取|比较|解释|解读|分析|介绍|讨论).+|I can (?:display|show|read|query|list|compare|explain|analy[sz]e|discuss).+"
    identity = r"(?:你好[！!]?|我是\s*SleepLens|我叫\s*SleepLens|I am SleepLens|I'm SleepLens)"
    definition = r"(?:夜醒次数|night_awakenings)(?:这个字段|字段)?记录.+|不包含最终醒来|(?:the )?night.awakenings field records .+"
    return all(re.fullmatch(identity + "|" + operation + "|" + definition, clause, re.I) for clause in clauses)


def identity_reply(language):
    return "我是 SleepLens，可以查询和解释睡眠记录。" if language == "Chinese" else "I'm SleepLens. I can look up and explain sleep records."


def application_reply(kind, language):
    zh = language == "Chinese"
    if kind == "capabilities":
        return ("你好！我是 SleepLens，可以帮你：\n\n"
                "- 查看已结束的一周睡眠记录，并与前一周比较。\n"
                "- 按天查看睡眠时长、入睡和醒来时刻、夜醒次数、清醒分钟数，以及深睡、浅睡和 REM 时长。\n"
                "- 结合记录与已有资料，解释睡眠变化，讨论你想改善的困扰。\n\n"
                "你想先看看记录，还是聊聊最近的睡眠？" if zh else
                "Hello! I'm SleepLens. I can help you:\n\n"
                "- Explore a completed week of sleep records and compare it with the preceding week.\n"
                "- View nightly duration, sleep-onset and wake-up times, awakenings, awake minutes, and deep/light/REM totals.\n"
                "- Explain patterns using your selected records and available sources, and discuss sleep concerns.\n\n"
                "Would you like to explore records or talk about your sleep?")
    if kind == "greeting":
        return "你好，我是 SleepLens。想看看睡眠记录，还是聊聊最近睡得怎么样？" if zh else "Hi, I'm SleepLens. Would you like to explore your records or talk about how you've been sleeping?"
    if kind == "thanks":
        return "不客气，有想继续了解的睡眠问题，随时问我。" if zh else "You're welcome. Feel free to ask another sleep question."
    raise ValueError("Unknown application dialogue kind")
