"""Check model-written measurements against scoped records, not prose templates.

Literal grounding is deliberately narrower than a medical/semantic verifier.
Conversions, stage shares and cited-duration differences are computed here.
"""
import math
import re
from datetime import datetime


def normalize_record_format(text):
    """Canonicalize unambiguous date/clock spelling, never measurement values."""
    def date_text(match):
        try:
            return datetime(*map(int, match.groups())).date().isoformat()
        except ValueError:
            # Keep impossible values for the date-scope gate to reject.
            return f"{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}"
    text = re.sub(r"(?<!\d)(\d{4})\s*(?:/|年)\s*(\d{1,2})\s*(?:/|月)\s*(\d{1,2})(?:日)?(?!\d)", date_text, text)
    text = re.sub(r"(?<!\d)(\d{1,2})\s*点\s*(\d{2})\s*分(?!钟)",
                  lambda m: f"{int(m[1]):02d}:{m[2]}", text)
    return re.sub(r"(?<=\d)：(?=\d{2}(?!\d))", ":", text)


NUMBER = r"(?:[-+−]?\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百半]+|zero|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|half)"
MONTHS = "January February March April May June July August September October November December".split()
QUANTITIES = re.compile(
    rf"(?<!\d)(?<!\d{{4}}-\d{{2}}-)(?P<number>{NUMBER})\s*(?:个\s*)?(?P<unit>(?P<hour_unit>hours?|hrs?|h\b|小时)|minutes?|mins?|分钟|分(?=\W|$)|次|times?|awakenings?|%|％|夜晚|晚|夜|nights?|天|days?)"
    rf"(?(hour_unit)(?:\s*(?:and\s+)?(?P<minutes>{NUMBER})\s*(?:分钟|分(?=\W|$)|minutes?|mins?))?)", re.I)
FIELD_TERMS = {
    "deep_sleep_min": r"深睡|deep(?: sleep)?",
    "light_sleep_min": r"浅睡|light(?: sleep)?",
    "rem_sleep_min": r"REM|快速眼动",
    "awake_min": r"(?:夜间|中途)?清醒|醒着|awake(?: time| duration| minutes)?",
    "night_awakenings": r"夜醒|夜间醒来|中途醒|醒了|awakening(?:s| count)?|woke|wake up",
    "sleep_onset": r"入睡|睡着|sleep onset|fell asleep",
    "wake_time": r"最终醒来|最后醒来|早上醒|醒来(?:时间|时刻)|wake(?:-up)? time|final wak",
    "coverage": r"覆盖率|coverage",
    "sleep_min": r"睡眠时长|睡眠时间|总睡眠|睡了|总共睡|总时长|sleep duration|total sleep|slept",
}


def record_validation_text(text, output):
    """Give Markdown table values their explicit column/date context.

    This is a line-preserving validation view. The displayed answer is never
    rewritten, and values are never inferred from a neighboring data field.
    """
    if not output or not output.get("current") or "|" not in text:
        return text
    lines = text.splitlines()
    known_dates = [row["record_date"] for rows in (output.get("daily_records") or {}).values() for row in rows or []]
    def cells(line):
        return [cell.strip() for cell in line.strip().strip("|").split("|")]
    def date_prefix(value):
        value = re.sub(r"[*`_]", "", value).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
        match = re.fullmatch(r"(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})\s*(?:日|号)?", value)
        if not match:
            return value
        month, day = map(int, match.groups())
        matches = [day_text for day_text in known_dates if day_text.endswith(f"-{month:02d}-{day:02d}")]
        year = (output.get("period") or {}).get("start_date", "")[:4]
        return matches[0] if matches else (f"{year}-{month:02d}-{day:02d}" if year else value)
    result, headers = [], None
    for index, line in enumerate(lines):
        if ("|" in line and index + 1 < len(lines)
                and all(re.fullmatch(r":?-{3,}:?", part) for part in cells(lines[index + 1]))):
            headers = cells(line)
            result.append(line)
            continue
        if headers and "|" in line:
            values = cells(line)
            if all(re.fullmatch(r":?-{3,}:?", part) for part in values):
                result.append(line)
                continue
            date_column = next((i for i, header in enumerate(headers)
                                if re.search(r"日期|醒来日|夜晚|record_date|\bdate\b|^night$", header, re.I)), None)
            if date_column is not None and len(values) == len(headers):
                prefix = date_prefix(values[date_column])
                parts = []
                for column, (header, value) in enumerate(zip(headers, values)):
                    if column == date_column:
                        continue
                    header = re.sub(r"[*`_]", "", header)
                    stage_order = sorted((m.start(), field) for field in ("deep_sleep_min", "light_sleep_min", "rem_sleep_min")
                                         if (m := re.search(FIELD_TERMS[field], header, re.I)))
                    triple = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*", value)
                    pair = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*", value)
                    if len(stage_order) == 3 and triple:
                        labels = {"deep_sleep_min": "深睡", "light_sleep_min": "浅睡", "rem_sleep_min": "REM"}
                        unit = "%" if re.search(r"%|百分比|percent", header, re.I) else "分钟"
                        parts.extend(f"{prefix} {labels[field]} {number_text}{unit}"
                                     for (_, field), number_text in zip(stage_order, triple.groups()))
                    elif pair and re.search(r"夜醒|awakenings", header, re.I) and re.search(r"清醒|awake", header, re.I):
                        parts.extend((f"{prefix} 夜醒 {pair[1]}次", f"{prefix} 清醒 {pair[2]}分钟"))
                    else:
                        parts.append(f"{prefix} {header}: {value}")
                result.append("，".join(parts))
                continue
        if line.strip() and "|" not in line:
            headers = None
        result.append(line)
    return "\n".join(result)


