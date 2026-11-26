"""Stage questions stay useful when a date or model interpretation is unavailable."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from streamlit.testing.v1 import AppTest

from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.answer_validation import validate_record_text
from sleeplens.config import Settings
from sleeplens.failure_display import stage_assessment_reply
from sleeplens.knowledge import load_knowledge
from sleeplens.llm import ModelError
from sleeplens.query_policy import plan_query


TODAY = date(2026, 11, 24)
WEEK = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-25", compare_previous=True)
DAY = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-19", compare_previous=False)


class Client:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def complete(self, messages, tools, timeout):
        self.calls += 1
        assert self.items, "Unexpected model request"
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        message = ChatCompletionMessage(role="assistant", content=item) if isinstance(item, str) else item
        return SimpleNamespace(model="offline-stage-fallback", usage=None,
                               choices=[SimpleNamespace(message=message, finish_reason="stop")])

    def close(self):
        pass


def evidence(args=None):
    calls = [("search_sleep_knowledge", {"query": "deep sleep stage distribution"})]
    if args:
        calls.insert(0, ("analyze_sleep", args))
    return ChatCompletionMessage(role="assistant", tool_calls=[
        {"id": str(i), "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        for i, (name, arguments) in enumerate(calls)])


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: TODAY)


@pytest.mark.parametrize("question", [
    "今晚的深睡占比正常吗？", "今天晚上的REM占比正常吗？", "今夜的浅睡比例正常吗？",
    "Is my deep sleep percentage normal tonight?", "Is my REM percentage normal this evening?",
])
def test_tonight_overrides_old_page_dates_without_a_model(question):
    client = Client()
    result = ChatSession(client).ask(question, selected_query=WEEK)
    assert result["query_plan"]["period"] == ("2026-11-25", "2026-11-25")
    assert result["status"] == "answered" and client.calls == 0
    assert not result["tool_events"] and not result.get("verified_record_facts")
    assert "2026-11-25" in result["answer"]
    assert "2026-10-19" not in result["answer"] and "2026-10-25" not in result["answer"]
    assert result["reply_policy"]["reason"] == "date_unavailable"
    assert not result["citation_check"]["references"]
    assert result["record_availability"]["state"] == "not_queried"


def test_tonight_rolls_over_the_year():
    plan = plan_query("今晚的深睡占比正常吗？", today=date(2026, 12, 31), selected_query=WEEK)
    assert plan.period == ("2027-01-01", "2027-01-01")
    assert plan.task == "combined" and "deep" in plan.metrics


@pytest.mark.parametrize("text", [
    "深睡占比会随年龄、睡眠时长以及前一晚的睡眠和活动情况而变化。[H10:Benchmarks]",
    "目前没有通用的深睡占比正常值可以拿来对照。深睡占比会随年龄、睡眠时长以及前一晚的睡眠和活动情况而变化。[H10:Benchmarks]",
])
def test_previous_night_is_a_time_reference_without_personal_measurements(text):
    refs = {r["citation_id"]: r["text"] for r in load_knowledge().references if r["source_id"].startswith("H")}
    assert validate_record_text(text, None, require_summary=False, health_references=refs) is None


@pytest.mark.parametrize("text", [
    "你的记录中有一晚有效记录。", "你的深睡只有一晚达标。",
    "你前一晚深睡999分钟。[H10:Benchmarks]", "你前一晚的深睡占比为99%。[H10:Benchmarks]",
])
def test_actual_personal_counts_and_measurements_still_require_records(text):
    refs = {r["citation_id"]: r["text"] for r in load_knowledge().references if r["source_id"].startswith("H")}
    assert validate_record_text(text, None, require_summary=False, health_references=refs)


BAD = "你的深睡67分钟已经达标。[H6:Pattern]"


def test_blocked_stage_grading_preserves_actual_minutes_and_calculated_share():
    client = Client(evidence(DAY), BAD, BAD)
    result = ChatSession(client).ask("2026-10-19的深睡占比正常吗？", selected_query=WEEK)
    row = analyze_sleep(**DAY, today=TODAY)["daily_records"]["current"][0]
    assert result["status"] == "answered"
    assert result["answer_validation"]["fallback"] == "stage_assessment"
    assert f"{row['deep_sleep_min']}" in result["answer"]
    assert f"{row['deep_sleep_min'] / row['sleep_min'] * 100:.1f}%" in result["answer"]
    assert "已经达标" not in result["answer"] and "依据核对" not in result["answer"]
    assert not result["citation_check"]["references"]


def test_blocked_general_question_gets_product_limit_and_next_step():
    result = ChatSession(Client(evidence(), BAD, BAD)).ask("深睡占比正常吗？")
    assert result["answer_validation"]["fallback"] == "stage_assessment"
    assert "日期" in result["answer"] and "尚未取得" in result["answer"]
    assert not result["citation_check"]["references"] and "67" not in result["answer"]


def test_no_records_fallback_does_not_replace_the_requested_date():
    args = {**DAY, "start_date": "2026-11-20", "end_date": "2026-11-20"}
    result = ChatSession(Client(evidence(args), BAD, BAD)).ask("2026-11-20的深睡占比正常吗？", selected_query=WEEK)
    assert "2026-11-20" in result["answer"] and "没有可用" in result["answer"]
    assert not result["citation_check"]["references"] and "2026-10-19" not in result["answer"]
    assert "67" not in result["answer"]


def test_model_failure_still_explains_what_is_needed_without_claiming_no_records():
    result = ChatSession(Client(ModelError("unavailable"))).ask("我的深睡占比正常吗？", selected_query=DAY)
    assert result["error"]["code"] == "model_error"
    assert result["answer_validation"]["fallback"] == "stage_assessment"
    assert "重试" in result["answer"] and "没有可用睡眠记录" not in result["answer"]
    assert result["record_availability"]["state"] == "not_queried"
    assert not result["citation_check"]["references"]


@pytest.mark.parametrize("missing", ["stage", "zero_total"])
def test_missing_stage_or_zero_denominator_is_not_filled_in(missing):
    output = deepcopy(analyze_sleep(**DAY, today=TODAY))
    row = output["daily_records"]["current"][0]
    if missing == "stage":
        row["deep_sleep_min"] = None
    else:
        row["sleep_min"] = 0
        row["deep_sleep_min"] = 0
    plan = plan_query("2026-10-19的深睡占比正常吗？", today=TODAY, selected_query=WEEK)
    answer = stage_assessment_reply(plan, "Chinese", record=output)
    assert "无法计算" in answer and "0.0%" not in answer
    assert "[B1:ProductStages]" not in answer
    assert "深睡时长" in answer if missing == "stage" else "总睡眠时长" in answer
    assert "| ---" not in answer


def test_weekly_fallback_uses_each_nights_own_denominator_and_requested_stage():
    output = analyze_sleep(**{**WEEK, "compare_previous": False}, today=TODAY)
    plan = plan_query("这周的深睡占比正常吗？", today=TODAY, selected_query=WEEK)
    answer = stage_assessment_reply(plan, "Chinese", record=output)
    for row in output["daily_records"]["current"]:
        assert f"| {row['record_date']} | 深睡 | {row['deep_sleep_min']} | {row['sleep_min']} | {row['deep_sleep_min'] / row['sleep_min'] * 100:.1f}% |" in answer
    assert "| 浅睡 |" not in answer and "| REM |" not in answer
    assert "2026-10-12" not in answer


def test_failed_new_lookup_does_not_reuse_old_stage_values(monkeypatch):
    old_row = analyze_sleep(**DAY, today=TODAY)["daily_records"]["current"][0]
    args = {**DAY, "start_date": "2026-10-20", "end_date": "2026-10-20"}
    client = Client(evidence(DAY), f"深睡{old_row['deep_sleep_min']}分钟。", evidence(args), BAD, BAD)
    session = ChatSession(client)
    assert session.ask("2026-10-19深睡多少分钟？", selected_query=WEEK)["status"] == "answered"

    def unavailable():
        raise OSError("injected read failure")

    monkeypatch.setattr("sleeplens.analysis.load_dataset", unavailable)
    result = session.ask("2026-10-20的深睡占比正常吗？", selected_query=WEEK)
    assert result["answer_validation"]["fallback"] == "stage_assessment"
    assert "读取失败" in result["answer"] and "稍后再试" in result["answer"]
    assert result["reply_policy"]["category"] == "tool_failure"
    assert "2026-10-19" not in result["answer"] and "| ---" not in result["answer"]
    assert result["record_context"]["scope_matches"] is False
    assert result["record_availability"]["state"] == "lookup_failed"


@pytest.mark.parametrize("question,client", [
    ("今晚的深睡占比正常吗？", lambda: Client()),
    ("2026-10-19的深睡占比正常吗？", lambda: Client(evidence(DAY), BAD, BAD)),
    ("Is my deep sleep percentage normal?", lambda: Client(ModelError("unavailable"))),
])
def test_web_displays_fallback_as_an_answer_with_its_sources(monkeypatch, tmp_path, question, client):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sleeplens.dashboard.create_model", lambda: (client(), Settings(api_key="offline")))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    app.chat_input[0].set_value(question).run()
    assert not app.exception and not app.error and not app.warning
    turn = app.session_state["dashboard"].turns[-1]
    shown = "\n".join(block.value for block in app.markdown)
    assert turn["answer_validation"]["fallback"] == "stage_assessment"
    assert "[B1:ProductStages]" not in shown
    has_source = bool(turn["citation_check"]["references"])
    assert ("SleepLens record definitions" in shown) is has_source
    assert ("[1]" in shown) is has_source
    assert "依据核对" not in shown and "AI could not finish this request" not in shown
