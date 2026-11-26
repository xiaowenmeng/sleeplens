"""Offline analysis and sleep-assistant command line."""

import argparse
import json
import sys

from sleeplens import __version__
from sleeplens.agent import ChatSession
from sleeplens.analysis import analyze_sleep
from sleeplens.config import ConfigError, load_settings
from sleeplens.llm import DeepSeekClient, ModelError
from sleeplens.presentation import format_analysis
from sleeplens.knowledge import load_knowledge
from sleeplens.telemetry import redact, save_turn


def display(value: dict):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def show_turn(result: dict, settings, *, as_json=False):
    secrets = (settings.api_key,)
    if as_json:
        print(redact(json.dumps(result, ensure_ascii=False, indent=2), secrets))
    else:
        print("\n" + redact(result["answer"], secrets))
        for ref in result["citation_check"]["references"]:
            location = ref["source_url"] or ref["filename"]
            print(f"  [{ref['citation_id']}] {ref['title']} ({ref['version']}) — {location}")
        print(f"\n状态：{result['status']}；模型请求：{len(result['model_calls'])}；"
              f"工具请求：{len(result['tool_events'])}；tokens：{result['total_tokens']}；"
              f"耗时：{result['elapsed_seconds']:.2f}秒")
    try:
        path = save_turn(result, base_url=settings.base_url, requested_model=settings.model, secrets=secrets)
        print(f"记录：{path}")
    except OSError:
        print("模型已运行，但本地记录保存失败；不要因此重复付费请求。", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    # Windows terminals may default to a legacy encoding. Print Chinese safely.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="SleepLens：离线睡眠分析与问答")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查配置状态；不联网，不显示密钥")
    sub.add_parser("sources", help="查看知识包段落列表；不联网")
    ask = sub.add_parser("ask", help="单轮模型问答，会按量计费")
    ask.add_argument("question")
    ask.add_argument("--live", action="store_true", required=True, help="明确运行真实付费模型")
    ask.add_argument("--json", action="store_true", help="显示完整诊断结果（含公开系统指令和证据）")
    chat = sub.add_parser("chat", help="多轮终端对话，会按量计费")
    chat.add_argument("--live", action="store_true", required=True, help="明确运行真实付费模型")
    analysis = sub.add_parser("analyze", help="本地睡眠计算；不读取密钥、不调用模型")
    analysis.add_argument("--profile", required=True, help="P01 / P02 / P03")
    analysis.add_argument("--start", required=True, help="起始醒来日期，YYYY-MM-DD")
    analysis.add_argument("--end", required=True, help="结束醒来日期，YYYY-MM-DD")
    analysis.add_argument("--compare-previous", action="store_true", help="与前7天比较")
    analysis.add_argument("--json", action="store_true", help="输出完整结构化结果及逐夜数据")
    args = parser.parse_args(argv)
    if args.command == "sources":
        knowledge = load_knowledge()
        print(f"{knowledge.version} · 来源库 · {len(knowledge.references)}段")
        for ref in knowledge.references:
            print(f"[{ref['citation_id']}] {ref['title']} — {ref['source_url'] or ref['filename']}")
        return 0
    if args.command == "analyze":
        result = analyze_sleep(args.profile, args.start, args.end, args.compare_previous)
        if args.json:
            display(result)
        else:
            print(format_analysis(result))
        return 0 if result["status"] in {"ok", "partial_data", "no_data"} else 1
    try:
        settings = load_settings()
        if args.command == "doctor":
            display({
                "version": __version__,
                "python": sys.version.split()[0],
                "model": settings.model,
                "base_url": settings.base_url,
                "api_key_configured": settings.has_api_key,
                "timeout_seconds": settings.timeout_seconds,
                "network_called": False,
            })
            return 0
        if not settings.has_api_key:
            raise ConfigError("尚未配置 DEEPSEEK_API_KEY。请在项目 .env 中本地填写，勿发到聊天。")
        client = DeepSeekClient(settings)
        try:
            if args.command in {"ask", "chat"}:
                session = ChatSession(client)
                if args.command == "ask":
                    result = session.ask(args.question)
                    show_turn(result, settings, as_json=args.json)
                    return 0 if result["status"] == "answered" else 1
                print("SleepLens · 对话；/reset清空会话，/exit退出。")
                while True:
                    try:
                        question = input("\n你：").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n对话结束。")
                        return 0
                    if question == "/exit":
                        return 0
                    if question == "/reset":
                        session.reset()
                        print("会话已清空。")
                        continue
                    if question:
                        show_turn(session.ask(question), settings)
        finally:
            client.close()
        return 0
    except (ConfigError, ModelError) as exc:
        print(f"未通过：{exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print("未通过：本地文件、数据或响应格式异常；请检查安装并运行测试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