def _dated_rows(prefix, rows, *, timestamp_fields=()):
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", prefix)
    if dates:
        if timestamp_fields and re.search(r"\d{4}-\d{2}-\d{2}\s*$", prefix):
            after_first = prefix.split(dates[0], 1)[1]
            if len(dates) > 1 and re.match(r"\s*(?:的)?(?:睡眠|记录|入睡|最终醒来|最后醒来|sleep|wake)", after_first, re.I):
                rows = [row for row in rows if row["record_date"] == dates[0]]
            return [row for row in rows if any(row.get(field) and row[field][:10] == dates[-1]
                                               for field in timestamp_fields)], True
        return [row for row in rows if row["record_date"] == dates[-1]], True
    dates = re.findall(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)", prefix)
    if dates:
        month, day = map(int, dates[-1])
        return [row for row in rows if row["record_date"].endswith(f"-{month:02d}-{day:02d}")], True
    month_pattern = "|".join(MONTHS)
    english = list(re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\b|\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", prefix, re.I))
    if english:
        last = english[-1]
        day = int(last[1] or last[4])
        month = next(i for i, name in enumerate(MONTHS, 1) if name.lower() == (last[2] or last[3]).lower())
        ordinals = re.findall(r"\b(?:the|on)\s+(\d{1,2})(?:st|nd|rd|th)\b", prefix[last.end():], re.I)
        if ordinals:
            day = int(ordinals[-1])
        return [row for row in rows if row["record_date"].endswith(f"-{month:02d}-{day:02d}")], True
    return rows, False


def _period_label(prefix, period):
    named = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:to|through|至|到|[-–—])\s*(\d{4}-\d{2}-\d{2})", prefix, re.I)
    if named:
        return named.groups() == (period.get("start_date"), period.get("end_date"))
    named = re.search(rf"\b(\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})\s+({'|'.join(MONTHS)})\b", prefix, re.I)
    if named and period:
        month = next(i for i, name in enumerate(MONTHS, 1) if name.lower() == named[3].lower())
        return (period.get("start_date", "").endswith(f"-{month:02d}-{int(named[1]):02d}")
                and period.get("end_date", "").endswith(f"-{month:02d}-{int(named[2]):02d}"))
    return False


def number(value):
    value = value.lower().replace("−", "-")
    try:
        return float(value)
    except ValueError:
        pass
    words = dict(zip("zero one two three four five six seven eight nine ten twenty thirty half".split(),
                     [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, .5]))
    if value in words:
        return words[value]
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits.update({"两": 2, "〇": 0, "半": .5})
    if value in digits:
        return digits[value]
    for marker, multiplier in (("百", 100), ("十", 10)):
        if marker in value:
            left, right = value.split(marker, 1)
            return (number(left) if left else 1) * multiplier + (number(right) if right else 0)
    return math.nan


def measurement(match):
    unit = match["unit"].lower()
    value = number(match["number"])
    if unit in {"小时", "hour", "hours", "hr", "hrs", "h"}:
        return "minutes", value * 60 + (number(match["minutes"]) if match["minutes"] else 0)
    if unit in {"分钟", "分", "minute", "minutes", "min", "mins"}:
        return "minutes", value
    if unit in {"%", "％"}:
        return "percent", value
    return ("count" if unit in {"次", "time", "times", "awakening", "awakenings"} else "nights"), value


def _context(text, start, end):
    # Keep decimal points intact; commas delimit separate measurements.
    boundary = r"[，,；;。!?！？\n]|(?<!\d)\.|\.(?!\d)"
    prefix = re.split(boundary, text[:start])[-1][-100:]
    suffix = re.split(boundary, text[end:])[0][:45]
    return prefix, suffix


def _field(prefix, kind):
    found = []
    for field, pattern in FIELD_TERMS.items():
        for match in re.finditer(pattern, prefix, re.I):
            if kind == "count" and field != "night_awakenings":
                continue
            if kind == "minutes" and field in {"sleep_onset", "wake_time", "coverage"}:
                continue
            found.append((match.end(), field))
    return max(found)[1] if found else None


