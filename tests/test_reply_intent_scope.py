"""Final answers follow the requested scope, even with overbroad model drafts."""

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
from sleeplens.query_policy import plan_query
from sleeplens.response_planning import refine_query_plan


DAY = dict(profile_id="P01", start_date="2026-10-22", end_date="2026-10-22", compare_previous=False)


class Client:
    def __init__(self, *items):
        self.items = list(items)

    def complete(self, messages, tools, timeout):
        assert self.items, "Unexpected model request"
        item = self.items.pop(0)
        msg = ChatCompletionMessage(role="assistant", content=item) if isinstance(item, str) else item
        return SimpleNamespace(model="offline-intent-regression", usage=None,
                               choices=[SimpleNamespace(message=msg, finish_reason="stop")])

    def close(self):
        pass


def evidence(args=DAY, search=False, proposal=None):
    args = {**args, **({"response_plan": proposal} if proposal else {})}
    calls = [{"id": "records", "type": "function", "function": {"name": "analyze_sleep", "arguments": json.dumps(args)}}]
    if search:
        calls.append({"id": "health", "type": "function", "function": {"name": "search_sleep_knowledge", "arguments": '{"query":"deep sleep stage distribution"}'}})
    return ChatCompletionMessage(role="assistant", tool_calls=calls)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 25))
    monkeypatch.setattr("sleeplens.analysis.berlin_today", lambda: date(2026, 11, 25))


def displayed(result):
    return result["answer"] + result.get("verified_record_facts", "")


@pytest.mark.parametrize("question", [
    "2026-10-22的深睡占比是多少？",
    "What was my deep sleep percentage on 2026-10-22?",
    "What percentage was deep-sleep on 2026-10-22?",
    "What was my deep sleep stage percentage on 2026-10-22?",
])
def test_lookup_is_one_sentence_without_health_boundary_or_extra_stage_table(question):
    draft = "深睡72分钟，总睡眠339分钟，占比21.2%。不过不能判断健康与否。[B1:ProductStages]"
    result = ChatSession(Client(evidence(), draft, draft)).ask(question, selected_query=DAY)
    row = analyze_sleep(**DAY)["daily_records"]["current"][0]
    text = displayed(result)
    assert f"{row['deep_sleep_min'] / row['sleep_min'] * 100:.1f}%" in text
    assert str(row["deep_sleep_min"]) in text and str(row["sleep_min"]) in text
    assert "|" not in text
    assert not any(word in text.lower() for word in ["正常", "健康", "依据", "normal", "evidence", "clinical", "rem", "light sleep", "浅睡", "可以", "i can"])
    assert not result["citation_check"]["references"]


@pytest.mark.parametrize("question", [
    "2026-10-22的深睡占比正常吗？",
    "Was my deep sleep percentage normal on 2026-10-22?",
])
def test_assessment_stops_after_values_current_evidence_limit_and_one_next_step(question):
    candidate = ("深睡已经达标。\n\n"
                 "Deep sleep tends to occur earlier in the night, so your deep sleep may reflect your late bedtime.[H6:Pattern]")
    result = ChatSession(Client(evidence(search=True), candidate, candidate)).ask(question, selected_query=DAY)
    text = displayed(result)
    assert "21.2%" in text and "72" in text and "339" in text
    assert "足够依据" in text or "enough evidence" in text
    assert not any(word in text.lower() for word in ["及格线", "universal", "earlier", "bedtime", "may reflect", "浅睡", "light sleep", "rem", "|", "supported part"])
    assert not result["citation_check"]["references"]
    assert result["calculations"] and len(result["calculations"]) == 1
    assert len([s for s in text.replace("。", ".").split(".") if s.strip()]) <= 5  # Includes the decimal separator.


@pytest.mark.parametrize("question", [
    "2026-11-20的深睡占比是多少？", "What was my deep sleep percentage on 2026-11-20?",
])
def test_no_records_names_the_requested_metric_and_date(question):
    args = {**DAY, "start_date": "2026-11-20", "end_date": "2026-11-20"}
    result = ChatSession(Client(evidence(args), "这天没有记录。", "这天没有记录。")).ask(question, selected_query=DAY)
    text = displayed(result)
    assert "2026-11-20" in text and ("深睡占比" in text or "deep sleep percentage" in text.lower())
    assert "2026-10-22" not in text and "0.0%" not in text and "|" not in text
    assert not result["citation_check"]["references"]
    from sleeplens.reply_policy import public_calculations
    assert not public_calculations(result)


@pytest.mark.parametrize("followup", [
    "那我这算失眠吗？", "Can you diagnose insomnia from my records?",
    "Does that mean I have insomnia?",
])
def test_diagnosis_followup_is_local_and_quotes_only_one_verified_fact(followup):
    client = Client(evidence(), "这晚睡眠339分钟。")
    session = ChatSession(client)
    assert session.ask("查2026-10-22睡了多久？", selected_query=DAY)["status"] == "answered"
    result = session.ask(followup, selected_query=DAY)
    text = displayed(result)
    assert result["reply_policy"]["category"] == "medical_boundary"
    assert not result["model_calls"] and not result["tool_events"]
    assert "5小时39分钟" in text or "5 hours 39 minutes" in text
    assert not any(word in text.lower() for word in ["missing fields", "three months", "diagnostic criteria", "上床", "缺少", "每周三", "|", "不能。"])
    assert len(text) < (170 if result["answer_language"] == "Chinese" else 450)


def test_model_refinement_cannot_expand_a_deep_only_request_to_all_stages():
    q = "Was my deep sleep percentage normal on 2026-10-22?"
    plan = plan_query(q, today=date(2026, 11, 25), selected_query=DAY)
    proposed = dict(intent="interpretation", metrics=["stages", "deep", "light", "rem"], evidence=["records", "knowledge"], answer_format="table")
    refined = refine_query_plan(plan, proposed, q)
    assert "deep" in refined.metrics and not set(refined.metrics) & {"stages", "light", "rem"}


