"""Relative night references and the rolling display window that ends today."""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage

from sleeplens import display_data
from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.data import load_dataset
from sleeplens.onboarding import data_catalogue
from sleeplens.query_policy import plan_query
from sleeplens.reply_policy import unavailable_period_reply


TODAY = date(2026, 11, 26)  # Matches the pinned display window end in conftest.


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: TODAY)
    monkeypatch.setattr("sleeplens.analysis.berlin_today", lambda: TODAY)


class Client:
    """Scripted model: one analyze_sleep call, then a fixed answer."""

    def __init__(self, query, answer):
        self.messages = [
            ChatCompletionMessage(role="assistant", tool_calls=[{
                "id": "records", "type": "function", "function": {
                    "name": "analyze_sleep", "arguments": json.dumps(query)}}]),
            ChatCompletionMessage(role="assistant", content=answer)]

    def complete(self, messages, tools, timeout):
        return SimpleNamespace(model="offline-relative-dates", usage=None, choices=[
            SimpleNamespace(message=self.messages.pop(0), finish_reason="stop")])


@pytest.mark.parametrize("question", [
    "P01昨晚睡了多久？", "P01昨天晚上睡了多久？", "P01昨天睡了多久？",
    "How long did P01 sleep last night?", "How did P01 sleep yesterday?",
])
def test_last_night_and_yesterday_both_mean_the_night_ending_this_morning(question):
    assert plan_query(question, today=TODAY).period == ("2026-11-26", "2026-11-26")


@pytest.mark.parametrize("question", ["P01前天睡了多久？", "P01前天晚上睡得怎样？",
                                      "How did P01 sleep the night before last?"])
def test_night_before_last_is_yesterdays_waking_date(question):
    assert plan_query(question, today=TODAY).period == ("2026-11-25", "2026-11-25")


@pytest.mark.parametrize("question", ["我以前天天失眠，有什么建议？", "睡前晚上玩手机会影响睡眠吗？"])
def test_words_containing_qian_tian_or_qian_wan_are_not_dates(question):
    assert plan_query(question, today=TODAY).period is None


def test_last_night_is_looked_up_and_answered():
    query = dict(profile_id="P01", start_date="2026-11-26", end_date="2026-11-26", compare_previous=False)
    minutes = analyze_sleep(**query)["daily_records"]["current"][0]["sleep_min"]
    hours, rest = divmod(minutes, 60)
    answer = f"昨晚睡了{hours}小时{rest}分钟。"
    result = ChatSession(Client(query, answer)).ask("P01昨晚睡了多久？")
    assert result["status"] == "answered" and result["answer"] == answer
    assert result["tool_events"][0]["result"]["status"] == "ok"


def test_today_is_queryable_but_tomorrow_is_not():
    query = dict(profile_id="P01", compare_previous=False)
    assert analyze_sleep(**query, start_date="2026-11-26", end_date="2026-11-26")["status"] == "ok"
    tomorrow = analyze_sleep(**query, start_date="2026-11-27", end_date="2026-11-27")
    assert tomorrow["error"]["code"] == "period_not_finished"
    reply = unavailable_period_reply(("2026-11-27", "2026-11-27"), TODAY, "English")
    assert "2026-11-26" in reply and "last night" in reply


def test_past_seven_days_include_last_night():
    assert plan_query("我最近七天平均睡多久？", today=TODAY).period == ("2026-11-20", "2026-11-26")


def test_catalogue_and_default_view_reach_last_night():
    info = data_catalogue("P01", today=TODAY)
    assert info["queryable_end"] == "2026-11-26"


@pytest.mark.parametrize("end", [date(2026, 11, 26), date(2027, 3, 31), date(2028, 2, 29)])
def test_rolling_window_always_covers_the_14_nights_ending_on_its_end_date(end):
    dataset = display_data.rolling_dataset(end)
    days = sorted({r.record_date for r in dataset.records})
    # P02 has one absent row, but the window bounds are the same for every profile.
    assert days[-1] == end and days[0] == end - timedelta(days=13)
    assert display_data.build_display_dataset(end) == display_data.build_display_dataset(end)


def test_default_dataset_follows_the_current_date(monkeypatch):
    monkeypatch.setattr("sleeplens.display_data.display_end_date", lambda: date(2027, 1, 10))
    days = {r.record_date for r in load_dataset().records}
    assert max(days) == date(2027, 1, 10) and min(days) == date(2026, 12, 28)


def test_committed_snapshot_is_the_window_ending_on_its_recorded_date():
    from importlib.resources import files
    raw = json.loads(files("sleeplens").joinpath("fixtures/display_sleep.json").read_text(encoding="utf-8"))
    end = date.fromisoformat(raw["generation"]["window_end"])
    assert raw == display_data.build_display_dataset(end)


def test_open_page_moves_to_the_new_window_when_the_date_changes(monkeypatch, tmp_path):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    monkeypatch.chdir(tmp_path)
    clock = {"today": TODAY}
    for module in ("sleeplens.analysis", "sleeplens.agent", "sleeplens.web"):
        monkeypatch.setattr(module + ".berlin_today", lambda: clock["today"])
    monkeypatch.setattr("sleeplens.display_data.display_end_date", lambda: clock["today"])
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert app.session_state["dashboard"].selection["end_date"] == "2026-11-26"
    clock["today"] = TODAY + timedelta(days=1)  # Midnight passes while the page is open.
    app.run()
    assert not app.exception
    assert app.session_state["dashboard"].selection["end_date"] == "2026-11-27"
    assert app.session_state["data_window_end"] == "2026-11-27"


@pytest.mark.parametrize("year", range(2026, 2033))
def test_every_window_around_berlin_clock_changes_is_valid(year):
    # Late bedtimes once fell in the hour skipped at the spring change, which
    # made the whole dataset fail validation on two days a year.
    for start in (date(year, 3, 20), date(year, 10, 20)):
        for offset in range(30):
            display_data.build_display_dataset(start + timedelta(days=offset))  # Raises if invalid.
