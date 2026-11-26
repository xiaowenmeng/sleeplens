"""Write or check the committed display-data snapshot.

The app generates its display data at runtime for the 14 waking dates ending
today (see sleeplens.display_data). This script freezes one such window, ending
on SNAPSHOT_END, so tests and offline checks have fixed, reproducible numbers.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from sleeplens.display_data import build_display_dataset


OUTPUT = Path(__file__).resolve().parents[1] / "src/sleeplens/fixtures/display_sleep.json"
SNAPSHOT_END = date(2026, 11, 26)


def build_dataset():
    return build_display_dataset(SNAPSHOT_END)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the committed snapshot without writing it.")
    args = parser.parse_args()
    content = json.dumps(build_dataset(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            parser.exit(1, "Display snapshot does not match the generator.\n")
        print("Display snapshot matches the generator and passes data validation.")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
        print(f"Wrote {OUTPUT.name}")


if __name__ == "__main__":
    main()
