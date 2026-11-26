"""A missing incidental health source must not exhaust a valid record lookup."""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage

from sleeplens.agent import ChatSession


pytestmark = pytest.mark.usefixtures("regression_dataset")


QUESTION = "你好，帮我查询10月22日的睡眠情况"
DAY = dict(profile_id="P01", start_date="2026-10-22", end_date="2026-10-22", compare_previous=False)
SELECTED = dict(profile_id="P01", start_date="2026-10-19", end_date="2026-10-25", compare_previous=True)
# Current authored lookup candidate: facts without a routine disclaimer.
CANDIDATE = (
    "10月22日睡了6小时50分钟，00:00入睡，07:05最终醒来；"
    "中途记录到3次夜醒，累计清醒15分钟。\n\n"
    "深睡94分钟、浅睡218分钟、REM 98分钟。"
)
FACTS = (
    "10月22日记录睡眠6小时50分钟，00:00入睡，07:05最终醒来；"
    "中途醒来3次，清醒共15分钟。深睡94分钟、浅睡218分钟、REM 98分钟。"
)


class Client:
    def __init__(self, final, candidate=CANDIDATE):
        self.responses = [
            ChatCompletionMessage(role="assistant", tool_calls=[{
                "id": "record", "type": "function", "function": {
                    "name": "analyze_sleep", "arguments": json.dumps(DAY)}}]),
            ChatCompletionMessage(role="assistant", content=candidate),
            ChatCompletionMessage(role="assistant", content=final),
        ]
        self.requests = []

    def complete(self, messages, tools, timeout):
        self.requests.append(json.loads(json.dumps(messages)))
        return SimpleNamespace(model="offline-record-repair", usage=None, choices=[
            SimpleNamespace(message=self.responses.pop(0), finish_reason="stop")])


@pytest.mark.parametrize("unused_final", [
    FACTS,
    FACTS.replace("6小时50分钟", "9小时50分钟"),
    FACTS + "你的睡眠完全正常。",
])
def test_record_lookup_keeps_supported_blocks_without_regenerating_after_empty_search(monkeypatch, unused_final):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 14))
    # With no health evidence, retain checked paragraphs instead of requesting
    # a third candidate. Its unused contents must not affect the result.
    client = Client(unused_final, candidate=CANDIDATE + "你的睡眠完全正常。")
    session = ChatSession(client)
    result = session.ask(QUESTION, selected_query=SELECTED)
    assert result["status"] == "answered"
    assert len(client.requests) == 2
    assert len(result["tool_events"]) == 2
    assert result["tool_events"][0]["validated_arguments"] == DAY
    assert result["tool_events"][0]["result"]["status"] == "ok"
    assert result["tool_events"][1]["result"]["status"] == "no_results"
    assert result["answer_validation"]["status"] == "partial"
    assert "6小时50分钟" in result["answer"]
    assert "9小时50分钟" not in result["answer"] and "完全正常" not in result["answer"]
    assert len(client.responses) == 1  # No third generation is consumed or displayed.


def test_current_lookup_needs_no_disclaimer_or_repair(monkeypatch):
    monkeypatch.setattr("sleeplens.agent.berlin_today", lambda: date(2026, 11, 14))
    client = Client(FACTS)
    result = ChatSession(client).ask(QUESTION, selected_query=SELECTED)
    assert result["status"] == "answered" and result["answer"] == CANDIDATE
    assert len(client.requests) == 2 and len(result["tool_events"]) == 1