def _record_tolerance(match):
    """Half the last written unit; compound hours use minute precision."""
    written = match["minutes"] if match["minutes"] is not None else match["number"]
    precision = len(written.partition(".")[2]) if "." in written else 0
    scale = 60 if match["hour_unit"] and match["minutes"] is None else 1
    return .5 * 10 ** -precision * scale + 1e-7


def temporal_reference_quantity(text, match):
    """The one in '前一晚' locates a night; it does not count recorded nights."""
    kind, value = measurement(match)
    prefix, suffix = _context(text, match.start(), match.end())
    return (kind == "nights" and value == 1 and match["unit"] in {"晚", "夜", "天"}
            and prefix.endswith(("前", "后"))
            and not re.match(r"\s*(?:有效|valid|recorded)", suffix, re.I))


def discourse_quantity(text, match):
    """'A single night cannot prove ...' is not a measured night count."""
    kind, value = measurement(match)
    prefix, suffix = _context(text, match.start(), match.end())
    if temporal_reference_quantity(text, match):
        return True
    if (kind == "nights" and value == 1 and match["unit"] == "天"
            and prefix.endswith(("换", "另")) and re.match(r"\s*(?:查看|查询|看|查|的记录)", suffix)):
        return True  # A proposed different date is not an observed night count.
    if kind == "nights" and prefix.endswith("第") and match["unit"].lower() in {"天", "day", "days"}:
        return True  # "第二天的精神状态" is an ordinal, not a two-day prescription.
    if re.match(r"\s*(?:有效|valid|recorded)", suffix, re.I):
        return False
    poor_night_condition = (
        (match["unit"] in {"夜", "晚"} and re.match(r"\s*(?:没(?:有)?睡好|睡不好|睡得不好)(?:之后|以后|后)", suffix))
        or (match["unit"].lower() in {"night", "nights"} and re.search(r"\bafter\s*$", prefix, re.I)
            and re.match(r"\s+of (?:poor|bad) sleep\b", suffix, re.I)))
    if (kind == "nights" and value == 1 and poor_night_condition
            and not re.search(r"记录|有效|总共|一共|共有|连续|本期|前期|本周|上周|昨|你的|我的|您的|P0[123]|有\s*$|\b(?:your|my|records?|recorded|observed|measured)\b", prefix, re.I)):
        return True  # "After a poor night" describes a condition, not coverage.
    return value == 1 and ((kind == "nights" and bool(re.search(r"单凭|仅凭|只凭|只看|仅看|单看|single|only|这$|那$|当$|同$|某$|每$", prefix, re.I))) or
                           (kind == "count" and bool(re.search(r"最后|最终|每", prefix))))


def stage_triples(text, output):
    valid = []
    rows = [row for scope in (output.get("daily_records") or {}).values() for row in scope or []] if output else []
    fields = ["deep_sleep_min", "light_sleep_min", "rem_sleep_min"]
    for match in re.finditer(r"(?<![\d/])(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*(?:分钟|minutes?)(?![a-z])", text, re.I):
        before = text[max(0, match.start() - 100):match.start()]
        mentions = sorted((m.end(), field) for field in fields for m in re.finditer(FIELD_TERMS[field], before, re.I))
        order = list(dict.fromkeys(field for _, field in mentions[-3:]))
        order = order if len(order) == 3 else fields
        if any(tuple(row.get(field) for field in order) == tuple(map(int, match.groups())) for row in rows if row.get("sleep_valid")):
            valid.append(match)
    return valid


def product_definition_quantity(text, match, policy_references, *, evidence_text=None):
    """A quoted field-definition example is distinct from a personal value."""
    return (measurement(match) == ("count", 0)
            and "B1:ProductStages" in (policy_references or {})
            and "[B1:ProductStages]" in (evidence_text or text)
            and text[max(0, match.start()-1):match.start()] in {"“", '"', "‘", "'"}
            and bool(re.match(r"[”\"’']\s*(?:也)?只表示没有记录到", text[match.end():])))


