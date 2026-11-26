"""Routing and selected presentation regressions; all clients are scripted."""

import json
import runpy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage

from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.query_policy import plan_query, render_facts
from sleeplens.response_planning import build_response_plan


WEEK = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-25", compare_previous=False)
# Display-data week for the nightly-table tests; WEEK above pairs with the regression fixture.
DISPLAY_WEEK = dict(profile_id="P01", start_date="2026-11-20", end_date="2026-11-26", compare_previous=False)
DISPLAY_TODAY = date(2026, 12, 26)


class Client:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.calls = 0

    def complete(self, messages, tools, timeout):
        self.calls += 1
        assert self.messages, messages[-1]
        item = self.messages.pop(0)
        message = ChatCompletionMessage(role="assistant", content=item) if isinstance(item, str) else item
        return SimpleNamespace(model="offline-v29", usage=None,
                               choices=[SimpleNamespace(message=message, finish_reason="stop")])


def lookup(args):
    return ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "records", "type": "function", "function": {
            "name": "analyze_sleep", "arguments": json.dumps(args)}}])


@pytest.mark.parametrize("question", [
    "解释均值的分母规则，并告诉我所选这周平均睡多久。",
    "解释均值分母，并给出P01在2026-10-19至2026-10-25的平均睡眠时长。",
    "Explain the denominator rule and tell me my average sleep for the selected week.",
])
def test_compound_rule_and_lookup_is_not_swallowed(question):
    plan = plan_query(question, today=date(2026, 11, 24), selected_query=WEEK)
    assert plan.task in {"records", "combined"}
    assert "mean" in plan.metrics


def test_compound_rule_lookup_completes_in_one_turn(regression_dataset, monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 24))
    answer = "均值按有效夜数计算，缺失不补零。[B2:Coverage]\n\n所选这周平均每晚睡了390分钟。"
    client = Client(lookup(WEEK), answer)
    result = ChatSession(client).ask("解释均值的分母规则，并告诉我所选这周平均睡多久。", selected_query=WEEK)
    assert client.calls == 2
    assert result["status"] == "answered" and result["answer"] == answer
    assert result["tool_events"][0]["validated_arguments"] == WEEK
    assert not result["answer_validation"]["repairs"]


def test_pure_rule_question_still_needs_no_model():
    client = Client()
    result = ChatSession(client).ask("解释均值的分母规则。", selected_query=WEEK)
    assert result["status"] == "answered" and client.calls == 0
    assert not result["tool_events"]


def test_lookup_does_not_require_an_unrequested_coverage_footer():
    question = "这周平均睡多久，只要均值。"
    plan = plan_query(question, today=date(2026, 11, 24), selected_query=WEEK)
    assert "coverage" not in build_response_plan(question, plan, WEEK)["requirements"]
    question = "这周有几晚有效记录，覆盖率多少？"
    plan = plan_query(question, today=date(2026, 11, 24), selected_query=WEEK)
    assert "coverage" in build_response_plan(question, plan, WEEK)["requirements"]


def test_compound_lookup_keeps_explicit_profile_and_date(regression_dataset, monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 24))
    explicit = dict(profile_id="P03", start_date="2026-10-20", end_date="2026-10-20", compare_previous=False)
    output = analyze_sleep(**explicit, today=date(2026, 11, 24))
    minutes = output["daily_records"]["current"][0]["sleep_min"]
    answer = f"均值按有效夜数计算。[B2:Coverage] P03在2026-10-20睡了{minutes}分钟。"
    result = ChatSession(Client(lookup(explicit), answer)).ask(
        "解释均值的分母规则，并给出P03在2026-10-20的睡眠时长。", selected_query=WEEK)
    assert result["status"] == "answered" and result["answer"] == answer
    assert result["tool_events"][0]["validated_arguments"] == explicit


@pytest.mark.parametrize("question", ["这周夜醒算多吗？", "这周夜醒正常吗？"])
def test_waking_interpretation_does_not_force_nightly_table(question):
    plan = plan_query(question, today=date(2026, 11, 24), selected_query=WEEK)
    assert "awakenings" in plan.metrics and "awake" in plan.metrics
    assert "daily" not in plan.metrics


@pytest.mark.parametrize("language,question", [
    ("Chinese", "逐夜列出所选这周的深睡时长，只要表格。"),
    ("English", "Show deep sleep night by night for the selected week, table only."),
])
def test_nightly_table_does_not_prepend_means_or_internal_checks(language, question):
    output = analyze_sleep(**DISPLAY_WEEK, today=DISPLAY_TODAY)
    plan = plan_query(question, today=DISPLAY_TODAY, selected_query=DISPLAY_WEEK)
    answer = render_facts(output, plan, language)
    assert "|" in answer and "2026-11-23" in answer
    assert "平均每晚深睡" not in answer and "Mean deep sleep" not in answer
    assert "中午" not in answer and "noon" not in answer


def test_requested_mean_and_nightly_detail_are_both_retained():
    output = analyze_sleep(**DISPLAY_WEEK, today=DISPLAY_TODAY)
    plan = plan_query("给出所选这周平均深睡时长，并逐夜列出。", today=DISPLAY_TODAY, selected_query=DISPLAY_WEEK)
    answer = render_facts(output, plan, "Chinese")
    assert "平均每晚深睡" in answer and "|" in answer


def test_nightly_onsets_do_not_explain_internal_average_algorithm():
    output = analyze_sleep(**DISPLAY_WEEK, today=DISPLAY_TODAY)
    plan = plan_query("逐夜列出所选这周入睡时刻。", today=DISPLAY_TODAY, selected_query=DISPLAY_WEEK)
    answer = render_facts(output, plan, "Chinese")
    assert "2026-11-23" in answer and "|" in answer
    assert "中午" not in answer and "平均入睡" not in answer


def test_authored_dialogues_evidence_and_all_loading_combinations():
    root = Path(__file__).resolve().parents[1]
    report = runpy.run_path(str(root / "scripts/check_current.py"))["run_checks"]()
    assert report["paid_model_requests"] == 0
    assert len(report["cases"]) == 12
    assert report["loading_combinations"] == 112
    assert report["maximum_context_chars"] <= 20000
