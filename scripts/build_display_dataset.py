"""Build a reproducible display fixture; parameters are illustrative, not fitted."""

import argparse
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from random import Random
from zoneinfo import ZoneInfo

from sleeplens.data import DETAIL_FIELDS, parse_dataset


OUTPUT = Path(__file__).resolve().parents[1] / "src/sleeplens/fixtures/display_sleep.json"
SEED = 20261124
START = date(2026, 10, 12)
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
# One absent row and two explicitly unavailable records exercise both gap states.
GAPS = {("P02", 2): "unavailable", ("P02", 8): "missing", ("P02", 12): "unavailable"}
# Irregular timing/fragmentation events; no inferred cause is attached to them.
EVENTS = {("P01", 4): (73, 5, 0), ("P01", 10): (19, -8, 31),
          ("P02", 5): (62, 87, 0), ("P02", 9): (68, 12, 16),
          ("P03", 8): (41, -3, 13)}


def build_dataset():
    records = []
    for index, spec in enumerate(PROFILES):
        rng = Random(SEED + 1009 * index)
        drift = 0.0
        for offset in range(14):
            day = START + timedelta(days=offset)
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
                  generation=dict(seed=SEED, method="Individual schedules, correlated timing jitter and irregular events; not fitted to real users."),
                  profiles=[{key: spec[key] for key in ("profile_id", "age", "scenario")} for spec in PROFILES],
                  records=records)
    parse_dataset(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the committed fixture without writing it.")
    args = parser.parse_args()
    content = json.dumps(build_dataset(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            parser.exit(1, "Display fixture does not match the generator.\n")
        print("Display fixture matches the generator and passes data validation.")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
        print(f"Wrote {OUTPUT.name}")


if __name__ == "__main__":
    main()