def supports_measurement(text, match, output, health_evidence=""):
    """True/False for a record claim; None means a source/abstract quantity."""
    if not output or not output.get("current"):
        return None
    kind, value = measurement(match)
    if kind == "nights":
        fraction = re.search(r"(?<![\d/])(\d+)\s*/\s*$", text[:match.start()])
        if fraction:
            return any(int(fraction[1]) == stats[key] and value == stats["expected_nights"]
                       for stats in (output.get("current"), output.get("previous")) if stats
                       for key in ("valid_nights", "detail_nights"))
    if any(triple.start() <= match.start() < triple.end() for triple in stage_triples(text, output)):
        return True
    prefix, suffix = _context(text, match.start(), match.end())
    sentence_prefix = re.split(r"[。！？\n]|(?<!\d)\.|\.(?!\d)", text[:match.start()])[-1]
    post_comparison = bool(re.match(r"\s*(?:more|less|shorter|longer)\b", suffix, re.I))
    comparative = post_comparison or bool(re.search(r"比|较|差|少|多|增|减|shorter|longer|less|more|difference|change|below|above", prefix, re.I))
    record_scope = re.search(r"前周|前一周|前期|此前|上周|本期|本周|previous|preceding|recorded", prefix + suffix, re.I)
    if (health_evidence and not record_scope and not personal_quantity(text, match)
            and cited_quantity_supported(match, health_evidence)):
        return None  # A supported recommendation, not a measured personal field.
    delta_claim = bool(re.search(r"(?:少|多|差|减|增|不足)(?:了)?(?:约|大约)?\s*$|(?:less|more|shorter|longer|below|above)(?:\s+by)?\s*$|差值|差距|difference|change", prefix, re.I)) and not prefix.rstrip().endswith(("至少", "最少", "不少于", "不低于"))
    if comparative and (delta_claim or post_comparison) and (
            re.search(r"前周|前一周|前期|此前|上周|previous|preceding|difference|change|差值", prefix + suffix, re.I)
            or post_comparison):
        delta = output.get("difference_min")
        if kind != "minutes" or output.get("comparison_state") != "available" or delta is None:
            return False
        if _field(prefix, kind) not in {None, "sleep_min"}:
            return False  # No stage/awake-time comparison is provided by this tool.
        # "Previous week ... 9 minutes less" reverses the comparison subject.
        subjects = re.findall(r"\b(this|current|selected|previous|preceding) week", sentence_prefix, re.I)
        previous_subject = bool(subjects and subjects[-1].lower() in {"previous", "preceding"})
        directed_delta = -delta if previous_subject and post_comparison else delta
        if re.search(r"少|减|shorter|less", prefix + suffix, re.I) and directed_delta > 0:
            return False
        if re.search(r"多|增|longer|more", prefix + suffix, re.I) and directed_delta < 0:
            return False
        return math.isclose(value if value < 0 else abs(value), delta if value < 0 else abs(delta), abs_tol=_record_tolerance(match))
    if kind == "minutes" and re.search(r"(?:低于|短于|高于|长于)\s*$", prefix):
        actual = output["current"]["mean_sleep_min"]
        targets = [measurement(m)[1] for m in QUANTITIES.finditer(health_evidence) if measurement(m)[0] == "minutes"]
        if actual is not None and any(math.isclose(value, target, abs_tol=.051) for target in targets):
            return actual < value if re.search(r"低于|短于", prefix) else actual > value
        return False
    if (kind == "minutes" and re.search(r"达到(?:了)?\s*$|\bmeets?\s*$", prefix, re.I)
            and re.match(r"\s*(?:的)?(?:一般)?(?:参考|建议|标准|reference)", suffix, re.I)):
        actual = output["current"]["mean_sleep_min"]
        lower_bounds = [measurement(m)[1] for m in QUANTITIES.finditer(health_evidence)
                        if measurement(m)[0] == "minutes" and duration_signature(m)[2] == "minimum"]
        return actual is not None and actual >= value and any(math.isclose(value, target, abs_tol=.051) for target in lower_bounds)
    if comparative and delta_claim and kind == "minutes" and re.search(r"参考|建议|reference|recommend", sentence_prefix, re.I):
        targets = [measurement(m)[1] for m in QUANTITIES.finditer(health_evidence) if measurement(m)[0] == "minutes"]
        actual = output["current"]["mean_sleep_min"]
        if actual is None:
            return False
        return any(math.isclose(abs(actual - target), abs(value), abs_tol=.051) and
                   not (re.search(r"少|低|below|shorter", prefix, re.I) and actual > target) and
                   not (re.search(r"多|高|above|longer", prefix, re.I) and actual < target) for target in targets)
    target_prefix = re.split(r"这(?:一)?(?:晚|天|周)|当晚|本晚|记录(?:到|显示)|\brecorded\b", prefix, flags=re.I)[-1]
    if (re.search(r"建议|参考|标准|推荐|至少|应当|必须|需要|recommend|reference|guideline|at least|should|must|required", target_prefix[-40:], re.I)
            or re.match(r"\s*(?:的)?(?:一般)?(?:参考|建议|标准)", suffix)):
        return None  # A record value cannot justify a medical target with the same number.
    field = _field(prefix, kind)
    if kind == "count" and re.match(r"\s*(?:醒来|中途醒来|awakenings?)", suffix, re.I):
        field = "night_awakenings"
    if kind == "minutes" and field in {None, "night_awakenings"} and re.search(r"(?:共|合计|总共|累计|total(?:ing)?)(?:只有|仅|约)?\s*$", prefix, re.I):
        previous_clause = re.split(r"[。！？\n]", text[:match.start()])[-1]
        if re.search(FIELD_TERMS["night_awakenings"], previous_clause, re.I):
            field = "awake_min"
    if kind == "minutes" and re.search(r"三(?:者|项|段).*?(?:合计|相加)|(?:阶段|分期).*(?:合计|相加)", prefix):
        field = "sleep_min"
    for name, pattern in FIELD_TERMS.items():
        if kind == "count" and name != "night_awakenings":
            continue
        if re.match(r"\s*(?:的)?(?:" + pattern + r")", suffix, re.I):
            field = name
            break
    if kind == "percent" and field in {None, "sleep_min"}:
        stage_mentions = [(m.end(), name) for name in ("deep_sleep_min", "light_sleep_min", "rem_sleep_min")
                          for m in re.finditer(FIELD_TERMS[name], text[max(0, match.start() - 100):match.start()], re.I)]
        if stage_mentions:
            field = max(stage_mentions)[1]
    scope = "previous" if re.search(r"前周|前一周|前期|此前|上周|previous|preceding", prefix, re.I) else "current"
    stats = output.get(scope)
    if not stats:
        return False
    rows = (output.get("daily_records") or {}).get(scope) or []
    if kind == "minutes" and re.search(r"平均每次(?:约)?\s*$", prefix):
        return any(row.get("night_awakenings") and row.get("awake_min") is not None
                   and math.isclose(value, row["awake_min"] / row["night_awakenings"], abs_tol=.051)
                   for row in rows if row.get("sleep_valid"))
    period = output.get("previous_period" if scope == "previous" else "period") or {}
    if _period_label(prefix, period):
        dated = False  # A whole-period label does not make its mean a last-day value.
    else:
        rows, dated = _dated_rows(prefix, rows)
    if dated and not rows:
        return False
    valid = [row for row in rows if row.get("sleep_valid")]
    mean = not dated and bool(re.search(r"平均|均值|average|mean", prefix, re.I))
    if (not mean and re.search(r"平均|均值|average|mean", sentence_prefix, re.I)
            and not dated
            and not re.search(r"这晚|当晚|那晚|最短|最长|最少|最多|this night|shortest|longest", prefix, re.I)):
        mean = True
    values = []
    if kind == "percent":
        if field == "coverage":
            values = [100 * stats["coverage"]]
        elif field in {"deep_sleep_min", "light_sleep_min", "rem_sleep_min"}:
            if mean:
                # Aggregate shares use the same complete-detail denominator.
                denominator = sum(row["sleep_min"] for row in valid if row.get(field) is not None)
                if denominator:
                    values = [100 * sum(row[field] for row in valid if row.get(field) is not None) / denominator]
            else:
                values = [100 * row[field] / row["sleep_min"] for row in valid if row.get(field) is not None and row["sleep_min"]]
    elif kind == "count":
        if field not in {None, "night_awakenings"}:
            return False
        if mean:
            values = [stats.get("mean_night_awakenings")]
        elif re.search(r"总共|总计|合计|一共|共(?:记录(?:到)?)?\s*$|\btotal\b", prefix, re.I):
            values = [stats.get("total_night_awakenings")]
        else:
            values = [row.get("night_awakenings") for row in valid]
    elif kind == "nights":
        if re.search(r"\ball\s*$", prefix, re.I) and re.search(r"\b(?:valid|recorded|complete)\b", suffix, re.I):
            return value == stats["valid_nights"] == stats["expected_nights"]
        if re.match(r"\s*(?:没有|无|缺少).{0,8}(?:记录|数据)", suffix):
            values = [stats["unavailable_nights"]]
        elif re.match(r"\s*均计入", suffix):
            values = [stats["detail_nights"] if "详细" in sentence_prefix else stats["valid_nights"]]
        elif (re.search(r"有效|有记录|记录了|代表(?:了)?(?:这|其中)?\s*$|valid|recorded", prefix, re.I)
                or re.match(r"\s*(?:的)?(?:有效|数据|记录|有(?:有效)?记录|valid|recorded)", suffix, re.I)
                or re.match(r"\s*的.{0,15}(?:平均|均值|mean|average)", suffix, re.I)):
            values = [stats["valid_nights"]]
        elif re.search(r"缺|不可用|missing|unavailable", prefix, re.I):
            values = [stats["unavailable_nights"]]
        elif re.search(r"查询|范围|所选|覆盖\s*\d+\s*周\s*$|period|window|selected", prefix, re.I):
            values = [stats["expected_nights"]]
        else:
            return None  # A source interval, not necessarily a record count.
    else:
        fields = [field] if field in {"sleep_min", "deep_sleep_min", "light_sleep_min", "rem_sleep_min", "awake_min"} else ["sleep_min"]
        for name in fields:
            if mean or not rows:
                values.append(stats.get("mean_" + name))
            else:
                values.extend(row.get(name) for row in valid)
    tolerance = _record_tolerance(match) if kind == "percent" or (mean and kind in {"minutes", "count"}) else .051
    if kind == "minutes" and not match["minutes"] and (
            re.search(r"(?:接近|大约|约|approximately|about|nearly|roughly|around)\s*$", prefix, re.I)
            or re.match(r"\s*(?:左右|上下)", suffix)):
        # Explicit rounding follows the written unit/precision, not a fixed
        # grace period: 'about 7 hours' may round 410 min; '7 hours' may not.
        tolerance = _record_tolerance(match)
    return any(v is not None and math.isclose(value, v, abs_tol=tolerance) for v in values)


