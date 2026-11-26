"""User-facing interception regressions; fixed records and scripted model output."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage
from streamlit.testing.v1 import AppTest

from sleeplens.agent import ChatSession
from sleeplens.answer_validation import needs_health_for_task, review_health_text
from sleeplens.config import Settings
from sleeplens.query_policy import QueryPlan, plan_query
from sleeplens.tools import dispatch_tool


pytestmark = pytest.mark.usefixtures("regression_dataset")


WEEK = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-25", compare_previous=False)
DAY = dict(profile_id="P01", start_date="2026-10-22", end_date="2026-10-22", compare_previous=False)


class Client:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.requests = []

    def complete(self, messages, tools, timeout):
        self.requests.append(json.loads(json.dumps(messages)))
        message = self.messages.pop(0)
        if isinstance(message, str):
            message = ChatCompletionMessage(role="assistant", content=message)
        return SimpleNamespace(model="offline-regression", usage=None, choices=[
            SimpleNamespace(message=message, finish_reason="stop")])

    def close(self):
        pass


def lookup(query):
    return ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "records", "type": "function", "function": {
            "name": "analyze_sleep", "arguments": json.dumps(query)}}])


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 23))
    monkeypatch.setattr("sleeplens.analysis.berlin_today", lambda: date(2026, 11, 23))


@pytest.mark.parametrize("question", [
    "你叫什么名字？", "你是谁？", "你能做什么？", "你可以分析哪些睡眠指标？",
    "What is your name?", "What's your name?", "Which sleep metrics can you analyze?",
    "Who are you, and what can you do?",
])
def test_product_introductions_are_local(question):
    result = ChatSession(None).ask(question)
    assert result["status"] == "answered" and "SleepLens" in result["answer"]
    assert not result["model_calls"] and not result["tool_events"]


@pytest.mark.parametrize("task", ["conversation", "capability", "definition"])
@pytest.mark.parametrize("text", [
    "我是 SleepLens，可以展示深睡时长和夜醒次数。",
    "I am SleepLens. I can display deep sleep duration and night awakenings.",
    "夜醒次数这个字段记录入睡后、最终醒来前的中途醒来次数，不包含最终醒来。",
])
def test_generated_product_descriptions_do_not_require_health_sources(task, text):
    assert not needs_health_for_task("介绍你的功能", text, QueryPlan(task=task), False)


@pytest.mark.parametrize("question", ["夜醒次数这个字段是什么意思？", "What does the night_awakenings field record?"])
def test_product_field_definition_is_not_a_health_question(question):
    result = ChatSession(None).ask(question)
    assert result["status"] == "answered" and "B1:" in result["answer"]
    assert not result["model_calls"] and not result["tool_events"]


def test_intro_plus_lookup_preserves_both_tasks():
    client = Client(lookup(WEEK), "本周平均睡眠390分钟。")
    result = ChatSession(client).ask("你是谁？顺便看看我这周平均睡多久", selected_query=WEEK)
    assert result["status"] == "answered"
    assert "SleepLens" in result["answer"] and "390" in result["answer"]
    assert result["tool_events"][0]["validated_arguments"] == WEEK


def test_intro_does_not_swallow_a_health_action_request():
    plan = plan_query("你可以解释夜醒吗？频繁夜醒该怎么改善？")
    assert not plan.application_dialogue and plan.wants_improvement
    assert needs_health_for_task("", "建议你减少下午的咖啡。", plan, False)


def test_field_explanation_does_not_consume_a_record_lookup():
    client = Client(lookup(DAY), "夜醒次数不包括最终醒来。[B1:Fields]这晚夜醒3次。")
    result = ChatSession(client).ask("夜醒次数这个字段是什么意思？顺便查我2026-10-22醒了几次", selected_query=DAY)
    assert result["status"] == "answered" and result["tool_events"]
    assert result["query_plan"]["task"] in {"records", "combined"}
    assert "3次" in result["answer"]


@pytest.mark.parametrize("question", [
    "我家有孩子，我自己的睡眠最近不好，该怎么办？",
    "I have a child, but my own sleep has been poor. How can I improve my sleep?",
])
def test_incidental_child_mention_does_not_block_the_adult(question):
    plan = plan_query(question)
    assert not plan.special_population
    assert plan.task in {"health", "combined"}


def test_child_sleep_gets_a_population_coverage_answer():
    result = ChatSession(None).ask("我家孩子最近睡不好，该怎么办？")
    assert result["status"] == "answered"
    assert not result["model_calls"] and "针对性依据" in result["answer"]


def test_mixed_population_keeps_the_adult_part_and_explains_child_scope():
    client = Client("现有资料未覆盖你描述的具体睡眠困扰，无法据此确认原因。")
    result = ChatSession(client).ask("我和孩子最近都睡不好，能分别解释一下吗？")
    assert result["status"] == "answered" and len(client.requests) == 1
    assert "孩子" in result["answer"] and "成人" in result["answer"]
    assert result["query_plan"]["population_scope"] == "mixed"


def test_ambiguous_population_asks_about_the_subject_without_model():
    result = ChatSession(None).ask("家里有孩子，最近睡不好，该怎么办？")
    assert not result["model_calls"]
    assert "谁" in result["answer"] or "你自己" in result["answer"]


@pytest.mark.parametrize("evidence,answer", [
    ("Adults need at least eight hours of sleep.", "成人睡眠参考是至少480分钟。"),
    ("Adults need at least 480 minutes of sleep.", "成人睡眠参考是至少8小时。"),
    ("Allow about seven hours and thirty minutes for sleep.", "睡眠参考约450分钟。"),
    ("Allow about 450 minutes for sleep.", "睡眠参考约7小时30分钟。"),
    ("A sleep interval of seven to nine hours.", "资料中的睡眠时长区间为420至540分钟。"),
    ("A sleep interval of 420 to 540 minutes.", "资料中的睡眠时长区间为7至9小时。"),
    ("No more than thirty minutes of napping.", "午睡最多半小时。"),
])
def test_equivalent_sleep_durations_preserve_qualifiers(evidence, answer):
    review = review_health_text(answer + "[H1:Test]", {"H1:Test": evidence})
    assert review.blocking_problem is None


@pytest.mark.parametrize("answer", ["最多480分钟", "最多8小时", "至少479分钟", "480分钟", "8小时", "约480分钟", "至少8分钟"])
def test_time_conversion_does_not_erase_or_reverse_a_lower_bound(answer):
    review = review_health_text("成人睡眠参考是" + answer + "。[H1:Test]",
                                {"H1:Test": "Adults need at least eight hours of sleep."})
    assert review.blocking_problem


def test_converted_reference_cannot_license_a_personal_measurement():
    search = ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "health", "type": "function", "function": {"name": "search_sleep_knowledge", "arguments": '{"query":"adult sleep duration"}'}}])
    client = Client(search, *["你的记录显示至少420分钟。[H1:AdultDuration]"] * 2)
    result = ChatSession(client).ask("一般成人睡眠要多久？")
    assert result["status"] != "answered" or "你的记录显示" not in result["answer"]


@pytest.mark.parametrize("question,scope", [
    ("我家有孩子但我自己的睡眠最近不好，该怎么办？", "adult"),
    ("I have a child and my own sleep is poor. How can I improve it?", "adult"),
    ("我怀孕了，我自己的睡眠最近不好，该怎么办？", "special"),
    ("我最近睡不好，孩子也一样，怎么办？", "mixed"),
    ("我家孩子最近睡不好，我该怎么办？", "special"),
])
def test_sleep_subject_is_resolved_within_clauses(question, scope):
    assert plan_query(question).population_scope == scope


@pytest.mark.parametrize("text", [
    "我可以展示深睡时长。建议你睡前服用3 mg褪黑素。",
    "夜醒次数这个字段记录中途醒来次数。你患有失眠。",
    "I can show deep sleep. You should avoid naps.",
])
def test_product_description_is_not_a_bypass_for_actions_or_diagnosis(text):
    assert needs_health_for_task("介绍功能", text, QueryPlan(task="capability"), False)


@pytest.mark.parametrize("answer,accepted", [
    ("一般18至60岁成人的每日睡眠参考是至少420分钟。[H1:AdultDuration]", True),
    ("一般18至60岁成人的每日睡眠参考是最多420分钟。[H1:AdultDuration]", False),
])
def test_converted_duration_and_qualifier_in_the_actual_agent(answer, accepted):
    search = ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "health", "type": "function", "function": {"name": "search_sleep_knowledge", "arguments": '{"query":"adult sleep duration"}'}}])
    result = ChatSession(Client(search, answer, answer)).ask("一般成人的每日睡眠时长参考是多少？")
    assert (result["status"] == "answered") is accepted


@pytest.mark.parametrize("query,record_text", [
    (WEEK, "390"),
    ({**WEEK, "start_date": "2026-11-09", "end_date": "2026-11-15"}, "没有可用"),
])
def test_partial_health_answer_does_not_hide_the_record_portion(query, record_text):
    search = {"id": "health", "type": "function", "function": {"name": "search_sleep_knowledge", "arguments": '{"query":"sleep routine"}'}}
    batch = lookup(query)
    batch.tool_calls.append(ChatCompletionMessage(role="assistant", tool_calls=[search]).tool_calls[0])
    bad = "本周平均睡眠999分钟。\n\n建议保持作息规律。[H2:Schedule]"
    result = ChatSession(Client(batch, bad, bad)).ask("查本周平均睡眠，给改善建议", selected_query=query)
    assert result["status"] == "answered" and result["answer_validation"]["status"] == "partial"
    assert record_text in result["verified_record_facts"] and "999" not in result["answer"]
    assert "保持作息" in result["answer"]


def test_no_data_explains_current_period_instead_of_reusing_values():
    query = {**WEEK, "start_date": "2026-11-09", "end_date": "2026-11-15"}
    bad = "你的记录睡了999分钟。"
    result = ChatSession(Client(lookup(query), bad, bad)).ask("查2026-11-09至2026-11-15平均睡眠", selected_query=query)
    assert "没有可用" in result["answer"] and "999" not in result["answer"]
    assert not result.get("verified_record_facts")


def empty_health_search(monkeypatch):
    def dispatch(name, args, **kwargs):
        if name == "search_sleep_knowledge":
            return {"status": "no_results", "passages": [], "query": args.get("query", "")}
        return dispatch_tool(name, args, **kwargs)
    monkeypatch.setattr("sleeplens.agent.dispatch_tool", dispatch)


def test_failed_advice_still_exposes_the_requested_verified_mean(monkeypatch):
    empty_health_search(monkeypatch)
    bad = "本周平均睡眠999分钟。建议你改变作息。"
    result = ChatSession(Client(lookup(WEEK), bad, bad)).ask(
        "查一下我这周的平均睡眠，并给改善建议", selected_query=WEEK)
    assert "390" in result["verified_record_facts"]
    assert "7/7" in result["verified_record_facts"]
    assert "建议" in result["answer"] and "999" not in result["answer"]
    assert "未通过核对的内容" not in result["answer"]


def test_verified_daily_results_survive_invalid_model_numbers(monkeypatch):
    empty_health_search(monkeypatch)
    bad = "每天都睡了999分钟。"
    result = ChatSession(Client(lookup(WEEK), bad, bad)).ask("逐夜列出这周睡眠时长", selected_query=WEEK)
    facts = result["verified_record_facts"]
    assert all(day in facts for day in ["2026-10-19", "2026-10-22", "2026-10-25"])
    assert "999" not in facts


def test_missing_health_evidence_does_not_spend_a_third_generation(monkeypatch):
    empty_health_search(monkeypatch)
    client = Client(lookup(WEEK), "本周平均睡眠390分钟。建议你改变作息。")
    result = ChatSession(client).ask("查本周平均睡眠，给改善建议", selected_query=WEEK)
    assert len(client.requests) == 2 and result.get("verified_record_facts")
    assert "建议" in result["answer"]


def test_current_profile_failure_never_reuses_historical_facts():
    client = Client(lookup(DAY), "这晚睡了410分钟。", lookup({**DAY, "profile_id": "P02", "start_date": "2026-11-23", "end_date": "2026-11-23"}), "你的记录睡了410分钟。")
    session = ChatSession(client)
    assert session.ask("P01在2026-10-22睡了多久？")["status"] == "answered"
    result = session.ask("改查P02在2026-11-23睡了多久？")
    assert not result.get("verified_record_facts") and "410" not in result["answer"]


def test_insufficient_comparison_has_no_fabricated_difference():
    query = {**WEEK, "profile_id": "P02", "compare_previous": True}
    bad = "本周比前一周少了30分钟。"
    result = ChatSession(Client(lookup(query), bad, bad)).ask("P02这周比前周变长还是变短？", selected_query=query)
    assert "差值" not in result.get("verified_record_facts", "") or "不足" in result["verified_record_facts"]
    assert "少了30" not in result["answer"]
    assert "少30" not in result.get("verified_record_facts", "")


def test_last_night_keeps_waking_date_and_explains_latest_supported_date():
    result = ChatSession(Client(lookup({**DAY, "start_date": "2026-11-23", "end_date": "2026-11-23"}),
                                "本轮记录读取失败，无法提供这晚的个人数值。")).ask("P01昨晚睡了多久？")
    assert result["query_plan"]["period"] == ("2026-11-23", "2026-11-23")
    assert "2026-11-22" in result["answer"]


def test_last_night_cutoff_is_explicit_even_when_the_model_honestly_abstains():
    query = {**DAY, "start_date": "2026-11-23", "end_date": "2026-11-23"}
    result = ChatSession(Client(lookup(query), "资料没有覆盖这一天，无法判断睡眠情况。")).ask("P01昨晚睡了多久？")
    assert "2026-11-22" in result["answer"]


def test_last_night_general_advice_keeps_the_explicit_record_cutoff():
    query = {**DAY, "start_date": "2026-11-23", "end_date": "2026-11-23"}
    batch = lookup(query)
    batch.tool_calls.append(ChatCompletionMessage(role="assistant", tool_calls=[{
        "id": "health", "type": "function", "function": {"name": "search_sleep_knowledge", "arguments": '{"query":"sleep routine"}'}}]).tool_calls[0])
    result = ChatSession(Client(batch, "建议保持作息规律。[H2:Schedule]")).ask("P01昨晚睡得怎样，给些改善建议？")
    assert result["status"] == "answered" and "2026-11-22" in result["answer"]
    assert "保持作息" in result["answer"] and not result.get("verified_record_facts")


def test_invalid_date_does_not_hide_an_independent_introduction():
    result = ChatSession(None).ask("你是谁？查一下2月30日")
    assert "SleepLens" in result["answer"] and "日期" in result["answer"]
    assert not result["model_calls"] and not result["tool_events"]


def test_non_numeric_claim_support_remains_a_documented_separate_gap():
    """A valid ID and matching quantities are not a semantic entailment check."""
    review = review_health_text("咖啡因会让神经恢复指数翻倍。[H2:Caffeine]",
                                {"H2:Caffeine": "Caffeine can affect sleep for up to eight hours."})
    assert review.blocking_problem is None


def test_public_ui_keeps_records_and_explains_the_unverified_advice(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    empty_health_search(monkeypatch)
    bad = "本周平均睡眠999分钟。建议你改变作息。"
    client = Client(lookup(WEEK), bad, bad)
    monkeypatch.setattr("sleeplens.dashboard.create_model", lambda: (client, Settings(api_key="offline")))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    app.chat_input[0].set_value("查一下我这周平均睡眠，并给改善建议").run()
    assert not app.exception
    shown = "\n".join(block.value for block in app.markdown)
    notices = "\n".join(block.value for block in app.warning)
    assert "390" in shown and "999" not in shown
    assert "建议" in notices and "未通过核对的内容" not in notices
