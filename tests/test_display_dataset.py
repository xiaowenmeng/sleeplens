"""Display data consistency and agreement between browsing and agent tools."""

import json
import runpy
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path
from statistics import pstdev
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from streamlit.testing.v1 import AppTest

from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.dashboard import DashboardSession, chart_rows
from sleeplens.data import PROFILE_IDS, load_dataset
from sleeplens.tools import dispatch_tool


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = files("sleeplens").joinpath("fixtures")


def test_default_uses_display_data_and_regression_file_remains_available():
    assert load_dataset().version == "display-sleep-v1"
    regression = load_dataset(FIXTURES.joinpath("synthetic_sleep.json"))
    assert regression.version == "synthetic-sleep-v2"
    values = [r.sleep_min for r in regression.records if r.profile_id == "P03"]
    assert values == [420] * 14


def test_display_fixture_can_be_reproduced_without_changing_regression_data():
    build = runpy.run_path(str(ROOT / "scripts/build_display_dataset.py"))["build_dataset"]
    committed = json.loads(FIXTURES.joinpath("display_sleep.json").read_text(encoding="utf-8"))
    assert build() == build() == committed


@pytest.mark.parametrize("profile", PROFILE_IDS)
def test_profiles_have_irregular_nightly_values_instead_of_short_repeating_cycles(profile):
    rows = [r for r in load_dataset().records if r.profile_id == profile and r.sleep_valid]
    durations = [r.sleep_min for r in rows]
    onsets = [r.sleep_onset[11:16] for r in rows]
    counts = [r.night_awakenings for r in rows]
    assert len(set(durations)) >= 8 and pstdev(durations) > 7
    assert sum(v % 10 != 0 for v in durations) >= len(durations) // 2
    assert len(set(onsets)) >= 8
    for lag in range(1, 5):
        assert onsets[lag:] != onsets[:-lag]
        assert counts[lag:] != counts[:-lag]


def test_stage_totals_and_elapsed_time_stay_consistent_including_clock_change():
    rows = [r for r in load_dataset().records if r.sleep_valid]
    offsets = set()
    for row in rows:
        onset, wake = map(datetime.fromisoformat, (row.sleep_onset, row.wake_time))
        offsets.add(wake.utcoffset())
        assert wake.date() == row.record_date
        assert row.deep_sleep_min + row.light_sleep_min + row.rem_sleep_min == row.sleep_min
        elapsed = (wake.astimezone(timezone.utc) - onset.astimezone(timezone.utc)).total_seconds() / 60
        assert elapsed == row.sleep_min + row.awake_min
        assert (row.night_awakenings == 0) == (row.awake_min == 0)
    assert len(offsets) == 2  # October 25 crosses Berlin's autumn clock change.


def test_browsing_and_tool_queries_use_identical_display_records_and_gap_states():
    view = DashboardSession()
    output = view.apply_selection("P02", "2026-10-19", True)
    tool_output = dispatch_tool("analyze_sleep", view.selection)
    assert output == tool_output
    assert output["dataset_version"] == "display-sleep-v1"
    assert output["status"] == "partial_data"
    assert output["current"]["valid_nights"] == 5
    assert output["previous"]["valid_nights"] == 6
    current = output["daily_records"]["current"]
    assert current[1]["record_state"] == "missing_record"
    assert current[5]["record_state"] == "unavailable_record"
    values = [r["sleep_min"] for r in current if r["sleep_valid"]]
    assert output["current"]["mean_sleep_min"] == sum(values) / len(values)
    assert output["comparison_state"] == "available"
    assert [r["minutes"] for r in chart_rows(output) if r["period"] == "current"].count(None) == 2


def test_single_day_gaps_are_not_zero_sleep():
    for day in ("2026-10-20", "2026-10-24"):
        result = analyze_sleep("P02", day, day, False, today=date(2026, 11, 24))
        assert result["status"] == "no_data"
        assert result["current"]["mean_sleep_min"] is None
        assert result["daily_records"]["current"][0]["sleep_min"] is None


def test_agent_answers_from_the_same_display_data_as_the_dashboard():
    query = dict(profile_id="P03", start_date="2026-10-20", end_date="2026-10-20", compare_previous=False)
    view = DashboardSession()
    record = view.apply_selection("P03", "2026-10-20", False, days=1)["daily_records"]["current"][0]
    messages = [ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "record", "type": "function", "function": {
            "name": "analyze_sleep", "arguments": json.dumps(query)}}]),
        ChatCompletionMessage(role="assistant", content=f"这晚夜醒{record['night_awakenings']}次。")]

    class Client:
        def complete(self, messages_in, tools, timeout):
            return SimpleNamespace(model="offline-display-check", usage=None, choices=[
                SimpleNamespace(message=messages.pop(0), finish_reason="stop")])

    result = ChatSession(Client()).ask("P03在2026-10-20醒了几次？", selected_query=query)
    assert result["status"] == "answered"
    evidence = result["tool_events"][0]["result"]
    assert evidence["dataset_version"] == "display-sleep-v1"
    assert evidence["daily_records"]["current"][0] == record


def test_web_opens_on_display_data_without_initializing_a_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def forbidden():
        raise AssertionError("Browsing records must not initialize a model")

    monkeypatch.setattr("sleeplens.dashboard.create_model", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    assert not app.exception and not app.error
    assert app.session_state["dashboard"].analysis["dataset_version"] == "display-sleep-v1"