def validity_definition_quantity(text, match, policy_references):
    """Recognize a cited technical field bound, never an actual personal value."""
    evidence = (policy_references or {}).get("B1:Validity", "")
    bounds = re.search(r"integer from (\d+) to (\d+) minutes", evidence)
    if not bounds or "[B1:Validity]" not in text:
        return False
    start = max((m.end() for m in re.finditer(r"[。！？!?\n;；]", text[:match.start()])), default=0)
    stop = re.search(r"[。！？!?\n;；]", text[match.end():])
    end = match.end() + stop.start() if stop else len(text)
    clause = text[start:end]
    if personal_quantity(text, match):
        return False
    if measurement(match)[0] != "minutes":
        return False
    for interval in re.finditer(r"(\d+)\s*(?:到|至|[-–—]|to)\s*(\d+)\s*(?:分钟|minutes?)", clause, re.I):
        if (interval[1], interval[2]) == bounds.groups() and interval.start() <= match.start()-start < interval.end():
            return bool(re.search(r"技术|取值|字段|technical|field", clause, re.I))
    return (measurement(match)[1] == 0 and "valid zero is retained" in evidence
            and bool(re.search(r"有效|无效|缺失|空值|字段|零值|如果|不等于|不是一回事|不能.*(?:证明|断定)|valid|missing|field|\bif\b|does not (?:mean|prove)", clause, re.I)))


