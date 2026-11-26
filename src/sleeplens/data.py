"""Strict, read-only loading of the public synthetic demonstration dataset."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path


PROFILE_IDS = ("P01", "P02", "P03")
DETAIL_FIELDS = ("sleep_onset", "wake_time", "night_awakenings", "awake_min",
                 "deep_sleep_min", "light_sleep_min", "rem_sleep_min")


class DataQualityError(ValueError):
    """A safe error with a stable code; no raw file contents or paths."""

    def __init__(self, code: str, message: str, *, fields=(), missing=False):
        super().__init__(message)
        self.code = code
        self.fields = tuple(fields)
        self.missing = missing


@dataclass(frozen=True)
class SleepRecord:
    profile_id: str
    record_date: date
    sleep_min: int | None
    sleep_valid: bool
    sleep_onset: str | None = None
    wake_time: str | None = None
    night_awakenings: int | None = None
    awake_min: int | None = None
    deep_sleep_min: int | None = None
    light_sleep_min: int | None = None
    rem_sleep_min: int | None = None


@dataclass(frozen=True)
class SleepProfile:
    profile_id: str
    age: int
    name: str | None = None
    scenario: str | None = None


@dataclass(frozen=True)
class SleepDataset:
    version: str
    records: tuple[SleepRecord, ...]
    profiles: tuple[SleepProfile, ...]
    generation: dict | None = None


def parse_iso_date(value: str) -> date:
    """Accept only a real calendar date in the exact YYYY-MM-DD form."""
    if type(value) is not str or len(value) != 10:
        raise ValueError("Expected YYYY-MM-DD.")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Expected YYYY-MM-DD.")
    return parsed


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise DataQualityError("duplicate_field", "Dataset JSON contains duplicate fields.")
        result[name] = value
    return result


def load_dataset(path: Path | None = None) -> SleepDataset:
    """Browsing and agent tools share the default: the rolling display window.

    A path loads a fixed JSON file instead, such as the regression fixture or
    the committed display snapshot used by offline checks.
    """
    if path is None:
        from sleeplens.display_data import display_end_date, rolling_dataset
        return rolling_dataset(display_end_date())
    resource = path
    try:
        raw = json.loads(resource.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeError):
        raise DataQualityError("invalid_json", "The dataset is not readable JSON.") from None
    return parse_dataset(raw)


def parse_dataset(raw: dict) -> SleepDataset:
    """Validate the entire file, including data outside the requested window."""
    if not isinstance(raw, dict) or raw.get("synthetic") is not True:
        raise DataQualityError("invalid_metadata", "A declared synthetic dataset is required.")
    if raw.get("timezone", "Europe/Berlin") != "Europe/Berlin":
        raise DataQualityError("invalid_metadata", "This dataset uses Europe/Berlin local dates and offsets.")
    version = raw.get("dataset_version")
    if type(version) is not str or not version.strip():
        raise DataQualityError("invalid_metadata", "A dataset version is required.")
    profiles = raw.get("profiles")
    if not isinstance(profiles, list) or len(profiles) != len(PROFILE_IDS):
        raise DataQualityError("invalid_profiles", "The three demo profiles are required.")
    seen_profiles = set()
    parsed_profiles = []
    for profile in profiles:
        if not isinstance(profile, dict):
            raise DataQualityError("invalid_profiles", "Invalid demo profile metadata.")
        profile_id, age = profile.get("profile_id"), profile.get("age")
        if (type(profile_id) is not str or profile_id not in PROFILE_IDS
                or profile_id in seen_profiles or type(age) is not int or not 18 <= age <= 60):
            raise DataQualityError("invalid_profiles", "Invalid or duplicate adult demo profile.")
        seen_profiles.add(profile_id)
        parsed_profiles.append(SleepProfile(profile_id=profile_id, age=age,
            name=profile.get("name") if isinstance(profile.get("name"), str) else None,
            scenario=profile.get("scenario") if isinstance(profile.get("scenario"), str) else None))
    records = raw.get("records")
    if not isinstance(records, list):
        raise DataQualityError("invalid_records", "Dataset records must be a list.")
    parsed, seen = [], set()
    for record in records:
        core = {"profile_id", "record_date", "sleep_min", "sleep_valid"}
        if not isinstance(record, dict) or set(record) not in (core, core | set(DETAIL_FIELDS)):
            if isinstance(record, dict) and set(record) < core | set(DETAIL_FIELDS):
                required = core | (set(DETAIL_FIELDS) if set(record) & set(DETAIL_FIELDS) else set())
                missing = tuple(sorted(required - set(record)))
                if missing:
                    raise DataQualityError("missing_record_fields", "Required record fields are missing.", fields=missing, missing=True)
            raise DataQualityError("invalid_record_fields", "A record has missing or extra fields.")
        profile_id = record["profile_id"]
        if type(profile_id) is not str or profile_id not in PROFILE_IDS:
            raise DataQualityError("unknown_record_profile", "A record refers to an unknown profile.")
        try:
            record_date = parse_iso_date(record["record_date"])
        except (ValueError, TypeError):
            raise DataQualityError("invalid_record_date", "A record has an invalid calendar date.") from None
        identity = (profile_id, record_date)
        if identity in seen:
            raise DataQualityError("duplicate_record", "Duplicate profile/date records are not allowed.")
        seen.add(identity)
        valid, minutes = record["sleep_valid"], record["sleep_min"]
        if type(valid) is not bool:
            raise DataQualityError("invalid_validity_flag", "sleep_valid must be a boolean.")
        if valid and minutes is None:
            raise DataQualityError("missing_sleep_minutes", "Valid records require sleep minutes.", fields=("sleep_min",), missing=True)
        if valid and (type(minutes) is not int or not 0 <= minutes <= 1440):
            raise DataQualityError("invalid_sleep_minutes", "Valid records require integer minutes from 0 to 1440.", fields=("sleep_min",))
        if not valid and minutes is not None:
            raise DataQualityError("conflicting_validity", "Unavailable records must have null minutes.")
        details = {name: record.get(name) for name in DETAIL_FIELDS}
        if set(DETAIL_FIELDS) <= set(record):
            validate_details(details, minutes, valid, record_date)
        parsed.append(SleepRecord(profile_id, record_date, minutes, valid, **details))
    return SleepDataset(version=version, records=tuple(parsed), profiles=tuple(parsed_profiles),
                        generation=dict(raw["generation"]) if isinstance(raw.get("generation"), dict) else None)


def validate_details(details, minutes, valid, record_date):
    """Extended nights are complete or entirely null; legacy rows remain valid."""
    if all(value is None for value in details.values()):
        return
    if not valid:
        raise DataQualityError("invalid_sleep_details", "Sleep details must be complete on a valid night, or all null.")
    if any(value is None for value in details.values()):
        raise DataQualityError("incomplete_sleep_details", "Sleep details must be complete or all null.",
                               fields=tuple(name for name, value in details.items() if value is None), missing=True)
    for name in DETAIL_FIELDS[2:]:
        value = details[name]
        if type(value) is not int or value < 0 or value > 1440:
            raise DataQualityError("invalid_sleep_details", "Sleep detail counts and minutes must be nonnegative integers.", fields=(name,))
    if sum(details[name] for name in ("deep_sleep_min", "light_sleep_min", "rem_sleep_min")) != minutes:
        raise DataQualityError("invalid_sleep_stages", "Deep, light and REM minutes must sum to recorded sleep minutes.")
    if (details["night_awakenings"] == 0) != (details["awake_min"] == 0) or details["night_awakenings"] > details["awake_min"]:
        raise DataQualityError("invalid_awakenings", "Awakenings and awake minutes must be consistent at minute resolution.")
    try:
        times = [datetime.fromisoformat(details[name]) for name in ("sleep_onset", "wake_time")]
        berlin = ZoneInfo("Europe/Berlin")
        for value in times:
            if value.tzinfo is None or value.second or value.microsecond:
                raise ValueError
            local = value.astimezone(berlin)
            if local.replace(tzinfo=None) != value.replace(tzinfo=None) or local.utcoffset() != value.utcoffset():
                raise ValueError
        onset, wake = times
        elapsed = (wake.astimezone(timezone.utc) - onset.astimezone(timezone.utc)).total_seconds() / 60
        if wake.date() != record_date or not 0 <= elapsed <= 1440 or elapsed != minutes + details["awake_min"]:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise DataQualityError("invalid_sleep_timestamps", "Timestamps must match Berlin offsets, waking date and sleep plus awake minutes.") from None
