"""Style-gate regressions with local evidence and a two-turn application replay."""

import runpy
from datetime import date
from pathlib import Path

import pytest

from sleeplens.analysis import analyze_sleep
from sleeplens.answer_validation import validate_interpretation, validate_record_text, validate_health_text
from sleeplens.knowledge import load_knowledge


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def week():
    return analyze_sleep("P01", "2026-11-20", "2026-11-26", True, today=date(2026, 12, 26))


@pytest.mark.parametrize("answer", [
    "本周平均每晚睡了约7小时26分钟，两周平均时长比较接近。",
    "你的本周和前周平均时长差不多。",
    "Your two weekly averages are similar.",
    "This week's shortest night was 23 November, with 5 hours 39 minutes of sleep.",
])
def test_natural_observation_needs_no_disclaimer(answer, week):
    assert validate_interpretation(answer, week) is None


@pytest.mark.parametrize("answer", [
    "这周的记录只能描述记录本身，不能据此判断原因或整体睡眠质量。",
    "Your records cannot establish a diagnosis.",
    "本周平均每晚446.3分钟。",
    "REM 是快速眼动睡眠。",
])
def test_limits_values_or_definitions_alone_do_not_complete_interpretation(answer, week):
    assert validate_interpretation(answer, week)


def test_weekly_style_does_not_relax_record_or_health_guards(week):
    assert validate_record_text("两周均值比较接近，本周平均每晚999分钟。", week,
                                require_summary=False, health_references={})
    refs = {p["citation_id"]: p["text"] for p in load_knowledge().references if p["source_id"].startswith("H")}
    for bad in ["你已经患有失眠。", "建议服用10毫克安眠药。", "成人最多睡7小时。[H1:AdultDuration]"]:
        assert validate_health_text(bad, refs, record_output=week)


def test_existing_week_input_and_chinese_followup_replay_without_model_calls():
    report = runpy.run_path(str(ROOT / "scripts/check_current.py"))["replay_week"]()
    assert report["expected_records_verified"]
    assert report["paid_model_requests"] == 0