def personal_quantity(text, match):
    """Detect a local personal assertion before considering source quantities.

    General references elsewhere in the answer cannot license a measured value.
    Explicit conditionals and inference limitations are not measurements.
    """
    if temporal_reference_quantity(text, match):
        return False
    prefix, suffix = _context(text, match.start(), match.end())
    if re.search(r"如果|假设|假如|若(?:是|有|记录|你)|\b(?:if|suppose|assuming)\b|不能(?:直接)?(?:认为|证明|断定)|无法(?:据此)?(?:确认|证明)|不等于|不足以证明|does not (?:prove|mean)|cannot (?:prove|conclude|infer)", prefix, re.I):
        return False
    personal = bool(re.search(r"你的|我的|您的|你昨|我昨|P0[123]|这(?:一)?晚|这天|这一夜|该晚|该夜|昨晚|本期|前期|本周|上周|这条(?:有效)?记录|该条记录|\b(?:your|my|last night|this night)\b", prefix, re.I))
    assignment = bool(re.match(r"\s*(?:是|就是|为|is|was).{0,12}(?:你的|我的|您的|your|my).{0,12}(?:记录|时长|睡眠|record|sleep)", suffix, re.I))
    factual = bool(re.search(r"睡了|总睡眠|时长(?:是|为)|深睡|浅睡|REM|夜醒|清醒|记录.{0,50}(?:显示|测得|测到|不是|是|为)|\bslept\b|\b(?:record|duration).{0,40}(?:shows|was|is)\b", prefix, re.I))
    general = bool(re.search(r"一般|参考|建议|指导|规则|定义|技术|字段|取值|范围|reference|recommend|guidance|technical|field|range", prefix, re.I))
    sentence_prefix = re.split(r"[。!?！？;；\n]", text[:match.start()])[-1][-160:]
    if not general and re.search(r"记录.{0,20}(?:显示|测得|测到)|record.{0,20}shows|recorded sleep duration was", sentence_prefix, re.I):
        return True  # A comma does not erase the preceding measured-record subject.
    if assignment or (personal and (factual or not general)):
        return True
    if re.search(r"记录.{0,20}(?:显示|测得|测到)|record.{0,20}shows|recorded sleep duration was", prefix, re.I):
        return True
    return factual and not general and not re.search(r"有效记录|无效|缺失|空值|零值", prefix)


