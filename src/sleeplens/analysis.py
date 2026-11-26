"""Deterministic sleep statistics. No API, generated code, or medical inference."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sleeplens.data import DETAIL_FIELDS, DataQualityError, PROFILE_IDS, SleepDataset, load_dataset, parse_iso_date


SCHEMA_VERSION = "sleep-analysis-v2"
RULE_VERSION = "sleep-rules-v2"
MIN_COMPARISON_NIGHTS = 4  # Product display rule, not a medical/statistical threshold.


def berlin_today() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def _period(start: date, end: date) -> dict:
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def _stats(dataset: SleepDataset, profile_id: str, start: date, scope: str, nights=7):
    index = {r.record_date: r for r in dataset.records if r.profile_id == profile_id}
    daily, values, warnings, detail_records = [], [], [], []
    for offset in range(nights):
        day = start + timedelta(days=offset)
        record = index.get(day)
        if record is None:
            state, valid, minutes = "missing_record", False, None
        else:
            valid, minutes = record.sleep_valid, record.sleep_min
            state = "valid" if valid else "unavailable_record"
        daily.append({"record_date": day.isoformat(), "sleep_min": minutes,
                      "sleep_valid": valid, "record_state": state,
                      **{name: getattr(record, name, None) if valid else None for name in DETAIL_FIELDS}})
        if valid:
            values.append(minutes)
            if all(getattr(record, name, None) is not None for name in DETAIL_FIELDS):
                detail_records.append(record)
            if minutes == 0:
                warnings.append({"code": "zero_value_requires_verification", "period": scope,
                                 "record_date": day.isoformat(),
                                 "message": "A valid zero was retained; verify the record, do not infer that no sleep occurred."})
    count = len(values)
    if count < nights:
        warnings.append({"code": "incomplete_coverage", "period": scope,
                         "message": "The mean describes available records only; missingness may bias the comparison."})
    return ({"expected_nights": nights, "valid_nights": count, "unavailable_nights": nights - count,
             "coverage": count / nights, "mean_sleep_min": sum(values) / count if count else None,
             **detail_statistics(detail_records, nights=nights)},
            daily, warnings)


def detail_statistics(records, *, nights=7):
    """Average local clock times on a waking-date-anchored sleep day.

    Onsets use noon as the day boundary so 23:50 and 00:10 average to 00:00.
    Wake times use midnight. Elapsed durations are validated in UTC upstream.
    """
    count = len(records)
    def clock(field, boundary):
        if not count:
            return None
        offsets = []
        for record in records:
            value = datetime.fromisoformat(getattr(record, field))
            offsets.append((value.hour * 60 + value.minute - boundary) % 1440)
        minute = (int(sum(offsets) / count + .5) + boundary) % 1440
        return f"{minute // 60:02d}:{minute % 60:02d}"
    return {"detail_nights": count, "detail_coverage": count / nights,
            "mean_sleep_onset": clock("sleep_onset", 720), "mean_wake_time": clock("wake_time", 0),
            "total_night_awakenings": sum(r.night_awakenings for r in records) if count else None,
            **{f"mean_{name}": sum(getattr(r, name) for r in records) / count if count else None
               for name in DETAIL_FIELDS[2:]}}


def analyze_sleep(profile_id: str, start_date: str, end_date: str,
                  compare_previous: bool, *, today: date | None = None) -> dict:
    """Read a completed single waking date or analyze seven consecutive dates.

    ``today`` is an internal test clock and is NOT exposed in the model schema.
    Numeric precision is retained here; the CLI/UI controls display rounding.
    """
    current_day = today if today is not None else berlin_today()
    result = {
        "status": "invalid_input", "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION, "dataset_version": None, "synthetic": True,
        "timezone": "Europe/Berlin", "as_of_date": current_day.isoformat(),
        "profile_id": None, "profile_age": None, "period": None, "current": None,
        "previous_period": None, "previous": None, "comparison_state": "not_requested",
        "difference_min": None, "daily_records": {"current": None, "previous": None},
        "warnings": [], "error": None,
    }

    def fail(status: str, code: str, message: str):
        result.update(status=status, error={"code": code, "message": message})
        return result

    if type(profile_id) is not str or profile_id not in PROFILE_IDS:
        return fail("invalid_input", "unknown_profile", "Choose one synthetic profile: P01, P02 or P03.")
    if type(compare_previous) is not bool:
        return fail("invalid_input", "invalid_compare_previous", "compare_previous must be a boolean.")
    try:
        start, end = parse_iso_date(start_date), parse_iso_date(end_date)
    except (ValueError, TypeError):
        return fail("invalid_input", "invalid_date", "Dates must be real calendar dates in YYYY-MM-DD form.")
    nights = (end - start).days + 1
    if nights not in {1, 7}:
        return fail("invalid_input", "invalid_period", "Request a single waking date or exactly seven consecutive dates.")
    if nights == 1 and compare_previous:
        return fail("invalid_input", "single_day_comparison_not_supported", "Single-night lookup does not apply a weekly comparison; set compare_previous=false.")
    try:
        previous_start = start - timedelta(days=7) if compare_previous else None
        previous_end = start - timedelta(days=1) if compare_previous else None
    except OverflowError:
        return fail("invalid_input", "date_out_of_range", "The preceding period exceeds supported calendar dates.")
    result.update(profile_id=profile_id, period=_period(start, end), granularity="day" if nights == 1 else "week")
    if end > current_day:
        # Today's waking date is last night's sleep, which has already ended.
        return fail("unsupported_period", "period_not_finished", "Only periods ending on or before today's waking date can be analyzed.")
    try:
        dataset = load_dataset()
    except DataQualityError as exc:
        failed = fail("data_quality_error", exc.code, str(exc))
        if exc.fields:
            failed["error"]["missing_fields" if exc.missing else "invalid_fields"] = list(exc.fields)
        return failed
    except OSError:
        return fail("tool_error", "dataset_unavailable", "The local dataset could not be read; no statistics were computed.")
    result["dataset_version"] = dataset.version
    result["profile_age"] = next(profile.age for profile in dataset.profiles if profile.profile_id == profile_id)
    available = [row.record_date for row in dataset.records if row.profile_id == profile_id]
    result["available_period"] = _period(min(available), max(available)) if available else None
    current, daily, warnings = _stats(dataset, profile_id, start, "current", nights=nights)
    result.update(current=current, warnings=warnings)
    result["daily_records"]["current"] = daily
    periods = [current]
    if compare_previous:
        previous, previous_daily, previous_warnings = _stats(dataset, profile_id, previous_start, "previous")
        result.update(previous=previous, previous_period=_period(previous_start, previous_end))
        result["daily_records"]["previous"] = previous_daily
        result["warnings"].extend(previous_warnings)
        periods.append(previous)
        if all(p["valid_nights"] >= MIN_COMPARISON_NIGHTS for p in periods):
            result.update(comparison_state="available", difference_min=current["mean_sleep_min"] - previous["mean_sleep_min"])
            result["warnings"].append({"code": "descriptive_comparison_only",
                                       "message": "Recorded duration difference only; not significance, causation, sleep quality or diagnosis."})
        else:
            result["comparison_state"] = "insufficient_data"
            result["warnings"].append({"code": "comparison_requires_four_nights",
                                       "message": "Each period needs at least four valid nights under this product display rule; this is not a medical standard."})
    if all(p["valid_nights"] == 0 for p in periods):
        result["status"] = "no_data"
    elif any(p["valid_nights"] < p["expected_nights"] for p in periods):
        result["status"] = "partial_data"
    else:
        result["status"] = "ok"
    return result
