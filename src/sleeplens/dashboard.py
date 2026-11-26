"""Per-viewer dashboard state. Browsing never initializes an API client."""

import json
from datetime import timedelta
from pathlib import Path

from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.config import ConfigError, load_settings, load_share_settings
from sleeplens.data import parse_iso_date
from sleeplens.data import DETAIL_FIELDS
from sleeplens.llm import DeepSeekClient, ModelError
from sleeplens.telemetry import redact, save_share_event, save_turn
from sleeplens.onboarding import default_query


USABLE = {"ok", "partial_data", "no_data"}


def create_model():
    settings = load_settings()
    if not settings.has_api_key:
        raise ConfigError("请在服务器本地配置API key；无需在浏览器中输入密钥。")
    return DeepSeekClient(settings), settings


class DashboardSession:
    def __init__(self, *, model_factory=None, trace_folder=None):
        self._model_factory = model_factory or create_model
        self._trace_folder = trace_folder
        self._client = self._agent = self._settings = None
        self.turns = []
        self.selection = {}
        self.analysis = None
        initial = default_query()
        self.apply_selection(initial["profile_id"], initial["start_date"], initial["compare_previous"],
                             days=1 if initial["start_date"] == initial["end_date"] else 7)

    def reset_chat(self):
        if self._client is not None:
            self._client.close()
        self._client = self._agent = self._settings = None
        self.turns = []

    def apply_selection(self, profile_id: str, start_date: str, compare_previous: bool, *, days=7):
        if days not in {1, 7}:
            raise ValueError("Choose one day or seven days")
        if days == 1:
            compare_previous = False
        try:
            end_date = (parse_iso_date(start_date) + timedelta(days=days - 1)).isoformat()
        except (ValueError, TypeError, OverflowError):
            end_date = start_date
        query = dict(profile_id=profile_id, start_date=start_date, end_date=end_date, compare_previous=compare_previous)
        result = analyze_sleep(**query)
        self.analysis = result
        if result["status"] in USABLE:
            if query != self.selection:
                self.reset_chat()
            self.selection = query
        return result

    def send(self, question: str) -> dict:
        if self._agent is None:
            self._agent = ChatSession(self)
        result = self._agent.ask(question, selected_query=self.selection or None)
        result["request_timeout_seconds"] = self._settings.timeout_seconds if self._settings else None
        secrets = (self._settings.api_key,) if self._settings else ()
        # Redact known credential echoes before anything reaches the browser.
        result = json.loads(redact(json.dumps(result, ensure_ascii=False), secrets))
        for event in reversed(result["tool_events"]):
            output = event.get("result")
            if isinstance(output, dict) and "current" in output:
                self.analysis = output  # An error clears old cards rather than presenting stale figures.
                if output["status"] in USABLE:
                    self.selection = {"profile_id": output["profile_id"],
                                      "start_date": output["period"]["start_date"],
                                      "end_date": output["period"]["end_date"],
                                      "compare_previous": output["comparison_state"] != "not_requested"}
                break
        try:
            sharing = load_share_settings()
            if sharing.enabled:
                path = save_share_event(result, folder=self._trace_folder, retention_days=sharing.log_days)
            else:
                path = save_turn(result, base_url=self._settings.base_url if self._settings else None,
                                 requested_model=self._settings.model if self._settings else None,
                                 secrets=secrets, folder=self._trace_folder)
            result["trace_filename"] = Path(path).name
        except OSError:
            result["trace_warning"] = "The model ran, but its local trace could not be saved."
        self.turns.append(result)
        self.turns = self.turns[-12:]
        return result

    def complete(self, messages, tools, timeout):
        """Initialize the model only when the agent actually needs generation."""
        if self._client is None:
            try:
                self._client, self._settings = self._model_factory()
            except ConfigError:
                raise ModelError("The sleep question service is unavailable.") from None
        return self._client.complete(messages, tools, timeout=timeout)


def chart_rows(analysis: dict) -> list[dict]:
    rows = []
    for scope in ("current", "previous"):
        segment = 0
        for night, record in enumerate(analysis.get("daily_records", {}).get(scope) or [], 1):
            if not record["sleep_valid"]:
                segment += 1
            rows.append({"period": scope, "night": night, "date": record["record_date"],
                         "minutes": record["sleep_min"], "valid": record["sleep_valid"],
                         "state": record["record_state"], "segment": f"{scope}-{segment}",
                         **{name: record.get(name) for name in DETAIL_FIELDS}})
    return rows