def duration_signature(match):
    """Minutes, interval endpoints and the qualifier of a duration assertion."""
    value = measurement(match)[1]
    start, end = match.start(), match.end()
    lower = upper = value
    join = r"\s*(?:到|至|[-–—]|to)\s*"
    others = [item for item in QUANTITIES.finditer(match.string) if measurement(item)[0] == "minutes"]
    previous = next((item for item in reversed(others) if item.end() <= start and re.fullmatch(join, match.string[item.end():start])), None)
    following = next((item for item in others if item.start() >= end and re.fullmatch(join, match.string[end:item.start()])), None)
    if previous:
        lower, start = measurement(previous)[1], previous.start()
    elif following:
        upper, end = measurement(following)[1], following.end()
    else:
        bare = re.search(rf"(?P<lower>{NUMBER})\s*(?:到|至|[-–—]|to)\s*$", match.string[:start], re.I)
        if bare:
            scale = 60 if match["unit"].lower() in {"小时", "hour", "hours", "hr", "hrs", "h"} else 1
            lower, start = number(bare["lower"]) * scale, bare.start()
    prefix = re.split(r"[，,。;；!?！？\n]", match.string[:start])[-1][-70:]
    suffix = match.string[end:end+10]
    qualifier = "exact"
    if re.search(r"(?:至少|最少|不少于|不低于|at least|no less than|minimum(?: of)?)\s*$", prefix, re.I):
        qualifier = "minimum"
    if re.search(r"(?:最多|至多|不超过|不多于|长达|(?:可|可能)持续|up to|at most|no more than|maximum(?: of)?)\s*$", prefix, re.I):
        qualifier = "maximum" if qualifier == "exact" else "conflicting"
    approximate = bool(re.search(r"(?:约|大约|大概|about|approximately|roughly)\s*$", prefix, re.I) or re.match(r"\s*左右", suffix))
    return lower, upper, qualifier, approximate


def cited_quantity_supported(match, evidence):
    """Reuse duration parsing while retaining bounds and comparison qualifiers."""
    def range_lower(item):
        lower = re.search(rf"(?P<lower>{NUMBER})\s*(?:到|至|[-–—]|to)\s*$", item.string[:item.start()], re.I)
        if lower is None:
            return None
        scale = 60 if item["unit"].lower() in {"小时", "hour", "hours", "hr", "hrs", "h"} else 1
        return number(lower["lower"]) * scale

    evidence = re.sub(r"\b(?:the|an?|a relaxing) hour\b", "one hour", evidence, flags=re.I)
    evidence = re.sub(r"\b(valid|recorded)\s+(nights?|days?)\b", r"\2", evidence, flags=re.I)
    evidence = re.sub(r"-(days?|nights?)\b", r" \1", evidence, flags=re.I)
    kind, value = measurement(match)
    if kind == "minutes":
        target = duration_signature(match)
        for source in QUANTITIES.finditer(evidence):
            if measurement(source)[0] != "minutes":
                continue
            candidate = duration_signature(source)
            if (all(math.isclose(a, b, abs_tol=.000001) for a, b in zip(target[:2], candidate[:2]))
                    and target[2:] == candidate[2:]):
                return True
        return False
    lower = range_lower(match)
    return any(kind == measurement(source)[0] and math.isclose(value, measurement(source)[1], abs_tol=.000001)
               and (lower is None or (range_lower(source) is not None and math.isclose(lower, range_lower(source), abs_tol=.000001)))
               for source in QUANTITIES.finditer(evidence))


def health_context(paragraph, references, *, answer=None):
    """Use supplied explicit references, or answer-level H context if untagged.

    An explicit B tag or unavailable H tag must never borrow another source.
    This is numeric context only, not a claim of semantic entailment.
    """
    ids = re.findall(r"\[([BH]\d+:[A-Za-z0-9_-]+)\]", paragraph)
    if not ids and answer is not None:
        ids = re.findall(r"\[(H\d+:[A-Za-z0-9_-]+)\]", answer)
    return " ".join(references.get(ref, "") for ref in ids if ref.startswith("H"))


