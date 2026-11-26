"""Three-turn record/advice follow-ups with fixed tools and model messages."""

import json
from datetime import date
from types import SimpleNamespace
from pathlib import Path

import pytest
from openai.types.chat import ChatCompletionMessage
from streamlit.testing.v1 import AppTest

from sleeplens.agent import ChatSession
from sleeplens.config import Settings
from sleeplens.telemetry import save_share_event
from sleeplens.tools import dispatch_tool


pytestmark = pytest.mark.usefixtures("regression_dataset")


WEEK = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-25", compare_previous=False)
COMPARED = {**WEEK, "compare_previous": True}
FOLLOWUP = "结合这段记录，有哪些可以尝试的改善方法？"
GOOD = ("这段记录平均每晚390分钟，比前一周少30分钟。\n\n"
        "可以尝试保持规律的入睡和起床时间。[H2:Schedule]")
BAD = "这段记录平均每晚999分钟。建议每天提前90分钟上床。[H2:Schedule]"


def tool(name, args, identity="lookup"):
    return ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": identity, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}])


class Client:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.requests = []

    def complete(self, messages, tools, timeout):
        self.requests.append(json.loads(json.dumps(messages)))
        message = self.messages.pop(0)
        if isinstance(message, str):
            message = ChatCompletionMessage(role="assistant", content=message)
        return SimpleNamespace(model="offline-three-turn", usage=None, choices=[
            SimpleNamespace(message=message, finish_reason="stop")])

    def close(self):
        pass


def seed(*tail):
    client = Client(tool("analyze_sleep", WEEK), "本周平均每晚睡了390分钟。",
                    tool("analyze_sleep", COMPARED), "本周390分钟，前一周420分钟，比前一周少30分钟。", *tail)
    session = ChatSession(client)
    first = session.ask("查一下2026-10-19至2026-10-25这一周平均睡眠时长", selected_query=WEEK)
    second = session.ask("和前一周比较一下", selected_query=WEEK)
    assert first["status"] == second["status"] == "answered"
    return session, client, [first, second]


def reproduce(answer=BAD):
    session, client, turns = seed(tool("search_sleep_knowledge", {"query": "sleep routine"}), answer, answer)
    turns.append(session.ask(FOLLOWUP, selected_query=COMPARED))
    return turns


@pytest.mark.parametrize("advice", [GOOD, BAD])
def test_verified_comparison_survives_a_rejected_comparison_narrative(advice):
    client = Client(tool("analyze_sleep", WEEK), "本周平均390分钟。",
                    tool("analyze_sleep", COMPARED), "本周平均999分钟。", "本周平均999分钟。",
                    tool("search_sleep_knowledge", {"query": "sleep routine"}), advice, advice)
    session = ChatSession(client)
    first = session.ask("查2026-10-19至2026-10-25平均睡眠", selected_query=WEEK)
    second = session.ask("和前一周比较一下", selected_query=WEEK)
    assert first["status"] == "answered" and second["status"] == "needs_review"
    assert "420" in second["verified_record_facts"]
    third = session.ask(FOLLOWUP, selected_query=COMPARED)
    assert third["query_plan"]["compare_previous"] is True
    assert third["record_context"]["source"] == "history"
    assert third["record_context"]["provided_via"] == "verified_record_data"
    assert third["record_context"]["origin_turn"] == 2
    assert any("VERIFIED_RECORD_DATA" in m.get("content", "") for m in client.requests[-1])
    assert not any("999" in m.get("content", "") for m in client.requests[-1][:-1])
    if advice == GOOD:
        assert third["status"] == "answered" and "保持规律" in third["answer"]
    else:
        assert "390" in third["verified_record_facts"] and "420" in third["verified_record_facts"]


def test_expired_record_cache_keeps_scope_but_cannot_supply_old_values():
    client = Client(tool("analyze_sleep", WEEK), "本周平均390分钟。",
                    tool("analyze_sleep", COMPARED), "本周平均999分钟。", "本周平均999分钟。",
                    tool("search_sleep_knowledge", {"query": "sleep routine"}), BAD, BAD)
    session = ChatSession(client, history_turns=1)
    session.ask("查2026-10-19至2026-10-25平均睡眠", selected_query=WEEK)
    session.ask("和前一周比较一下", selected_query=WEEK)
    session.ask("你好", selected_query=COMPARED)
    result = session.ask(FOLLOWUP, selected_query=COMPARED)
    assert result["query_plan"]["compare_previous"] is True
    assert not result.get("verified_record_facts")
    assert result["record_context"]["scope_matches"] is False


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 23))
    monkeypatch.setattr("sleeplens.analysis.berlin_today", lambda: date(2026, 11, 23))


def test_three_turn_followup_resolves_profile_period_and_comparison_scope():
    turns = reproduce(GOOD)
    plan = turns[-1]["query_plan"]
    assert plan["followup"] and plan["profile_id"] == "P01"
    assert tuple(plan["period"]) == (WEEK["start_date"], WEEK["end_date"])
    assert plan["compare_previous"] is True and "comparison" in plan["metrics"]


def test_supported_advice_reuses_matching_records_and_retrieves_health_evidence():
    result = reproduce(GOOD)[-1]
    assert result["status"] == "answered" and "保持规律" in result["answer"]
    assert result["answer_validation"]["status"] == "passed"
    assert [event["tool"] for event in result["tool_events"]] == ["search_sleep_knowledge"]
    assert "H2:Schedule" in [ref["citation_id"] for ref in result["retrieved_evidence"]]
    assert result["record_context"]["source"] == "history"
    assert result["record_context"]["scope_matches"] is True


