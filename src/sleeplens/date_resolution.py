"""Resolve explicit waking dates before applying page-period defaults."""
import re
from datetime import date, timedelta


def explicit_period(question, *, today, selection=None, previous=None):
    """Return (period, source, error); never fall back after an invalid date.

    An omitted year uses a confirmed/page period's year, then today's year.
    A month/day within a cross-year selected period uses that actual year.
    """
    selection = selection if isinstance(selection, dict) else {}
    previous = previous or {}
    reference = previous.get("resolved_period") or [selection.get("start_date"), selection.get("end_date")]
    anchors = []
    for value in reference:
        try:
            anchors.append(date.fromisoformat(value))
        except (TypeError, ValueError):
            pass
    years = sorted({anchor.year for anchor in anchors}) or [today.year]
    default_year = anchors[0].year if anchors else today.year
    matches = []
    full = r"(?<!\d)(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*(?:日|号)?(?!\d)"
    for match in re.finditer(full, question):
        matches.append((match.start(), match.end(), tuple(map(int, match.groups())), "explicit_year"))
    short = r"(?<![\d./-])(\d{1,2})\s*[./月]\s*(\d{1,2})\s*(日|号)?(?!\d)"
    for match in re.finditer(short, question):
        if any(start <= match.start() < end for start, end, *_ in matches):
            continue
        after = question[match.end():]
        if re.match(r"\s*(?:次|分钟|小时|%|percent|hours?|minutes?)", after, re.I):
            continue  # A measured quantity such as 1.3 awakenings is not a date.
        if not match.group(3) and not (match.start() == 0 or re.search(r"查|看|日期|记录|这天|那天", question[:match.start()])):
            continue
        month, day = map(int, match.groups()[:2])
        candidates = []
        for year in years:
            try:
                candidate = date(year, month, day)
                if anchors and min(anchors) <= candidate <= max(anchors):
                    candidates.append(candidate)
            except ValueError:
                pass
        year = candidates[0].year if len(candidates) == 1 else default_year
        matches.append((match.start(), match.end(), (year, month, day), "context_year" if anchors else "current_year"))
    if not matches:
        if re.search(r"今晚|今夜|今天晚上|\btonight\b|\bthis evening\b", question, re.I):
            day = today + timedelta(days=1)
            return (day.isoformat(), day.isoformat()), "tonight_waking_date", None
        # A night belongs to the date of waking. "The night before last" ended
        # yesterday morning. Check it before "yesterday"/"last night".
        if re.search(r"(?<![以之提睡目先])前天|\bthe night before last\b|\bday before yesterday\b", question, re.I):
            day = today - timedelta(days=1)
            return (day.isoformat(), day.isoformat()), "night_before_last_waking_date", None
        if re.search(r"昨晚|昨天晚上|昨夜|last night", question, re.I):
            return (today.isoformat(), today.isoformat()), "last_night_waking_date", None
        # For sleep, "yesterday" means the night that started yesterday
        # evening, i.e. the one the user woke from this morning.
        if re.search(r"昨天|昨日|yesterday", question, re.I):
            return (today.isoformat(), today.isoformat()), "yesterday", None
        if re.search(r"(?<!\d)\d{1,2}\s*(?:日|号)(?!\d)", question):
            return None, "day_without_month", "missing_month"
        return None, None, None
    matches.sort()
    try:
        days = [date(*parts) for _, _, parts, _ in matches]
    except ValueError:
        return None, "explicit_date", "invalid_date"
    if len(days) > 2:
        return None, "explicit_date", "multiple_dates"
    if len(days) == 1:
        day = days[0]
        tail = question[matches[0][1]:]
        abbreviated_end = re.match(r"\s*(?:到|至|—|–|~|-)\s*(\d{1,2})\s*(?:日|号)?(?!\d)", tail)
        if abbreviated_end:
            try:
                end = date(day.year, day.month, int(abbreviated_end.group(1)))
            except ValueError:
                return None, "explicit_date_range", "invalid_date"
            if (end - day).days not in {0, 6, 13}:
                return None, "explicit_date_range", "unsupported_range"
            return (day.isoformat(), end.isoformat()), "explicit_date_range", None
        # With an explicit evening, the associated waking date is next day.
        if re.match(r"\s*(?:的)?(?:晚上|当晚|夜里)", tail):
            try:
                day += timedelta(days=1)
            except OverflowError:
                return None, "explicit_date", "invalid_date"
            source = "explicit_sleep_evening"
        else:
            source = matches[0][3]
        return (day.isoformat(), day.isoformat()), source, None
    if (days[1] - days[0]).days not in {0, 6, 13}:
        return None, "explicit_date_range", "unsupported_range"
    return tuple(day.isoformat() for day in days), "explicit_date_range", None