def validate_record_claims(text, output, health_references, policy_references=None):
    text = record_validation_text(text, output)
    if not output or not output.get("current"):
        for paragraph in text.splitlines():
            refs = re.findall(r"\[([BH]\d+:[A-Za-z0-9_-]+)\]", paragraph)
            evidence = " ".join((health_references if ref.startswith("H") else (policy_references or {})).get(ref, "") for ref in refs)
            for match in QUANTITIES.finditer(paragraph):
                if personal_quantity(paragraph, match):
                    return "No usable record supports these personal quantities. Explain the lookup gap."
                if discourse_quantity(paragraph, match) or validity_definition_quantity(paragraph, match, policy_references):
                    continue
                if evidence:
                    if cited_quantity_supported(match, evidence):
                        continue
                    return "This general quantity is absent from its supplied supporting passage. Correct the value or unit."
                prefix, suffix = _context(paragraph, match.start(), match.end())
                if re.search(r"记录|这晚|这天|你的|your|\brecord\b|recorded|slept", prefix + suffix, re.I):
                    return "No usable record supports these personal quantities. Explain the lookup gap."
        return None
    clean = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", text)
    periods = [output.get("period"), output.get("previous_period")]
    rows = [row for scope in (output.get("daily_records") or {}).values() for row in scope or []]
    dates = {row["record_date"] for row in rows}
    dates.update(datetime.fromisoformat(row[field]).date().isoformat() for row in rows for field in ("sleep_onset", "wake_time") if row.get(field))
    dates.update(value for period in periods if period for value in period.values())
    available = output.get("available_period") or {}
    dates.update(available.values())
    for day in re.findall(r"\d{4}-\d{2}-\d{2}", clean):
        if day not in dates:
            return f"Record date {day} is outside the returned records; preserve the requested scope."
    for match in re.finditer(r"(?:平均|均值|\baverage\b|\bmean\b)[^\d\n。！？!?；;:：]{0,12}(?<![A-Za-z])(\d+(?:\.\d+)?)(?!\d)", clean, re.I):
        if re.match(r":\d{2}(?!\d)", clean[match.end():]):
            continue  # A clock mean is checked below as a clock, not minutes.
        # Explicit units are handled below; this catches unlabelled invented averages.
        if not re.match(r"\s*(?:个\s*)?(?:分钟|小时|次|%|夜晚|晚|夜|天|minutes?|hours?|nights?|days?|h\b|min\b)", clean[match.end():], re.I):
            values = [stats.get("mean_sleep_min") for stats in (output.get("current"), output.get("previous")) if stats]
            if not any(v is not None and math.isclose(float(match[1]), v, abs_tol=.051) for v in values):
                return "The unlabelled average is not a returned sleep-duration mean; use an explicit metric and unit."
    normalize_clock = lambda value: f"{int(value.split(':')[0]):02d}:{value.split(':')[1]}"
    ranges = list(re.finditer(r"(?<!\d)(\d{1,2}:\d{2})\s*(?:→|至|到|[-–—])\s*(\d{1,2}:\d{2})(?!\d)", clean))
    for clock_range in ranges:
        prefix, _ = _context(clean, clock_range.start(), clock_range.end())
        scoped_rows, _ = _dated_rows(prefix, rows, timestamp_fields=("sleep_onset",))
        permitted_ranges = {(datetime.fromisoformat(row["sleep_onset"]).strftime("%H:%M"), datetime.fromisoformat(row["wake_time"]).strftime("%H:%M")) for row in scoped_rows if row.get("sleep_onset") and row.get("wake_time")}
        if (normalize_clock(clock_range[1]), normalize_clock(clock_range[2])) not in permitted_ranges:
            return "The stated onset-to-wake interval does not match a returned record."
    for clock in re.finditer(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", clean):
        if any(interval.start() <= clock.start() < interval.end() for interval in ranges):
            continue
        prefix, suffix = _context(clean, clock.start(), clock.end())
        # A clock may precede its label ("00:00 入睡"). Prefer that
        # local label over earlier headings or the previous clock's label.
        field = None
        for name in ("sleep_onset", "wake_time"):
            pattern = FIELD_TERMS[name] + (r"|醒来" if name == "wake_time" else "")
            if re.match(r"\s*(?:\*\*)?(?:" + pattern + r")", suffix, re.I):
                field = name
                break
        if field is None:
            field = "wake_time" if re.search(r"醒来(?:时间)?[：:\s*]*$", prefix) else _field(prefix, "clock")
        fields = [field] if field in {"sleep_onset", "wake_time"} else ["sleep_onset", "wake_time"]
        scoped_rows, dated = _dated_rows(prefix, rows, timestamp_fields=fields)
        permitted = {datetime.fromisoformat(row[name]).strftime("%H:%M") for row in scoped_rows for name in fields if row.get(name)}
        if not dated:
            permitted.update(stats.get("mean_" + name) for stats in (output.get("current"), output.get("previous")) if stats for name in fields)
        hour, minute = clock.group().split(":")
        if f"{int(hour):02d}:{minute}" not in permitted:
            return f"Clock time {clock.group()} does not match the returned timing fields."
    triples = stage_triples(clean, output)
    for fraction in re.finditer(r"(?<![\d/])(\d+)\s*/\s*(\d+)(?![\d/])", clean):
        if any(triple.start() <= fraction.start() < triple.end() for triple in triples):
            continue
        numerator, denominator = fraction.groups()
        permitted = {(stats[key], stats["expected_nights"]) for stats in (output.get("current"), output.get("previous")) if stats for key in ("valid_nights", "detail_nights")}
        if (int(numerator), int(denominator)) not in permitted:
            return "The stated coverage fraction does not match the returned coverage."
    for paragraph in text.splitlines():
        evidence = health_context(paragraph, health_references, answer=text)
        paragraph = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", paragraph)
        for match in QUANTITIES.finditer(paragraph):
            if discourse_quantity(paragraph, match) or product_definition_quantity(paragraph, match, policy_references, evidence_text=text):
                continue
            if supports_measurement(paragraph, match, output, evidence) is False:
                return f"The record quantity '{match.group()}' does not match its field, period or permitted calculation. Correct it using the actual tool result."
    return None