def test_overbroad_proposal_does_not_expand_final_answer_or_visible_calculations():
    from sleeplens.reply_policy import public_calculations

    proposed = dict(intent="interpretation", metrics=["stages", "deep", "light", "rem", "awakenings"],
                    evidence=["records", "knowledge"], answer_format="table")
    result = ChatSession(Client(evidence(proposal=proposed))).ask(
        "Was my deep sleep percentage normal on 2026-10-22?", selected_query=DAY)
    assert len(result["model_calls"]) == 1 and len(result["calculations"]) == 1
    assert "|" not in displayed(result) and "Awakenings" not in displayed(result)
    details = json.dumps(public_calculations(result)).lower()
    assert "mean_light_sleep_min" not in details and "mean_rem_sleep_min" not in details


def test_following_general_knowledge_question_keeps_its_source_and_explanation():
    search = ChatCompletionMessage(role="assistant", tool_calls=[{"id": "health", "type": "function", "function": {
        "name": "search_sleep_knowledge", "arguments": '{"query":"deep sleep"}'}}])
    answer = "Deep sleep is a non-REM sleep stage.[H6:NREM]"
    session = ChatSession(Client(evidence(), search, answer))
    assert "21.2%" in session.ask("2026-10-22深睡占比多少？", selected_query=DAY)["answer"]
    result = session.ask("What is deep sleep?", selected_query=DAY)
    assert result["answer"] == answer and "calculations" not in result
    assert [r["citation_id"] for r in result["citation_check"]["references"]] == ["H6:NREM"]


def test_medical_followup_does_not_reuse_a_record_after_the_date_changes():
    session = ChatSession(Client(evidence(), "这晚睡眠339分钟。"))
    session.ask("查2026-10-22睡了多久？", selected_query=DAY)
    different = {**DAY, "start_date": "2026-10-23", "end_date": "2026-10-23"}
    result = session.ask("Can you diagnose insomnia from my records?", selected_query=different)
    assert "medical_record_fact" not in result and "339" not in result["answer"]


def test_full_distribution_is_still_available_when_explicitly_requested():
    result = ChatSession(Client(evidence(), "记录可供查看。", "记录可供查看。")).ask(
        "列出2026-10-22完整的睡眠阶段分布和占比。", selected_query=DAY)
    text = displayed(result)
    assert all(word in text for word in ["深睡", "浅睡", "REM", "|"])
    assert len(result["calculations"]) == 3


@pytest.mark.parametrize("nightly", [False, True])
def test_weekly_single_metric_is_compact_unless_nightly_values_are_requested(nightly):
    week = {**DAY, "start_date": "2026-10-19", "end_date": "2026-10-25"}
    question = "逐夜列出所选这周的深睡占比。" if nightly else "所选这周的深睡占比是多少？"
    result = ChatSession(Client(evidence(week))).ask(question, selected_query=week)
    rows = analyze_sleep(**week)["daily_records"]["current"]
    text = displayed(result)
    if nightly:
        assert len(result["calculations"]) == 7 and "|" in text
    else:
        expected = sum(r["deep_sleep_min"] for r in rows) / sum(r["sleep_min"] for r in rows) * 100
        assert f"{expected:.1f}%" in text and "|" not in text
        assert len(result["calculations"]) == 1 and len(result["calculations"][0]["contributing_dates"]) == 7
    assert "浅睡" not in text and "REM" not in text


def test_independently_requested_definition_survives_beside_limited_assessment():
    candidate = "你的深睡已达标。\n\n深睡属于非快速眼动睡眠阶段。[H6:NREM]"
    result = ChatSession(Client(evidence(search=True), candidate, candidate)).ask(
        "2026-10-22的深睡占比正常吗？另外解释深睡是什么。", selected_query=DAY)
    text = displayed(result)
    assert "21.2%" in text and "足够依据" in text and "深睡属于非快速" in text
    assert {r["citation_id"] for r in result["citation_check"]["references"]} == {"H6:NREM"}


def test_a_separate_rem_definition_does_not_add_a_rem_percentage():
    batch = evidence(search=True)
    batch.tool_calls[1].function.arguments = '{"query":"REM sleep"}'
    candidate = "Your deep sleep is normal.\n\nREM is a sleep phase associated with dreaming.[H6:REM]"
    result = ChatSession(Client(batch, candidate, candidate)).ask(
        "What was my deep sleep percentage on 2026-10-22, and what is REM sleep?", selected_query=DAY)
    assert len(result["calculations"]) == 1 and result["calculations"][0]["stage"] == "Deep sleep"
    assert "21.2%" in result["answer"] and "dreaming" in result["answer"] and "|" not in result["answer"]


def test_web_has_no_internal_partial_caption_or_unasked_stage_table(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    candidate = "深睡已经达标。\n\nDeep sleep is a non-REM sleep stage.[H6:NREM]"
    client = Client(evidence(search=True), candidate, candidate)
    monkeypatch.setattr("sleeplens.dashboard.create_model", lambda: (client, Settings(api_key="offline")))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=15).run()
    app.chat_input[0].set_value("Was my deep sleep percentage normal on 2026-10-22? Explain what deep sleep is.").run()
    assert not app.exception
    captions = "\n".join(x.value for x in app.caption)
    turn = app.session_state["dashboard"].turns[-1]
    assert turn["answer_validation"]["status"] == "partial"
    assert "supported part" not in captions.lower()
    assert "|" not in displayed(turn) and "earlier" not in displayed(turn)
    assert "Calculation & tool details" in [e.label for e in app.expander]
