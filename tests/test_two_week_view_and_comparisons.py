"""The 14-day record view, and week comparisons asked in everyday wording."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from streamlit.testing.v1 import AppTest

from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.dashboard import DashboardSession
from sleeplens.query_policy import plan_query


TODAY = date(2026, 11, 26)  # Matches the pinned display window end in conftest.
WEEK = dict(profile_id="P01", start_date="2026-11-20", end_date="2026-11-26", compare_previous=False)
TWO_WEEKS = dict(profile_id="P01", start_date="2026-11-13", end_date="2026-11-26", compare_previous=False)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    for module in ("sleeplens.analysis", "sleeplens.agent", "sleeplens.web"):
        monkeypatch.setattr(module + ".berlin_today", lambda: TODAY)


class Client:
    """Scripted model: one analyze_sleep call, then an answer using the summary token."""

    def __init__(self, query):
        self.messages = [
            ChatCompletionMessage(role="assistant", tool_calls=[{
                "id": "records", "type": "function", "function": {
                    "name": "analyze_sleep", "arguments": json.dumps(query)}}]),
            ChatCompletionMessage(role="assistant", content="{{sleep_summary}}")]

    def complete(self, messages, tools, timeout):
        return SimpleNamespace(model="offline-two-weeks", usage=None, choices=[
            SimpleNamespace(message=self.messages.pop(0), finish_reason="stop")])


@pytest.mark.parametrize("question", [
    "Did I sleep more or less than the previous week? By how much?",
    "Did I sleep more than last week?",
    "Did I sleep less than the week before?",
    "Was my sleep longer or shorter than the prior week?",
    "This week vs last week?",
    "Am I sleeping better than last week?",
    "How much more did I sleep than the previous week?",
    "How does this week compare to last week?",
    "我比上周睡得多还是少？",
    "跟上周比怎么样？",
])
def test_everyday_week_comparisons_are_record_lookups_of_the_selected_week(question):
    # These used to be classified as chat, so the model was never asked to
    # look up records and answered as if none existed.
    plan = plan_query(question, today=TODAY, selected_query={**WEEK, "compare_previous": False})
    assert plan.task in {"records", "combined"} and plan.compare_previous is True
    assert plan.period is None  # The selected week, not last calendar week.


def test_last_week_as_the_subject_is_still_last_week():
    plan = plan_query("How was last week compared with the week before?", today=TODAY)
    assert plan.period == ("2026-11-16", "2026-11-22") and plan.compare_previous is True


def test_comparison_question_is_answered_from_both_weeks():
    question = "Did I sleep more or less than the previous week? By how much?"
    result = ChatSession(Client({**WEEK, "compare_previous": True})).ask(question, selected_query=WEEK)
    assert result["status"] == "answered"
    assert result["answer"].startswith("You slept more than the previous week: 0.6 minutes more per night")
    assert "preceding seven nights" in result["answer"]


def test_fourteen_day_lookup_covers_the_whole_window():
    output = analyze_sleep("P02", "2026-11-13", "2026-11-26", False)
    assert output["status"] == "partial_data" and output["granularity"] == "two_weeks"
    assert output["current"]["expected_nights"] == 14 and output["current"]["valid_nights"] == 11
    assert len(output["daily_records"]["current"]) == 14


def test_fourteen_day_lookup_does_not_compare_with_an_empty_earlier_window():
    output = analyze_sleep("P01", "2026-11-13", "2026-11-26", True)
    assert output["error"]["code"] == "two_week_comparison_not_supported"


def test_dashboard_fourteen_day_selection_turns_comparison_off():
    view = DashboardSession()
    output = view.apply_selection("P01", "2026-11-13", True, days=14)
    assert output["status"] == "ok" and output["current"]["expected_nights"] == 14
    assert view.selection == TWO_WEEKS


def test_summary_of_a_two_week_selection_reports_all_fourteen_nights():
    # Even if the model asks for a comparison, a 14-day lookup runs without one.
    result = ChatSession(Client({**TWO_WEEKS, "compare_previous": True})).ask(
        "How did I sleep over these two weeks?", selected_query=TWO_WEEKS)
    assert result["status"] == "answered"
    assert "The 14 nights you selected (2026-11-13—2026-11-26): 14/14 recorded nights" in result["answer"]


def test_comparison_while_viewing_two_weeks_compares_its_two_weeks():
    question = "Did I sleep more or less than the previous week?"
    plan = plan_query(question, today=TODAY, selected_query=TWO_WEEKS)
    assert plan.period == ("2026-11-20", "2026-11-26") and plan.compare_previous is True
    result = ChatSession(Client({**WEEK, "compare_previous": True})).ask(question, selected_query=TWO_WEEKS)
    assert result["status"] == "answered"
    assert "(2026-11-20—2026-11-26)" in result["answer"] and result["answer"].startswith("You slept more")


@pytest.mark.parametrize("question", ["How did I sleep over the past two weeks?", "最近两周睡得怎么样？",
                                      "Show 2026-11-13 to 2026-11-26."])
def test_two_week_phrasing_and_ranges_resolve_to_fourteen_days(question):
    assert plan_query(question, today=TODAY).period == ("2026-11-13", "2026-11-26")


def test_sidebar_offers_fourteen_days_and_disables_comparison(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    span = app.selectbox(key="record_span")
    assert span.options == ["Seven days", "Fourteen days", "One day"]
    span.set_value(14).run()
    assert app.checkbox(key="record_compare").disabled
    app.date_input(key="record_start").set_value(date(2026, 11, 13))
    app.button(key="apply_selection").click().run()
    assert not app.exception
    view = app.session_state["dashboard"]
    assert view.selection == TWO_WEEKS
    assert view.analysis["current"]["expected_nights"] == 14
    cards = {metric.label: metric.value for metric in app.metric}
    assert cards["Valid nights"] == "14/14" and cards["Change vs previous"] == "Not applicable"


# --- The comparison answer says "more", "less" or "the same" up front. ---

def _week_result(delta, previous_nights=7):
    from copy import deepcopy
    output = deepcopy(analyze_sleep(**{**WEEK, "compare_previous": True}))
    output["difference_min"] = delta
    output["previous"]["valid_nights"] = previous_nights
    return output


@pytest.mark.parametrize("delta, english, chinese", [
    (17.6, "You slept more than the previous week: 17.6 minutes more per night on average.", "比前一周睡得多：平均每晚多17.6分钟。"),
    (-17.6, "You slept less than the previous week: 17.6 minutes less per night on average.", "比前一周睡得少：平均每晚少17.6分钟。"),
    (0.02, "You slept the same amount per night as the previous week, on average.", "两周平均每晚的睡眠时长相同。"),
    (None, "I can't tell whether you slept more or less than the previous week", "还不能判断比前一周睡得多还是少"),
])
def test_comparison_answer_leads_with_the_direction(delta, english, chinese):
    from sleeplens.answer_validation import record_summary
    output = _week_result(delta, previous_nights=7 if delta is not None else 1)
    assert record_summary(output, "English", lead_with_change=True).startswith(english)
    assert record_summary(output, "Chinese", lead_with_change=True).startswith(chinese)


def test_plain_english_summary_states_direction_instead_of_a_signed_number():
    from sleeplens.answer_validation import record_summary
    text = record_summary(_week_result(-17.6), "English")
    assert "17.6 minutes less per night than the preceding seven nights" in text and "-17.6" not in text


def test_model_is_told_to_answer_more_or_less_first():
    from sleeplens.response_planning import build_response_plan
    question = "did i sleep more or less than last week"
    plan = build_response_plan(question, plan_query(question, today=TODAY, selected_query=WEEK), WEEK)
    assert "direction_and_amount" in plan["requirements"]
    assert "more, less, or the same" in plan["comparison_goal"]
