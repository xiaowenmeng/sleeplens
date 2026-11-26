"""DeepSeek model adapter for the official or selected ChatAnywhere endpoint."""

import json
import queue
import threading
import time

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from sleeplens.config import Settings
from sleeplens.request_budget import BudgetError, RequestBudget


class ModelError(RuntimeError):
    """Safe public error: never display raw API bodies, headers or credentials."""


class DeepSeekClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._budget = RequestBudget(settings.budget_db, request_limit=settings.request_limit, max_concurrent=settings.max_concurrent)
        # No implicit retries: keep this first paid verification bounded.
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            max_retries=0,
        )

    def complete(self, messages: list[dict], tools: list[dict], timeout: float):
        deadline = time.monotonic() + min(timeout, self.settings.timeout_seconds)
        if timeout <= 0:
            raise ModelError("本轮剩余时间不足，未发送模型请求。")
        if len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False)) > self.settings.max_input_chars:
            raise ModelError("对话内容超过服务输入上限，请清空历史后重试。")
        budget = getattr(self, "_budget", None)  # __new__ is used only by offline adapter fixtures.
        try:
            reservation = budget.reserve() if budget else None
        except BudgetError as exc:
            raise ModelError(str(exc)) from None
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            if budget:
                budget.finish(reservation, "not_sent_deadline")
            raise ModelError("等待服务额度时已超时，未发送模型请求。")
        result_queue = queue.Queue(maxsize=1)
        expired = threading.Event()

        def request():
            status = "error"
            outcome = None
            try:
                if expired.is_set() or time.monotonic() >= deadline:
                    status = "not_sent_deadline"
                    return
                tool_options = {"tools": tools, "tool_choice": "auto"} if tools else {}
                response = self.client.chat.completions.create(
                    model=self.settings.model, messages=messages, **tool_options,
                    max_tokens=1200, temperature=0, timeout=max(.001, deadline-time.monotonic()),
                    extra_body={"thinking": {"type": "disabled"}})
                status = "completed_after_timeout" if expired.is_set() else "completed"
                outcome = (True, response)
            except Exception as exc:
                outcome = (False, exc)
            finally:
                if budget:
                    budget.finish(reservation, status)
                if outcome is not None:
                    result_queue.put(outcome)

        threading.Thread(target=request, daemon=True, name="sleeplens-model-request").start()
        try:
            try:
                success, value = result_queue.get(timeout=max(.001, deadline-time.monotonic()))
            except queue.Empty:
                expired.set()
                raise ModelError("模型请求达到等待时限；迟到结果将丢弃，本次不自动重试。") from None
            if success:
                return value
            raise value
        except AuthenticationError:
            raise ModelError("DeepSeek 认证失败，请在本地检查 API key。") from None
        except RateLimitError:
            raise ModelError("DeepSeek 请求限流（429），请稍后重试。") from None
        except APITimeoutError:
            raise ModelError("DeepSeek 请求超时；本次未自动重试。") from None
        except APIConnectionError:
            raise ModelError("无法连接 DeepSeek，请检查网络。") from None
        except APIStatusError as exc:
            if exc.status_code == 402:
                raise ModelError("模型服务余额不足，请检查当前平台账户余额。") from None
            if exc.status_code == 403:
                raise ModelError("当前平台拒绝访问（403），请检查该密钥的模型权限及额度。") from None
            raise ModelError(f"DeepSeek 返回 HTTP {exc.status_code}；本次未自动重试。") from None
        except APIError:
            raise ModelError("DeepSeek 响应无法正常解析；本轮验证未通过。") from None
        except ModelError:
            raise
        except Exception:
            raise ModelError("模型服务请求异常；本次未自动重试。") from None

    def close(self):
        self.client.close()