def test_failed_advice_keeps_matching_history_records_including_the_comparison():
    result = reproduce()[-1]
    assert result["status"] == "needs_review"
    assert result["answer_validation"]["repairs"]
    facts = result["verified_record_facts"]
    assert all(value in facts for value in ["390", "420", "30", "7/7"])
    assert "999" not in facts and "90分钟" not in result["answer"]
    assert "建议" in result["answer"] and "已核实的记录" in result["answer"]
    assert result["reply_policy"]["partial"] is True


def test_model_presentation_refinement_keeps_the_confirmed_comparison_in_fallback():
    search = tool("search_sleep_knowledge", {"query": "sleep routine", "response_plan": {
        "intent": "advice", "metrics": ["mean"], "evidence": ["records", "knowledge"], "answer_format": "advice"}})
    session, _, _ = seed(search, BAD, BAD)
    result = session.ask(FOLLOWUP, selected_query=COMPARED)
    assert result["query_plan"]["compare_previous"] is True
    assert "420" in result["verified_record_facts"] and "30" in result["verified_record_facts"]


@pytest.mark.parametrize("selection", [
    {**COMPARED, "profile_id": "P02"},
    {**COMPARED, "start_date": "2026-10-12", "end_date": "2026-10-18"},
])
def test_selection_change_cannot_reuse_the_previous_record_summary(selection):
    session, client, _ = seed(tool("search_sleep_knowledge", {"query": "sleep routine"}), BAD, BAD)
    result = session.ask(FOLLOWUP, selected_query=selection)
    assert not result.get("verified_record_facts")
    assert "390" not in result["answer"] and "420" not in result["answer"]
    assert result["record_context"]["scope_matches"] is False


def test_fresh_lookup_failure_has_priority_over_previously_valid_history(monkeypatch):
    session, client, _ = seed(tool("analyze_sleep", COMPARED), BAD, BAD)
    def fail_lookup(name, args, **kwargs):
        if name == "analyze_sleep":
            return {"status": "tool_error", "profile_id": "P01", "period": {
                "start_date": WEEK["start_date"], "end_date": WEEK["end_date"]}, "current": None,
                "error": {"code": "dataset_unavailable", "message": "Synthetic fixture read failure"}}
        return dispatch_tool(name, args, **kwargs)
    monkeypatch.setattr("sleeplens.agent.dispatch_tool", fail_lookup)
    result = session.ask(FOLLOWUP, selected_query=COMPARED)
    assert not result.get("verified_record_facts") and "读取失败" in result["answer"]
    assert result["record_context"]["source"] == "current_tool"
    # A later turn must query again rather than resurrect a pre-failure tool message.
    client.messages.extend([tool("search_sleep_knowledge", {"query": "sleep routine"}), BAD, BAD])
    again = session.ask(FOLLOWUP, selected_query=COMPARED)
    assert not again.get("verified_record_facts")


def test_explicit_new_comparison_scope_uses_only_the_new_lookup():
    session, client, _ = seed(tool("analyze_sleep", WEEK), BAD, BAD)
    result = session.ask("不比较前一周，只结合这段记录给改善建议", selected_query=WEEK)
    assert "390" in result["verified_record_facts"]
    assert "420" not in result["verified_record_facts"] and "30.0" not in result["verified_record_facts"]


def test_general_health_question_does_not_get_an_unrequested_record_fallback():
    session, client, _ = seed(tool("search_sleep_knowledge", {"query": "sleep routine"}), BAD, BAD)
    result = session.ask("不查个人记录，只问一般成人睡眠建议", selected_query=COMPARED)
    assert not result.get("verified_record_facts")


def test_sharing_diagnostics_explain_blocks_without_logging_user_text(tmp_path):
    result = reproduce()[-1]
    result["question"] = "private-question-canary"
    result["candidate_answer"] = "private-answer-canary"
    path = save_share_event(result, folder=tmp_path)
    raw = path.read_text(encoding="utf-8")
    metadata = json.loads(raw)
    assert "private-question-canary" not in raw and "private-answer-canary" not in raw
    diagnostics = metadata["diagnostics"]
    assert diagnostics["blocking_codes"]
    assert diagnostics["record_context"]["source"] == "history"
    assert diagnostics["scope"]["compare_previous"] is True


@pytest.mark.parametrize("answer", [GOOD, BAD])
def test_actual_page_keeps_the_same_three_turn_record_context(monkeypatch, tmp_path, answer):
    monkeypatch.chdir(tmp_path)
    client = Client(tool("analyze_sleep", WEEK), "本周平均每晚睡了390分钟。",
                    tool("analyze_sleep", COMPARED), "本周390分钟，前一周420分钟，比前一周少30分钟。",
                    tool("search_sleep_knowledge", {"query": "sleep routine"}), answer, answer)
    monkeypatch.setattr("sleeplens.dashboard.create_model", lambda: (client, Settings(api_key="offline")))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"), default_timeout=15).run()
    for question in ["查一下2026-10-19至2026-10-25这一周平均睡眠时长", "和前一周比较一下", FOLLOWUP]:
        app.chat_input[0].set_value(question).run()
        assert not app.exception
    dashboard = app.session_state["dashboard"]
    assert len(dashboard.turns) == 3 and dashboard.selection == COMPARED
    result = dashboard.turns[-1]
    assert result["record_context"]["source"] == "history" and result["record_context"]["scope_matches"]
    if answer == GOOD:
        assert result["status"] == "answered" and not app.warning
    else:
        shown = "\n".join(block.value for block in app.markdown)
        assert "390" in shown and "420" in shown and "999" not in shown
        assert any("建议" in warning.value for warning in app.warning)
