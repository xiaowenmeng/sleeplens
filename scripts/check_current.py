"""Offline authored-dialogue checks; no production client or network allowed."""

import argparse
import itertools
import json
import re
from dataclasses import replace
from datetime import date, datetime, timezone
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openai.types.chat import ChatCompletionMessage

from sleeplens.agent import ChatSession, PROMPT_VERSION
from sleeplens.analysis import analyze_sleep
from sleeplens.answer_validation import validate_health_text, validate_record_text
from sleeplens.business_skill import TASK_SECTIONS, load_business_skill, reference_sections
from sleeplens.data import load_dataset
from sleeplens.knowledge import load_knowledge
from sleeplens.query_policy import plan_query
from sleeplens.record_grounding import normalize_record_format


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "src/sleeplens/resources/skills/sleep-analysis"
TODAY = date(2026, 11, 24)


class ScriptedClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0

    def complete(self, messages, tools, timeout):
        self.calls += 1
        try:
            item = next(self.replies)
        except StopIteration:
            raise AssertionError(f"Unexpected extra generation: {messages[-1]}") from None
        msg = ChatCompletionMessage(role="assistant", content=item) if isinstance(item, str) else item
        return SimpleNamespace(model="offline-authored-current", usage=None,
                               choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def calls(record=None, search=None):
    entries = []
    for name, arguments in [("analyze_sleep", record), ("search_sleep_knowledge", {"query": search} if search else None)]:
        if arguments:
            entries.append({"id": name, "type": "function", "function": {
                "name": name, "arguments": json.dumps(arguments)}})
    return ChatCompletionMessage(role="assistant", tool_calls=entries)


def query(profile="P01", start="2026-10-20", end=None, compare=False):
    return dict(profile_id=profile, start_date=start, end_date=end or start, compare_previous=compare)


def authored_answer(section, question):
    text = reference_sections((SKILL / "references/examples.md").read_text(encoding="utf-8"))[section]
    match = re.search(r"用户：" + re.escape(question) + r"\n助手：([^\n]+)", text)
    assert match, (section, question)
    return match[1]


def replay_week():
    """Check bilingual answers from a self-contained current data fixture."""
    fixture = json.loads((ROOT / "tests/fixtures/weekly_response_style.json").read_text(encoding="utf-8"))
    selection = fixture["selection"]
    expected = fixture["expected"]
    dataset = load_dataset(ROOT / "src/sleeplens/fixtures" / fixture["fixture"])
    with patch("sleeplens.analysis.load_dataset", return_value=dataset), \
         patch("sleeplens.agent.berlin_today", return_value=TODAY), \
         patch("sleeplens.analysis.berlin_today", return_value=TODAY), \
         patch("sleeplens.llm.DeepSeekClient.complete", side_effect=AssertionError("Paid model prohibited")), \
         patch("socket.socket.connect", side_effect=AssertionError("Network prohibited")):
        output = analyze_sleep(**selection, today=TODAY)
        assert math.isclose(output["current"]["mean_sleep_min"], expected["current_mean_sleep_min"])
        assert math.isclose(output["previous"]["mean_sleep_min"], expected["previous_mean_sleep_min"])
        assert output["current"]["valid_nights"] == output["previous"]["valid_nights"] == expected["valid_nights_each"]
        shortest = min((r for r in output["daily_records"]["current"] if r["sleep_valid"]), key=lambda r: r["sleep_min"])
        assert (shortest["record_date"], shortest["sleep_min"], shortest["awake_min"]) == (
            expected["shortest_date"], expected["shortest_sleep_min"], expected["shortest_awake_min"])
        client = ScriptedClient([calls(selection, "sleep quality"), fixture["english_candidate"], fixture["chinese_candidate"]])
        session = ChatSession(client)
        results = [session.ask(question, selected_query=selection) for question in fixture["questions"]]
    health = {r["citation_id"]: r["text"] for r in load_knowledge().references if r["source_id"].startswith("H")}
    for result, candidate in zip(results, [fixture["english_candidate"], fixture["chinese_candidate"]]):
        assert result["status"] == "answered" and result["answer"] == candidate
        assert not result["answer_validation"]["repairs"]
        assert not result.get("verified_record_facts")
        assert validate_record_text(candidate, output, require_summary=False, health_references=health) is None
        assert validate_health_text(candidate, health, record_output=output) is None
    assert client.calls == 3
    return {"case": "bilingual_week", "fixture": fixture["fixture"], "expected_records_verified": True,
            "prompt_version": session.prompt_version, "paid_model_requests": 0,
            "questions": fixture["questions"], "answers": [r["answer"] for r in results]}


def run_checks():
    reports = []
    cases = [
        ("lookup_only", "synthetic_sleep.json", "records", "10月20日睡了多久？只要数值，不要分析。", query(), None),
        ("single_day_analysis", "synthetic_sleep.json", "combined", "帮我分析10月21日的睡眠。", query(start="2026-10-21"), "night waking"),
        ("weekly_overview", "display_sleep.json", "combined", "分析所选这周，跟前周比怎么样？", query(start="2026-10-19", end="2026-10-25", compare=True), "sleep quality"),
        ("missing_record", "synthetic_sleep.json", "records", "这天醒了几次？", query(profile="P02", start="2026-10-24"), None),
        ("compound", "synthetic_sleep.json", "definition", "解释均值的分母规则，并告诉我所选这周平均睡多久。", query(start="2026-10-19", end="2026-10-25"), None),
    ]
    with patch("sleeplens.llm.DeepSeekClient.complete", side_effect=AssertionError("Paid model prohibited")), \
         patch("socket.socket.connect", side_effect=AssertionError("Network prohibited")), \
         patch("sleeplens.agent.berlin_today", return_value=TODAY), \
         patch("sleeplens.analysis.berlin_today", return_value=TODAY):
        for name, fixture, section, question, selection, search in cases:
            dataset = load_dataset(ROOT / "src/sleeplens/fixtures" / fixture)
            answer = authored_answer(section, question)
            client = ScriptedClient([calls(selection, search), answer])
            with patch("sleeplens.analysis.load_dataset", return_value=dataset):
                session = ChatSession(client)
                result = session.ask(question, selected_query=selection)
                assert result["status"] == "answered", (name, result.get("error"))
                if name == "missing_record":
                    assert result["reply_policy"]["category"] == "data_missing"
                    assert result["reply_policy"]["reason"] == "unavailable_record"
                    assert "2026-10-24" in result["answer"]
                else:
                    assert result["answer"] == normalize_record_format(answer), (name, result["answer"])
                assert not result["answer_validation"]["repairs"], (name, result["answer_validation"])
                assert not result.get("verified_record_facts")
                if name == "weekly_overview":
                    follow_question = "平均时长还可以，但我白天还是很困。"
                    follow_answer = authored_answer("combined", follow_question)
                    session.client = ScriptedClient([follow_answer])
                    follow_result = session.ask(follow_question, selected_query=selection)
                    assert follow_result["status"] == "answered" and follow_result["answer"] == follow_answer
                    assert not follow_result["answer_validation"]["repairs"]
                    reports.append({"case": "daytime_feedback", "type": "authored_scripted_replay", "answer": follow_answer})
                    gap_question = "能看出最短那晚为什么睡得短吗？"
                    gap_answer = authored_answer("combined", gap_question)
                    session.client = ScriptedClient([calls(search="zzzx-uncovered-evidence"), gap_answer])
                    gap_result = session.ask(gap_question, selected_query=selection)
                    assert gap_result["status"] == "answered" and gap_result["answer"] == gap_answer, gap_result
                    assert not gap_result["answer_validation"]["repairs"]
                    assert gap_result["tool_events"][0]["result"]["status"] == "no_results"
                    reports.append({"case": "knowledge_gap_with_records", "type": "authored_scripted_replay", "answer": gap_answer})
            reports.append({"case": name, "type": "authored_scripted_replay", "fixture": fixture,
                            "selection": selection, "answer": result["answer"], "model_calls_simulated": client.calls})

        # Multi-turn habit feedback uses only the current conversation.
        question = "怎样改善睡前习惯？"
        first = authored_answer("health", question)
        feedback = "上次你说可以少看亮屏，我试了两晚，醒来舒服一些，但下午还是困。"
        reply = authored_answer("followup", feedback)
        client = ScriptedClient([calls(search="wind down"), first, calls(search="sleep diary"), reply])
        session = ChatSession(client)
        assert session.ask(question)["status"] == "answered"
        result = session.ask(feedback)
        assert result["status"] == "answered" and result["answer"] == reply, result
        assert not result["answer_validation"]["repairs"]
        reports.append({"case": "reported_feedback", "type": "authored_scripted_replay", "answer": reply})

        for name, question, search in [
            ("habit_correction", "我不喝咖啡，你刚才理解错了。", "wind down"),
            ("deep_followup", "那晚深睡是不是太少了？", "deep sleep stages sleep quality"),
        ]:
            reply = authored_answer("followup", question)
            if name == "deep_followup":
                selection = query()
                client = ScriptedClient([calls(selection), "10月20日睡了6小时40分钟。", calls(search=search), reply])
                session = ChatSession(client)
                with patch("sleeplens.analysis.load_dataset", return_value=load_dataset(ROOT / "src/sleeplens/fixtures/synthetic_sleep.json")):
                    assert session.ask("查询10月20日睡多久", selected_query=selection)["status"] == "answered"
                    result = session.ask(question, selected_query=selection)
            else:
                session = ChatSession(ScriptedClient([calls(search=search), reply]))
                result = session.ask(question)
            assert result["status"] == "answered" and result["answer"] == reply, (name, result)
            assert not result["answer_validation"]["repairs"]
            reports.append({"case": name, "type": "authored_scripted_replay", "answer": reply})

        # Actual local tool failure; no old personal data can be resurrected.
        answer = authored_answer("records", "查一下10月20日的睡眠时长。")
        session = ChatSession(ScriptedClient([calls(query()), answer]))
        with patch("sleeplens.analysis.load_dataset", side_effect=OSError("offline injected read failure")):
            result = session.ask("查一下10月20日的睡眠时长。", selected_query=query())
        assert result["status"] == "error" and "读取失败" in result["answer"]
        assert result["tool_events"][0]["result"]["status"] == "tool_error"
        reports.append({"case": "tool_failure", "type": "application_owned_failure_with_injected_read_error",
                        "answer": result["answer"], "authored_example": answer})

    # Every section key is retained; test all loading combinations, including
    # compound rule requests that load an extra definition section.
    base = plan_query("Explain the selected sleep records, focusing on the most useful observations.")
    lengths = []
    for task, followup, sources, measurement, compound in itertools.product(TASK_SECTIONS, *([[False, True]] * 4)):
        plan = replace(base, task=task, followup=followup, focus_citations=(), compare_sources=sources,
                       include_rule_explanation=compound, topics=("night_waking",) if measurement else ())
        lengths.append(len(load_business_skill(plan).context))
    refs = {p["citation_id"]: p for p in load_knowledge().references}
    example_ids = set(re.findall(r"\[([BH]\d+:[A-Za-z0-9_-]+)\]", (SKILL / "references/examples.md").read_text(encoding="utf-8")))
    assert example_ids <= set(refs)
    with patch("sleeplens.analysis.load_dataset", return_value=load_dataset(ROOT / "src/sleeplens/fixtures/synthetic_sleep.json")):
        assert analyze_sleep(**query(), today=TODAY)["daily_records"]["current"][0]["deep_sleep_min"] == 84
    reports.append(replay_week())
    return {"paid_model_requests": 0, "real_model_quality_tested": False,
            "prompt_version": PROMPT_VERSION, "skill_version": load_business_skill(base).version,
            "knowledge_version": load_knowledge().version,
            "evidence_type": "developer-authored examples with real local tools and scripted model transport",
            "cases": reports, "loading_combinations": len(lengths), "maximum_context_chars": max(lengths),
            "citation_passages": {key: refs[key]["text"] for key in sorted(example_ids)},
            "semantic_review": "IDs and quantities checked automatically; claim support reviewed against these supplied passages, not independently graded"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check current SleepLens offline; never use a paid model.")
    parser.add_argument("--output", type=Path, help="New output directory; an existing directory is rejected.")
    args = parser.parse_args()
    destination = args.output or ROOT / "artifacts/checks" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if destination.exists():
        parser.error("Output directory already exists; historical results must not be overwritten.")
    report = run_checks()
    destination.mkdir(parents=True)
    (destination / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Passed {len(report['cases'])} authored dialogue cases; {report['loading_combinations']} loading combinations; 0 paid requests.")
    print(f"Results: {destination}")
