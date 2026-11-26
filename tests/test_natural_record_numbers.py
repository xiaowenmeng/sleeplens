"""Natural unit conversions remain grounded in the selected display records."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from streamlit.testing.v1 import AppTest

from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.config import Settings
from sleeplens.answer_validation import validate_record_text
from sleeplens.knowledge import load_knowledge
from sleeplens.record_grounding import QUANTITIES, measurement


WEEK = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-25", compare_previous=True)


@pytest.fixture
def records():
    return analyze_sleep(**WEEK, today=date(2026, 11, 24))


def check(text, records):
    return validate_record_text(text, records, require_summary=False, health_references={})


@pytest.mark.parametrize("text", [
    "Your average was about 7 h 26 min.",
    "Your mean recorded sleep was about 7 hours 26 minutes a night.",
    "平均每晚睡了约7小时26分钟。",
    "平均每晚睡了7小时26.3分钟。",
    "The previous week averaged about 7 hours 17 minutes.",
    "The previous week (12–18 October) averaged about 7 hours 17 minutes.",
    "19–25 October: your mean sleep was about 7 hours 26 minutes.",
    "All seven nights from 19 to 25 October are valid.",
    "Your average sleep was 7.44 hours.",
    "The mean difference from the previous week was 9 minutes.",
    "Your average was about 7 h 26 min, roughly 9 minutes more than the previous week's 7 h 17 min.",
    "The previous week averaged about 7 hours 17 minutes, so this week's mean was roughly 9 minutes longer.",
    "22 October: 5 h 39 min of sleep with 2 awakenings and 49 minutes awake.",
    "22 October: 5 hours 39 minutes of sleep with 49 minutes awake across two awakenings.",
])
def test_supported_rounded_means_and_natural_english_sentences_pass(text, records):
    assert check(text, records) is None


@pytest.mark.parametrize("text", [
    "平均每晚睡了7小时25分钟。",  # Rounding cannot move a full minute.
    "平均每晚睡了7小时26.0分钟。",  # Written decimal precision matters.
    "Your average sleep was 7.43 hours.",
    "The previous week averaged 7 h 26 min.",
    "The previous week (12–17 October) averaged 7 h 17 min.",
    "The mean difference from the previous week was 10 minutes.",
    "Your average was roughly 9 minutes shorter than the previous week.",
    "22 October: 5 hours 39.3 minutes of sleep.",  # Raw minutes stay exact.
    "22 October: 6 hours 42 minutes of sleep.",  # Correct value, wrong date.
    "23 October: 5 hours 39 minutes of sleep.",
    "22 October: 2 awakenings and 48 minutes awake.",
    "22 October: 49 awakenings and 2 minutes awake.",
])
def test_rounding_does_not_allow_wrong_fields_dates_directions_or_precision(text, records):
    assert check(text, records)


def test_counts_and_minutes_are_separate_quantities():
    matches = list(QUANTITIES.finditer("2 awakenings and 49 minutes awake"))
    assert [(m.group(), measurement(m)) for m in matches] == [
        ("2 awakenings", ("count", 2)), ("49 minutes", ("minutes", 49))]


def test_complete_coverage_cannot_be_claimed_for_a_week_with_gaps():
    output = analyze_sleep("P02", "2026-10-19", "2026-10-25", False, today=date(2026, 11, 24))
    assert check("All seven nights from 19 to 25 October are valid.", output)


class Client:
    def __init__(self, answer):
        self.calls = 0
        self.messages = [ChatCompletionMessage(role="assistant", tool_calls=[{
            "id": "records", "type": "function", "function": {
                "name": "analyze_sleep", "arguments": json.dumps(WEEK)}}]),
            ChatCompletionMessage(role="assistant", content=answer),
            ChatCompletionMessage(role="assistant", content=answer)]

    def complete(self, messages, tools, timeout):
        self.calls += 1
        return SimpleNamespace(model="offline-number-check", usage=None, choices=[
            SimpleNamespace(message=self.messages.pop(0), finish_reason="stop")])


def test_weekly_explanation_with_rounded_mean_is_displayed_without_repair():
    answer = ("2026-10-19 to 2026-10-25: your mean sleep was about 7 hours 26 minutes. "
              "The previous week averaged about 7 hours 17 minutes, roughly 9 minutes less.\n\n"
              "22 October was the shortest night: 5 hours 39 minutes of sleep, "
              "with 2 awakenings and 49 minutes awake. The weekly average hides that shorter night.")
    client = Client(answer)
    result = ChatSession(client).ask(
        "Explain the selected sleep records, including coverage and any comparison I selected.", selected_query=WEEK)
    assert result["status"] == "answered" and result["answer"] == answer
    assert not result["answer_validation"]["repairs"]
    assert not result.get("verified_record_facts") and client.calls == 2


def test_a_real_numeric_error_still_falls_back_to_a_compact_record_table():
    client = Client("The mean recorded sleep was 999 minutes.")
    result = ChatSession(client).ask(
        "Explain the selected sleep records, including coverage and any comparison I selected.", selected_query=WEEK)
    assert result["status"] == "needs_review"
    assert "999" not in result["answer"] + result["verified_record_facts"]
    assert "|" in result["verified_record_facts"]
    assert "446.3" in result["verified_record_facts"] and "437.1" in result["verified_record_facts"]
    assert "7/7" in result["verified_record_facts"] and "+9.1" in result["verified_record_facts"]
    assert "could not be verified" not in result["answer"]


def test_health_numbers_keep_their_source_qualifiers_after_record_rounding_is_relaxed(records):
    references = {r["citation_id"]: r["text"] for r in load_knowledge().references if r["source_id"] == "H1"}
    from sleeplens.answer_validation import review_health_text
    assert review_health_text("Adults need at most seven hours of sleep.[H1:AdultDuration]", references,
                              record_output=records).blocking_problem


@pytest.mark.parametrize("valid", [True, False])
def test_web_shows_the_interpretation_or_one_notice_with_a_record_table(monkeypatch, tmp_path, valid):
    monkeypatch.chdir(tmp_path)
    answer = ("Your mean recorded sleep was about 7 hours 26 minutes.\n\n"
              "22 October was the shortest night: 5 hours 39 minutes of sleep, "
              "with 2 awakenings and 49 minutes awake.") if valid else "The mean recorded sleep was 999 minutes."
    client = Client(answer)
    monkeypatch.setattr("sleeplens.dashboard.create_model", lambda: (client, Settings(api_key="offline")))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    app.chat_input[0].set_value("Explain the selected sleep records, including coverage and any comparison I selected.").run()
    assert not app.exception and not app.error
    turn = app.session_state["dashboard"].turns[-1]
    shown = "\n".join(block.value for block in app.markdown)
    if valid:
        assert turn["status"] == "answered" and not app.warning
        assert answer in shown and not turn.get("verified_record_facts")
    else:
        assert turn["status"] == "needs_review" and len(app.warning) == 1
        assert "| Dates |" in shown and "446.3" in shown and "999" not in shown
    assert "unverified interpretation is excluded" not in shown
