"""Version/resource and self-contained checks for the current working copy."""

import json
import runpy
import shutil
import socket
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from sleeplens.agent import ChatSession, PROMPT_VERSION
from sleeplens.business_skill import load_business_skill
from sleeplens.knowledge import load_knowledge
from sleeplens.llm import DeepSeekClient
from sleeplens.query_policy import plan_query


ROOT = Path(__file__).resolve().parents[1]


def test_test_suite_blocks_external_connections():
    with socket.socket() as connection, pytest.raises(AssertionError, match="network or paid model"):
        connection.connect(("192.0.2.1", 443))


def test_test_suite_blocks_production_model_requests():
    with pytest.raises(AssertionError, match="network or paid model"):
        DeepSeekClient.complete(None, [], [], timeout=1)


def test_current_runtime_versions_and_only_supported_prompt_are_packaged():
    session = ChatSession(object())
    skill = load_business_skill(plan_query("Explain my sleep records."))
    assert PROMPT_VERSION == session.prompt_version == "prompt-v1"
    assert skill.version == "3.6.0"
    assert load_knowledge().version == "sleep-knowledge-v1"
    prompts = files("sleeplens").joinpath("resources/prompts")
    assert sorted(p.name for p in prompts.iterdir() if p.name.endswith(".md")) == ["system_v1.md"]
    assert session.prompt.startswith("# SleepLens — prompt-v1")


def test_current_checks_work_without_historical_evidence(tmp_path):
    for directory in ("src/sleeplens/fixtures", "src/sleeplens/resources"):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    fixture = tmp_path / "tests/fixtures/weekly_response_style.json"
    fixture.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/fixtures/weekly_response_style.json", fixture)
    checker = runpy.run_path(str(ROOT / "scripts/check_current.py"))["run_checks"]
    checker.__globals__["ROOT"] = tmp_path
    checker.__globals__["SKILL"] = tmp_path / "src/sleeplens/resources/skills/sleep-analysis"
    report = checker()
    assert len(report["cases"]) == 12
    assert report["prompt_version"] == PROMPT_VERSION
    assert report["paid_model_requests"] == 0
    assert not (tmp_path / "artifacts").exists()


def test_check_cli_rejects_overwriting_an_existing_result_directory(tmp_path, monkeypatch):
    sentinel = tmp_path / "checks.json"
    sentinel.write_text('{"unchanged": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_current.py", "--output", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "scripts/check_current.py"), run_name="__main__")
    assert exc.value.code == 2
    assert json.loads(sentinel.read_text(encoding="utf-8")) == {"unchanged": True}
