"""Rolling synthetic display data: always the 14 waking dates ending today.

The records are generated, not stored, so the demonstration never goes stale.
Generation is deterministic for a given end date: every page, tool call and
answer on the same Berlin day sees identical records. When the day changes, the
whole window slides forward, so the numbers shown for a particular calendar
date can differ from one day to the next. Parameters are illustrative, not
fitted to real users.
"""

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from random import Random
from zoneinfo import ZoneInfo

from sleeplens.data import DETAIL_FIELDS, SleepDataset, parse_dataset


SEED = 20261124
WINDOW_NIGHTS = 14
BERLIN = ZoneInfo("Europe/Berlin")
PROFILES = (
    # Onset minutes are measured from midnight before the waking date.
    dict(profile_id="P01", age=28, onset=23 * 60 + 35, wake=7 * 60 + 5,
         jitter=19, weekend=46, awakenings=(2, 5, 3, 1), deep=.19, rem=.23,
         scenario="Variable timing with occasional shorter nights."),
    dict(profile_id="P02", age=35, onset=24 * 60 + 5, wake=7 * 60 + 40,
         jitter=29, weekend=67, awakenings=(1, 3, 4, 2), deep=.17, rem=.24,
         scenario="Later, more variable timing with three scattered record gaps."),
    dict(profile_id="P03", age=42, onset=22 * 60 + 55, wake=6 * 60 + 50,
         jitter=12, weekend=23, awakenings=(3, 5, 2, 1), deep=.18, rem=.22,
         scenario="Relatively steady timing with ordinary variation and an occasional shorter night."),
)
# Positions within the 14-night window (0 = oldest). One absent row and two
# explicitly unavailable records exercise both gap states.
GAPS = {("P02", 2): "unavailable", ("P02", 8): "missing", ("P02", 12): "unavailable"}
# Irregular timing/fragmentation events; no inferred cause is attached to them.
EVENTS = {("P01", 4): (73, 5, 0), ("P01", 10): (19, -8, 31),
          ("P02", 5): (62, 87, 0), ("P02", 9): (68, 12, 16),
          ("P03", 8): (41, -3, 13)}


def display_end_date() -> date:
    """The newest waking date in the display data: today in Europe/Berlin."""
    return datetime.now(BERLIN).date()


def build_display_dataset(end_date: date) -> dict:
    """Raw dataset JSON for the WINDOW_NIGHTS waking dates ending on end_date."""
    start = end_date - timedelta(days=WINDOW_NIGHTS - 1)
    records = []
    for index, spec in enumerate(PROFILES):
        rng = Random(SEED + 1009 * index)
        drift = 0.0
        for offset in range(WINDOW_NIGHTS):
            day = start + timedelta(days=offset)
            # Shared timing drift ties onset and waking together across nearby nights.
            drift = .45 * drift + rng.gauss(0, spec["jitter"] * .55)
            weekend = spec["weekend"] if day.weekday() >= 5 else 0
            onset_min = spec["onset"] + drift + rng.gauss(0, spec["jitter"]) + .65 * weekend
            wake_min = spec["wake"] + .45 * drift + rng.gauss(0, spec["jitter"] * .65) + weekend
            if spec["profile_id"] == "P01" and offset >= 7:
                onset_min += 17
            later, extra_sleep_opportunity, extra_awake = EVENTS.get((spec["profile_id"], offset), (0, 0, 0))
            onset = datetime.combine(day - timedelta(days=1), time(), BERLIN) + timedelta(minutes=round(onset_min + later))
            wake = datetime.combine(day, time(), BERLIN) + timedelta(minutes=round(wake_min + extra_sleep_opportunity))
            count = rng.choices(range(4), weights=spec["awakenings"])[0]
            if extra_awake:
                count = max(count, 2)
            awake = sum(max(1, round(rng.gammavariate(2.0, 3.2))) for _ in range(count)) + extra_awake
            elapsed = round((wake.astimezone(timezone.utc) - onset.astimezone(timezone.utc)).total_seconds() / 60)
            minutes = elapsed - awake
            deep = round(minutes * min(.27, max(.11, rng.gauss(spec["deep"], .026))))
            rem = round(minutes * min(.32, max(.15, rng.gauss(spec["rem"], .031))))
            row = dict(profile_id=spec["profile_id"], record_date=day.isoformat(),
                       sleep_min=minutes, sleep_valid=True, sleep_onset=onset.isoformat(),
                       wake_time=wake.isoformat(), night_awakenings=count, awake_min=awake,
                       deep_sleep_min=deep, light_sleep_min=minutes - deep - rem, rem_sleep_min=rem)
            gap = GAPS.get((spec["profile_id"], offset))
            if gap == "missing":
                continue
            if gap == "unavailable":
                row.update(sleep_min=None, sleep_valid=False, **dict.fromkeys(DETAIL_FIELDS))
            records.append(row)
    result = dict(dataset_version="display-sleep-v1", synthetic=True, timezone="Europe/Berlin",
                  generation=dict(seed=SEED, window_end=end_date.isoformat(), window_nights=WINDOW_NIGHTS,
                                  method="Individual schedules, correlated timing jitter and irregular events; "
                                         "a rolling window ending on the current Berlin date; not fitted to real users."),
                  profiles=[{key: spec[key] for key in ("profile_id", "age", "scenario")} for spec in PROFILES],
                  records=records)
    parse_dataset(result)
    return result


@lru_cache(maxsize=4)
def rolling_dataset(end_date: date) -> SleepDataset:
    """Validated display dataset for one end date (cached; records are immutable)."""
    return parse_dataset(build_display_dataset(end_date))
