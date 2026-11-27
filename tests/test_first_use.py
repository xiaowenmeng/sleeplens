"""First-use copy, actual coverage and opt-in example submission stay offline."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from sleeplens.analysis import analyze_sleep
from sleeplens.query_policy import plan_query
from sleeplens.data import PROFILE_IDS


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("profile", PROFILE_IDS)
def test_catalogue_matches_raw_dates_validity_and_missing_dates(profile):
    from sleeplens.onboarding import data_catalogue

    raw = json.loads((ROOT / "src/sleeplens/fixtures/display_sleep.json").read_text(encoding="utf-8"))
    rows = [r for r in raw["records"] if r["profile_id"] == profile]
    days = {date.fromisoformat(r["record_date"]) for r in rows}
    all_days = {min(days) + timedelta(days=i) for i in range((max(days) - min(days)).days + 1)}
    info = data_catalogue(profile, today=date(2026, 12, 27))
    assert info["status"] == "ok"
    assert info["record_rows"] == len(rows) and info["unique_dates"] == len(days)
    assert info["missing_dates"] == sorted(d.isoformat() for d in all_days - days)
    assert info["unavailable_dates"] == sorted(r["record_date"] for r in rows if not r["sleep_valid"])
    assert info["valid_nights"] == sum(r["sleep_valid"] for r in rows)
    assert info["incomplete_dates"] == [] and info["duplicate_dates"] == []
    assert info["queryable_start"] == min(days).isoformat() and info["queryable_end"] == max(days).isoformat()
    assert info["scenario"] == next(p["scenario"] for p in raw["profiles"] if p["profile_id"] == profile)


@pytest.mark.parametrize("profile", PROFILE_IDS)
@pytest.mark.parametrize("language", ["中文", "English"])
def test_function_examples_use_real_dates_fields_and_supported_windows(profile, language):
    from sleeplens.onboarding import data_catalogue, question_examples

    info = data_catalogue(profile, today=date(2026, 12, 27))
    examples = question_examples(info, language)
    assert {e["id"] for e in examples} == {"duration", "deep", "stages", "period", "knowledge", "normality"}
    for example in examples:
        if example["query"]:
            assert example["query"]["profile_id"] == profile
            output = analyze_sleep(**example["query"], today=date(2026, 12, 27))
            assert output["current"]["valid_nights"] > 0
            if example["id"] in {"deep", "stages", "normality"}:
                row = output["daily_records"]["current"][0]
                assert row["sleep_min"] > 0 and all(row[k] is not None for k in ["deep_sleep_min", "light_sleep_min", "rem_sleep_min"])
            if example["query"]["compare_previous"]:
                assert output["comparison_state"] == "available"
            # The prepared wording must resolve to exactly the dates the button prepares.
            plan = plan_query(example["question"], today=date(2026, 12, 27))
            assert plan.period == (example["query"]["start_date"], example["query"]["end_date"])


@pytest.mark.parametrize("language", ["中文", "English"])
def test_examples_for_the_newest_night_use_relative_wording(language):
    from sleeplens.onboarding import data_catalogue, question_examples

    today = date(2026, 11, 26)  # The pinned display window ends today.
    examples = question_examples(data_catalogue("P01", today=today), language)
    night, week = ("昨晚", "最近七天") if language == "中文" else ("last night", "past 7 days")
    for example in examples:
        if example["query"]:
            assert "2026-" not in example["question"]
            assert (week if example["id"] == "period" else night) in example["question"]
            plan = plan_query(example["question"], today=today)
            assert plan.period == (example["query"]["start_date"], example["query"]["end_date"])


def test_units_and_computed_fields_match_the_implemented_record_definitions():
    from sleeplens.onboarding import data_catalogue, metric_rows

    info = data_catalogue("P01", today=date(2026, 12, 27))
    raw = metric_rows(info, "English")
    assert {r["field"] for r in raw} == {"sleep_min", "sleep_onset", "wake_time", "night_awakenings", "awake_min", "deep_sleep_min", "light_sleep_min", "rem_sleep_min"}
    assert next(r for r in raw if r["field"] == "night_awakenings")["unit"] == "count"
    assert all(r["unit"] == "min" for r in raw if r["field"].endswith("_min"))
    assert all("Europe/Berlin" in r["unit"] for r in raw if r["field"] in {"sleep_onset", "wake_time"})
    assert "N1 + N2" in next(r for r in raw if r["field"] == "light_sleep_min")["meaning"]


def forbidden_model():
    raise AssertionError("Reading onboarding or preparing an example must not initialize a model")


def open_app(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sleeplens.dashboard.create_model", forbidden_model)
    # Pin the clock after the display data so every recorded date is "completed".
    for module in ("sleeplens.analysis", "sleeplens.agent", "sleeplens.web"):
        monkeypatch.setattr(module + ".berlin_today", lambda: date(2026, 12, 26))
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()


def test_page_introduces_the_project_and_clicking_an_example_does_not_send(monkeypatch, tmp_path):
    app = open_app(monkeypatch, tmp_path)
    assert not app.exception
    shown = "\n".join(b.value for group in [app.markdown, app.caption] for b in group)
    assert "synthetic" in shown.lower() and "P01" in shown
    assert "adult" in shown.lower() and "manual" in shown.lower()
    captions = "\n".join(b.value for b in app.caption)
    assert not any(text in captions for text in [
        "This course demonstration", "Current profile", "Queryable record dates",
        "unique record dates", "Variable timing", "Try a question", "An example only fills",
    ])
    app.button(key="example_duration").click().run()
    assert not app.exception and not app.error
    assert app.session_state["dashboard"].turns == []
    assert app.chat_input[0].proto.set_value and "P01" in app.chat_input[0].proto.value


def test_profile_and_language_changes_update_examples_without_duplicate_selectors(monkeypatch, tmp_path):
    app = open_app(monkeypatch, tmp_path)
    app.selectbox(key="record_profile").set_value("P02")
    app.button(key="apply_selection").click().run()
    app.selectbox(key="ui_language").set_value("中文").run()
    assert not app.exception
    shown = "\n".join(b.value for group in [app.markdown, app.caption] for b in group)
    assert app.selectbox(key="record_profile").value == "P02"
    assert "13" in shown and "11" in shown
    assert "当前档案 P02" not in shown and "可以这样提问" not in shown
    assert "SleepLens is an adult" not in shown
    assert len([s for s in app.selectbox if s.key == "record_profile"]) == 1
    app.button(key="example_deep").click().run()
    assert app.chat_input[0].proto.set_value and "P02" in app.chat_input[0].proto.value
    assert "深睡" in app.chat_input[0].proto.value and not app.session_state["dashboard"].turns


@pytest.mark.parametrize("old_language,new_language", [("English", "中文"), ("中文", "English")])
@pytest.mark.parametrize("days", [1, 7, 14])
def test_delayed_range_label_after_language_change_keeps_numeric_days(monkeypatch, tmp_path, old_language, new_language, days):
    app = open_app(monkeypatch, tmp_path)
    app.selectbox(key="ui_language").set_value(old_language).run()
    app.selectbox(key="record_span").set_value(days).run()
    old_label = app.selectbox(key="record_span").options[[7, 14, 1].index(days)]
    app.selectbox(key="ui_language").set_value(new_language).run()
    assert not app.exception

    # Replay the previous language's browser payload, rather than letting
    # AppTest serialize the Python value using the new labels.
    states = app._tree.get_widget_states()
    range_id = app.selectbox(key="record_span").id
    next(state for state in states.widgets if state.id == range_id).string_value = old_label
    app._run(states)

    assert not app.exception
    assert type(app.session_state["record_span"]) is int
    assert app.selectbox(key="record_span").value == days
    assert app.checkbox(key="record_compare").disabled == (days != 7)
    app.date_input(key="record_start").set_value(date(2026, 10, 19))
    app.button(key="apply_selection").click().run()
    assert not app.exception
    selection = app.session_state["dashboard"].selection
    assert selection["start_date"] == "2026-10-19"
    assert selection["end_date"] == (date(2026, 10, 19) + timedelta(days=days - 1)).isoformat()


def test_classroom_examples_are_separate_and_have_a_genuinely_absent_date():
    from sleeplens.onboarding import data_catalogue, classroom_examples

    for profile in PROFILE_IDS:
        info = data_catalogue(profile, today=date(2026, 12, 27))
        examples = classroom_examples(info, "中文")
        no_data = next(e for e in examples if e["id"] == "no_records")
        output = analyze_sleep(**no_data["query"], today=date(2026, 12, 27))
        assert output["status"] == "no_data"
        assert output["daily_records"]["current"][0]["record_state"] == "missing_record"
        assert {e["id"] for e in examples} == {"no_records", "medical", "outside"}
        assert not any("自杀" in e["question"] for e in examples)


def test_dataset_read_failure_keeps_the_page_usable_and_hides_exception_details(monkeypatch, tmp_path):
    def fail():
        raise OSError("SECRET raw path /private/canary")

    monkeypatch.setattr("sleeplens.analysis.load_dataset", fail)
    app = open_app(monkeypatch, tmp_path)
    assert not app.exception and app.chat_input
    shown = "\n".join(str(b.value) for group in [app.markdown, app.caption, app.info, app.warning, app.error] for b in group)
    assert "temporarily" in shown.lower()
    assert "SECRET" not in shown and "canary" not in shown
    assert not app.session_state["dashboard"].turns
    app.chat_input[0].set_value("Hello").run()
    assert not app.exception and len(app.session_state["dashboard"].turns) == 1


def test_prefilled_example_runs_only_after_explicit_submission(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from openai.types.chat import ChatCompletionMessage
    from sleeplens.config import Settings

    app = open_app(monkeypatch, tmp_path)
    app.button(key="example_duration").click().run()
    question = app.chat_input[0].proto.value
    calls = []
    query = dict(profile_id="P01", start_date="2026-11-26", end_date="2026-11-26", compare_previous=False)
    minutes = analyze_sleep(**query)["daily_records"]["current"][0]["sleep_min"]
    messages = [ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "record", "type": "function", "function": {
            "name": "analyze_sleep", "arguments": json.dumps(query)}}]),
        ChatCompletionMessage(role="assistant", content=f"Recorded sleep duration was {minutes} minutes.")]

    class Client:
        def complete(self, *args, **kwargs):
            calls.append(True)
            return SimpleNamespace(model="offline-first-use", usage=None, choices=[
                SimpleNamespace(message=messages.pop(0), finish_reason="stop")])

    app.session_state["dashboard"]._model_factory = lambda: (Client(), Settings(api_key="offline"))
    assert not calls and not app.session_state["dashboard"].turns
    app.chat_input[0].set_value(question).run()
    assert not app.exception and calls
    turn = app.session_state["dashboard"].turns[-1]
    assert turn["question"] == question and turn["status"] == "answered"
    assert turn["tool_events"][0]["result"]["dataset_version"] == "display-sleep-v1"


def test_examples_respect_completed_dates_and_legacy_missing_fields():
    from sleeplens.data import DETAIL_FIELDS, parse_dataset
    from sleeplens.onboarding import data_catalogue, question_examples, metric_rows

    raw = json.loads((ROOT / "src/sleeplens/fixtures/display_sleep.json").read_text(encoding="utf-8"))
    for row in raw["records"]:
        for field in DETAIL_FIELDS:
            row.pop(field, None)
    info = data_catalogue("P01", today=date(2026, 11, 16), dataset=parse_dataset(raw))
    # Today's waking date (last night) is queryable, so 11-13 to 11-16 count.
    assert info["unique_dates"] == 14 and info["queryable_unique_dates"] == 4
    assert info["queryable_end"] == "2026-11-16" and len(info["incomplete_dates"]) == 14
    assert info["complete_detail_nights"] == 0
    assert [r["field"] for r in metric_rows(info, "English")] == ["sleep_min"]
    examples = question_examples(info, "English")
    assert {e["id"] for e in examples} == {"duration", "knowledge"}
    assert all(e["query"] is None or e["query"]["end_date"] <= "2026-11-16" for e in examples)


@pytest.mark.parametrize("problem,issue", [("duplicate", "duplicate_record"), ("incomplete", "incomplete_data")])
def test_unusable_data_is_not_presented_as_zero_records(monkeypatch, problem, issue):
    from sleeplens.data import parse_dataset
    from sleeplens.onboarding import data_catalogue, question_examples

    raw = json.loads((ROOT / "src/sleeplens/fixtures/display_sleep.json").read_text(encoding="utf-8"))
    if problem == "duplicate":
        raw["records"].append(dict(raw["records"][0]))
    else:
        raw["records"][0].pop("deep_sleep_min")
    monkeypatch.setattr("sleeplens.analysis.load_dataset", lambda: parse_dataset(raw))
    info = data_catalogue("P01")
    assert info["status"] == "unavailable" and info["issue"] == issue
    assert "unique_dates" not in info and "valid_nights" not in info
    assert all(e["query"] is None for e in question_examples(info, "English"))
