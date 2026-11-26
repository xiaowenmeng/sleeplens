"""Conversation-first sleep companion with on-demand record analysis."""

import csv
import io
import json
import hashlib
import hmac
from datetime import date, timedelta

import pandas as pd
import altair as alt
import streamlit as st

from sleeplens.analysis import berlin_today
from sleeplens.config import ConfigError, load_share_settings
from sleeplens.dashboard import DashboardSession, chart_rows
from sleeplens.knowledge import load_knowledge
from sleeplens.reply_policy import public_calculations
from sleeplens.data import PROFILE_IDS
from sleeplens.onboarding import (
    COPY as GUIDE, data_catalogue, metric_rows, computed_rows, question_examples, classroom_examples,
)


APP_BEHAVIOR_REVISION = "display-data-v1-prompt-v30-first-use-v1"


TEXT = {
    "English": {
        "eyebrow": "BETTER NIGHTS START WITH UNDERSTANDING", "intro": "Understand your sleep. Find a routine that works for you.",
        "badge": "SLEEP COMPANION", "sample": "Synthetic course records", "choose": "Your record view",
        "profile": "Profile", "start": "First waking date", "end": "Seven nights, ending", "compare": "Compare previous 7 nights",
        "apply": "View records", "free": "Viewing records is free. A changed selection starts a fresh conversation.",
        "records_ready": "Records updated. The chart panel is now open on the main page.",
        "ai": "Sleep assistant", "ai_hint": "Ask about a pattern or get practical sleep advice.",
        "reset": "Clear conversation", "mean": "Average recorded sleep", "valid": "Valid nights", "coverage": "Record coverage",
        "change": "Change vs previous", "none": "No data", "not_requested": "Not requested", "not_comparable": "Not comparable",
        "min": "min", "chart": "Night by night", "chart_note": "Points show recorded minutes. Missing nights stay blank; lines stop at gaps.",
        "night": "Night in period", "minutes": "Recorded minutes", "current": "Selected period", "previous": "Previous period",
        "reading": "Reading this week", "missing": "A missing night is not zero sleep.",
        "insufficient": "Only part of this week is recorded, so a week-to-week change is not shown.",
        "limited": "The average uses nights with a valid record. Gaps may affect the comparison.",
        "descriptive": "Explore this change with the assistant, or ask for a plan for the week ahead.",
        "no_data": "No usable records are available for these dates. Check Data details for the current profile's coverage.",
        "records": "Daily records & download", "wake": "Waking date", "status": "Record status", "period": "Period",
        "valid_state": "Available", "unavailable_state": "Unavailable", "missing_state": "Missing record",
        "json": "Download analysis JSON", "csv": "Download daily CSV", "chat": "Talk about your sleep",
        "chat_intro": "Understand your nights, work through a sleep concern, or build a better routine.",
        "advice": "Help me sleep better", "advice_prompt": "I'd like to sleep better. What are a few practical changes I can start with?",
        "explain": "Explain these records", "metric": "What does this metric mean?", "followup": "Why can't these be compared?",
        "explain_prompt": "Explain the selected sleep records, focusing on the most useful observations.",
        "metric_prompt": "What does sleep_min mean, and does it measure sleep quality?",
        "followup_prompt": "Why can't these selected periods be compared? Is the four-night gate a medical standard?",
        "placeholder": "Tell me what's keeping you up, or ask about your sleep…", "thinking": "Checking records and evidence…",
        "welcome": "A little space for better sleep.", "record_panel": "Explore your sleep records",
        "send_hint": "Send a message to start · English or 中文", "usage_hint": "Only sending a question uses model credits.",
        "sources": "Sources behind this answer", "tools": "Calculation & tool details", "library": "Sleep knowledge library",
        "library_note": "Sources include CDC, NIH/NHLBI, NHS, AASM and scoped manufacturer documentation.",
        "structural": "Open the original source for more context.",
        "error": "The requested view could not be calculated.", "prompt_error": "AI explanations could not start. Check the server configuration.",
        "calls": "Model requests", "tokens": "Tokens", "seconds": "seconds", "tool_count": "Tool requests",
        "trace_error": "The model ran, but the local trace was not saved. Do not resend just to create a log.",
        "complete": "Complete records", "partial": "Partial records", "empty": "No usable records",
        "sleep_onset": "Sleep onset", "wake_time": "Final wake-up", "night_awakenings": "Night awakenings",
        "awake_min": "Awake minutes", "deep_sleep_min": "Deep sleep (min)", "light_sleep_min": "Light sleep (min)", "rem_sleep_min": "REM sleep (min)",
        "mean_onset": "Mean sleep onset", "mean_wake": "Mean final wake-up", "mean_awakenings": "Mean awakenings / night", "mean_awake": "Mean awake minutes / night",
        "stages": "Sleep stages by night", "stage_note": "Stage totals in minutes, not a timeline or a sleep-quality score. Missing records stay unavailable. Clock times use Europe/Berlin.",
    },
    "中文": {
        "eyebrow": "从了解睡眠，到找到更好的节奏", "intro": "看懂睡眠变化，找到适合你的改善方法。",
        "badge": "你的睡眠助手", "sample": "课程演示合成数据", "choose": "选择记录",
        "profile": "记录档案", "start": "首个醒来日期", "end": "连续七夜，结束于", "compare": "与前7夜比较",
        "apply": "查看记录", "free": "查看记录不调用模型。更改查询后会开始新的对话。",
        "records_ready": "记录已更新，主页面的图表已展开。",
        "ai": "睡眠助手", "ai_hint": "聊聊记录变化，或获取实用的睡眠建议。", "reset": "清空对话",
        "mean": "有效记录平均时长", "valid": "有效夜数", "coverage": "记录覆盖率", "change": "与前期的差值",
        "none": "无数据", "not_requested": "未请求比较", "not_comparable": "不可比较", "min": "分钟",
        "chart": "逐夜记录", "chart_note": "每个点表示记录的分钟数。缺失位置留空，线条在缺口处断开。",
        "night": "这一周的第几夜", "minutes": "记录时长（分钟）", "current": "所选一周", "previous": "此前一周",
        "reading": "如何理解这一周", "missing": "没有记录，不等于没有睡觉。",
        "insufficient": "这周只有部分夜晚有记录，暂不展示周与周之间的变化。",
        "limited": "均值根据有记录的夜晚计算，缺失情况可能影响比较。",
        "descriptive": "可以继续问问这段变化，或一起制定接下来一周的睡眠计划。",
        "no_data": "这些日期没有可用记录，可在数据详情中查看当前档案的日期覆盖。",
        "records": "每日记录与下载", "wake": "醒来日期", "status": "记录状态", "period": "周期",
        "valid_state": "有效", "unavailable_state": "不可用", "missing_state": "缺少记录",
        "json": "下载分析 JSON", "csv": "下载每日 CSV", "chat": "聊聊你的睡眠",
        "chat_intro": "看懂一段变化，聊聊睡不好的困扰，或从今晚开始做一点调整。",
        "advice": "给我睡眠建议", "advice_prompt": "我想改善睡眠，可以先从哪些具体、容易坚持的调整开始？",
        "explain": "解读这些记录", "metric": "这个指标是什么意思？", "followup": "为什么不能比较？",
        "explain_prompt": "请解读已选择的睡眠记录，重点说说值得关注的变化。",
        "metric_prompt": "sleep_min是什么意思？它能衡量睡眠质量吗？",
        "followup_prompt": "为什么这两个周期不能比较？至少4夜是医学标准吗？",
        "placeholder": "最近睡得怎么样？聊聊你的困扰，或问问睡眠记录…", "thinking": "正在核对记录和资料…",
        "welcome": "今晚，从好好聊聊开始。", "record_panel": "查看我的睡眠记录",
        "send_hint": "发送消息，开始对话 · 支持中文与 English", "usage_hint": "仅在发送问题时使用模型额度。",
        "sources": "参考依据", "tools": "计算依据与工具结果", "library": "睡眠知识库",
        "library_note": "包含CDC、NIH/NHLBI、NHS、AASM及注明适用产品的厂商说明。",
        "structural": "可以打开原文了解更多背景。",
        "error": "无法计算所请求的记录。", "prompt_error": "AI 解读未能启动，请检查服务器配置。",
        "calls": "模型请求", "tokens": "Tokens", "seconds": "秒", "tool_count": "工具请求",
        "trace_error": "模型已运行，但日志保存失败。不要仅为补日志而重复发送。",
        "complete": "完整记录", "partial": "部分记录", "empty": "无可用记录",
        "sleep_onset": "入睡时刻", "wake_time": "最终醒来时刻", "night_awakenings": "夜间醒来次数",
        "awake_min": "夜间清醒分钟数", "deep_sleep_min": "深睡（分钟）", "light_sleep_min": "浅睡（分钟）", "rem_sleep_min": "REM（分钟）",
        "mean_onset": "平均入睡时刻", "mean_wake": "平均最终醒来时刻", "mean_awakenings": "平均每晚夜醒次数", "mean_awake": "平均每晚清醒分钟数",
        "stages": "逐夜睡眠阶段", "stage_note": "展示各阶段总分钟数，不代表阶段发生顺序或睡眠质量评分。缺失记录不补零；时刻使用Europe/Berlin当地时间。",
    },
}

CSS = """
<style>
.stApp { background: #f8f7f3; color: #263d37; }
[data-testid="stHeader"] { background: rgba(248,247,243,.94); }
[data-testid="stSidebar"] { background: #eeefe9; border-right: 1px solid #dfe3d9; }
.block-container { max-width: 960px; padding-top: 2.5rem; padding-bottom: 3rem; }
h1, h2, h3 { color: #263d37; letter-spacing: -.035em; }
h1 { font-size: clamp(2rem, 4vw, 3rem) !important; font-weight: 500 !important; line-height:1.25 !important; }
h3 { font-size: 1.1rem !important; font-weight:600 !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #68786d; }
.st-key-hero { padding: .6rem 0 .2rem; }
.st-key-hero h1 { margin: .7rem 0; }
.st-key-hero h1, .st-key-hero p { text-align:left; }
.st-key-hero [data-testid="stCaptionContainer"] { letter-spacing:.1em; }
.brand { display:flex; align-items:center; gap:.65rem; font-size:1.1rem; font-weight:650; letter-spacing:-.035em; }
.brand-mark { display:inline-grid; place-items:center; width:32px; height:32px; border-radius:50%; background:#dce7db; color:#36574a; font-size:1.4rem; }
.night-disc { position:relative; width:68px; height:68px; background:#36574a; border-radius:50%; margin:0 auto 1.5rem; }
.night-disc::after { content:""; position:absolute; width:58px; height:58px; border-radius:50%; background:#f8f7f3; top:-7px; right:-9px; }
.st-key-suggestions { margin: .4rem 0 1.2rem; }
.st-key-suggestions button { background:#fffefa; border:1px solid #dce1d7; min-height:44px; color:#36574a; text-align:left; box-shadow:0 3px 9px #263d3704; }
.st-key-suggestions button:hover { background:#eef2e9; border-color:#8ba28e; color:#263d37; }
[data-testid="stMetric"] { background:#fffefa; border:1px solid #e0e4da; border-radius:14px; padding:1rem; min-height:110px; }
[data-testid="stMetricLabel"] { color:#68786d; font-size:.8rem; }
[data-testid="stMetricValue"] { color:#36574a; font-size:1.45rem; font-weight:600; }
[data-testid="stChatMessage"] { background:#eeefe9; border-radius:18px; padding:1.25rem; margin-bottom:.8rem; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) { background:#fffefa; border:1px solid #e0e4da; }
[data-testid="stButton"] button { border-radius:12px; transition:background .15s, border-color .15s; }
[data-testid="stChatInput"] { border-radius:22px; border:1px solid #b9c8b9; background:#fffefa; box-shadow:0 6px 24px #263d3709; }
[data-testid="stChatInput"]:focus-within { border-color:#36574a; box-shadow:0 0 0 3px #36574a15; }
[data-testid="stBottom"] > div { background:#f8f7f3; }
[data-testid="stBottomBlockContainer"] { max-width:960px; margin:auto; }
.st-key-apply_selection button { background:#36574a; color:#fff; border:none; }
.st-key-apply_selection button:hover { background:#294438; color:#fff; }
[data-testid="stExpander"] { background:#fffefa; border-radius:14px; border-color:#e0e4da; }
.st-key-record_panel { margin-top:1.5rem; }
@media (max-width:640px) {
 .block-container { padding-top:3rem; padding-left:1rem; padding-right:1rem; }
 .st-key-hero { padding:1.5rem 0 .5rem; }
 .st-key-hero h1 { font-size:1.7rem !important; }
 .night-disc { width:48px; height:48px; margin-bottom:1rem; }
 .night-disc::after { width:42px; height:42px; }
 .st-key-topbar [data-testid="stHorizontalBlock"] { display:grid; grid-template-columns:minmax(0,1fr) 110px; align-items:center; }
 .st-key-topbar [data-testid="stColumn"] { width:100% !important; min-width:0 !important; }
 .st-key-suggestions button { min-height:48px; }
 .st-key-suggestions [data-testid="stHorizontalBlock"] { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.5rem; }
 .st-key-suggestions [data-testid="stColumn"] { width:100% !important; min-width:0 !important; }
 .st-key-metrics [data-testid="stHorizontalBlock"] { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.65rem; }
 .st-key-metrics [data-testid="stColumn"] { width:100% !important; min-width:0 !important; }
 [data-testid="stMetric"] { padding:.9rem; min-height:96px; }
 [data-testid="stMetricValue"] { font-size:1.35rem; }
}
</style>
"""


def _change_language():
    st.session_state["ui_language"] = st.session_state["header_language"]


def _sync_controls(view):
    if st.session_state.pop("sync_controls", False):
        if not view.selection:
            return
        st.session_state["record_profile"] = view.selection["profile_id"]
        st.session_state["record_start"] = date.fromisoformat(view.selection["start_date"])
        st.session_state["record_compare"] = view.selection["compare_previous"]
        st.session_state["record_span"] = 1 if view.selection["start_date"] == view.selection["end_date"] else 7


def _chart(result, text):
    rows = chart_rows(result)
    if not any(row["valid"] for row in rows):
        st.info(text["no_data"])
        return
    data = [{**row, "label": text[row["period"]]} for row in rows]
    nights = result["current"]["expected_nights"]
    chart = alt.Chart(pd.DataFrame(data)).transform_filter(alt.datum.valid == True).mark_line(
        point=alt.OverlayMarkDef(size=65, filled=True), strokeWidth=2.4,
    ).encode(
        x=alt.X("night:Q", title=text["night"], scale=alt.Scale(domain=[1, nights] if nights > 1 else [.5, 1.5]), axis=alt.Axis(values=list(range(1, nights + 1)), grid=False)),
        y=alt.Y("minutes:Q", title=text["minutes"], scale=alt.Scale(zero=True)),
        color=alt.Color("label:N", title=None, scale=alt.Scale(domain=[text["current"], text["previous"]], range=["#36574a", "#b5a17b"]), legend=alt.Legend(orient="bottom")),
        detail="segment:N",
        tooltip=[alt.Tooltip("label:N", title=text["period"]), alt.Tooltip("date:N", title=text["wake"]), alt.Tooltip("minutes:Q", title=text["minutes"])],
    ).properties(height=250).configure_view(stroke=None).configure_axis(labelColor="#6a748d", titleColor="#6a748d", gridColor="#e9ecf5", titleFontWeight="normal")
    st.altair_chart(chart, width="stretch")


def _statistics(result, text):
    if result["current"] is None:
        st.info("记录视图暂时不可用，你仍可以阅读使用说明或了解指标含义。" if text is TEXT["中文"] else
                "The record view is temporarily unavailable. You can still read the guide or ask about metric meanings.")
        return
    current = result["current"]
    nights = current["expected_nights"]
    if nights == 1:
        zh = text is TEXT["中文"]
        text = dict(text)
        text.update(dict(zip(["mean", "mean_onset", "mean_wake", "mean_awakenings", "mean_awake", "reading"],
                             ["睡眠时长", "入睡时刻", "最终醒来", "夜醒次数", "夜间清醒分钟数", "当天记录"] if zh else
                             ["Sleep duration", "Sleep onset", "Final wake-up", "Awakenings", "Awake minutes", "This night's record"])))
        text["limited"] = "仅展示该醒来日期的记录；单日数据不能代表长期睡眠状况。" if zh else "This record describes only the specified waking date, not a long-term sleep pattern."
        text["chart"] = "当天睡眠时长" if zh else "This night's duration"
        text["stages"] = "当天睡眠阶段" if zh else "This night's stages"
    mean = text["none"] if current["mean_sleep_min"] is None else f"{current['mean_sleep_min']:.1f} {text['min']}"
    state = result["comparison_state"]
    change = (f"{result['difference_min']:+.1f} {text['min']}" if state == "available"
              else text["not_comparable"] if state == "insufficient_data" else text["not_requested"])
    with st.container(key="metrics"):
        columns = st.columns(4)
        for column, label, value in zip(columns, [text["mean"], text["valid"], text["coverage"], text["change"]],
                                        [mean, f"{current['valid_nights']}/{nights}", f"{current['coverage']:.1%}", change]):
            column.metric(label, value)
    st.write("")
    if current.get("detail_nights", 0):
        columns = st.columns(4)
        for column, label, key in zip(columns, ["mean_onset", "mean_wake", "mean_awakenings", "mean_awake"],
                                      ["mean_sleep_onset", "mean_wake_time", "mean_night_awakenings", "mean_awake_min"]):
            value = current[key]
            column.metric(text[label], value if isinstance(value, str) else f"{value:.1f}")
        st.caption(f"{current['detail_nights']}/{nights} · Europe/Berlin")
    if any(w["code"] == "zero_value_requires_verification" for w in result["warnings"]):
        st.warning("有效0分钟记录需核验，不能据此认定整夜未睡。" if text["min"] == TEXT["中文"]["min"]
                   else "A valid zero-minute record needs verification; it does not establish that no sleep occurred.")
    left, right = st.columns([2.1, 1], gap="large")
    with left, st.container(border=True):
        st.subheader(text["chart"])
        st.caption(text["chart_note"])
        _chart(result, text)
    with right, st.container(border=True):
        st.subheader(text["reading"])
        if state == "insufficient_data":
            st.info(text["insufficient"])
        elif state == "available":
            st.markdown(f"**{text['change']} · {change}**")
            st.write(text["descriptive"])
        else:
            st.write(text["limited"])
        if result["previous"] is not None:
            previous = result["previous"]
            previous_mean = text["none"] if previous["mean_sleep_min"] is None else f"{previous['mean_sleep_min']:.1f} {text['min']}"
            st.caption(f"{text['previous']}: {previous['valid_nights']}/7 · {previous['coverage']:.1%} · {previous_mean}")
        if any(w["code"] == "incomplete_coverage" for w in result["warnings"]):
            st.markdown(f"**{text['missing']}**")
            st.caption(text["limited"])
    rows = chart_rows(result)
    stage_rows = [{"date": row["date"], "stage": text[field], "minutes": row[field]}
                  for row in rows if row["period"] == "current" and row.get("deep_sleep_min") is not None
                  for field in ("deep_sleep_min", "light_sleep_min", "rem_sleep_min")]
    if stage_rows:
        st.subheader(text["stages"])
        st.caption(text["stage_note"])
        chart = alt.Chart(pd.DataFrame(stage_rows)).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("date:O", title=text["wake"]), y=alt.Y("minutes:Q", stack="zero", title=text["minutes"]),
            color=alt.Color("stage:N", title=None, scale=alt.Scale(
                domain=[text[field] for field in ("deep_sleep_min", "light_sleep_min", "rem_sleep_min")],
                range=["#36574a", "#b8c9ae", "#b5a17b"]), legend=alt.Legend(orient="bottom")),
            tooltip=[alt.Tooltip("date:O", title=text["wake"]), alt.Tooltip("stage:N", title=text["stages"]), alt.Tooltip("minutes:Q", title=text["minutes"])],
        ).properties(height=210).configure_view(stroke=None)
        st.altair_chart(chart, width="stretch")
    records = [{text["period"]: text[r["period"]], text["wake"]: r["date"], text["minutes"]: r["minutes"],
                text["status"]: text[{"valid": "valid_state", "unavailable_record": "unavailable_state", "missing_record": "missing_state"}[r["state"]]],
                **{text[field]: r.get(field) for field in ("sleep_onset", "wake_time", "night_awakenings", "awake_min", "deep_sleep_min", "light_sleep_min", "rem_sleep_min")}} for r in rows]
    with st.expander(text["records"]):
        st.dataframe(records, hide_index=True, width="stretch")
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(records[0]) if records else [])
        writer.writeheader()
        writer.writerows(records)
        a, b = st.columns(2)
        a.download_button(text["json"], json.dumps(result, ensure_ascii=False, indent=2), file_name="sleeplens-analysis.json", mime="application/json")
        b.download_button(text["csv"], output.getvalue().encode("utf-8-sig"), file_name="sleeplens-daily.csv", mime="text/csv")


def _turn(turn, text):
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        stage_fallback = (turn.get("answer_validation") or {}).get("fallback") == "stage_assessment"
        if turn["status"] == "answered" or stage_fallback:
            if turn.get("verified_record_facts"):
                st.caption("本轮已核实的记录（查询部分）" if text is TEXT["中文"] else "Verified records for this request")
                st.markdown(turn["verified_record_facts"])
            # Keyword-based prose review remains in diagnostics; it is not a
            # failed lookup or evidence of missing subjective experience.
            availability = turn.get("record_availability") or {}
            if availability.get("message") and not turn.get("reply_policy"):
                st.caption(availability["message"])
            answer = turn["answer"]
            for number, ref in enumerate(turn["citation_check"]["references"], 1):
                answer = answer.replace(f"[{ref['citation_id']}]", f"[{number}]")
            st.markdown(answer)
        else:
            plan = turn.get("query_plan") or {}
            records_only = (bool(turn.get("verified_record_facts")) and plan.get("task") == "records"
                            and not any(plan.get(key) for key in (
                                "wants_analysis", "sleep_overview", "personal_assessment", "wants_improvement")))
            if not records_only:
                if not turn.get("reply_policy") and text is TEXT["English"] and (turn.get("error") or {}).get("code") == "model_error":
                    st.warning("AI could not finish this request. Your record view is still available.")
                else:
                    st.warning(turn["answer"])
            if turn.get("verified_record_facts"):
                st.markdown(turn["verified_record_facts"])
        refs = turn["citation_check"]["references"]
        if refs:
            with st.expander(text["sources"]):
                for number, ref in enumerate(refs, 1):
                    st.markdown(f"**[{number}] {ref['title']}**")
                    st.caption(f"{ref['version']} · checked {ref['checked_at']}")
                    st.write(ref["text"])
                    if ref["source_url"]:
                        st.link_button(ref["source_id"] + " · original", ref["source_url"])
                st.caption(text["structural"])
        calculations = public_calculations(turn)
        if calculations:
            with st.expander(text["tools"]):
                for calculation in calculations:
                    st.json(calculation, expanded=False)
        if turn.get("trace_warning"):
            st.caption(text["trace_error"])


def _prepare_example(question):
    # Native chat_input prefill is a one-shot frontend update, not a submission.
    st.session_state["chat_question"] = question


def _first_use_header(info, language, has_turns):
    guide = GUIDE[language]
    if not has_turns:
        with st.container(key="hero"):
            st.write(guide["intro"])
    if info["status"] != "ok":
        st.info(guide[info["issue"]])


def _example_buttons(info, language, selection):
    examples = question_examples(info, language, selection)
    if examples:
        with st.container(key="suggestions"):
            columns = st.columns(3)
            for index, example in enumerate(examples):
                columns[index % 3].button(example["label"], key="example_" + example["id"],
                    help=example["question"], on_click=_prepare_example, args=(example["question"],), width="stretch")


def _first_use_details(info, language):
    guide = GUIDE[language]
    with st.expander(guide["data"]):
        if info["status"] != "ok":
            st.write(guide[info["issue"]])
        else:
            st.write(guide["source_counts"].format(rows=info["record_rows"], unique=info["unique_dates"],
                     calendar=info["calendar_days"], complete=info["complete_detail_nights"]))
            st.write(guide["date_rule"])
            st.write(guide["data_rule"])
            with st.expander(guide["date_lists"]):
                for label, key in [("missing", "missing_dates"), ("unavailable", "unavailable_dates"),
                                   ("incomplete", "incomplete_dates"), ("duplicates", "duplicate_dates")]:
                    st.write(f"{guide[label]}: " + (", ".join(info[key]) or guide["none"]))
            st.markdown("**" + guide["raw"] + "**")
            raw = metric_rows(info, language)
            if raw:
                st.table(pd.DataFrame([{guide["metric"]: r["name"], guide["meaning"]: r["meaning"], guide["unit"]: r["unit"]} for r in raw]))
            st.markdown("**" + guide["computed"] + "**")
            computed = computed_rows(info, language)
            if computed:
                st.table(pd.DataFrame(computed, columns=[guide["metric"], guide["meaning"], guide["unit"]]))
            st.caption(guide["not_recorded"])
    with st.expander(guide["about"]):
        st.write(guide["about_text"])
    with st.expander(guide["classroom"]):
        st.caption(guide["classroom_hint"])
        for example in classroom_examples(info, language):
            st.button(guide["labels"][example["id"]], key="classroom_" + example["id"],
                      help=example["question"], on_click=_prepare_example, args=(example["question"],))
            st.code(example["question"], language=None)


def main():
    st.set_page_config(page_title="SleepLens · Sleep companion", page_icon="🌙", layout="wide", initial_sidebar_state="collapsed")
    try:
        sharing = load_share_settings()
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    if sharing.enabled:
        digest = hashlib.sha256(sharing.password.encode()).hexdigest()
        if st.session_state.get("share_authenticated") != digest:
            st.title("SleepLens · Shared preview")
            with st.form("share_login"):
                password = st.text_input("Access password", type="password", key="share_access_input")
                submitted = st.form_submit_button("Enter")
            if submitted:
                if hmac.compare_digest(password, sharing.password):
                    st.session_state["share_authenticated"] = digest
                    st.rerun()
                st.error("Incorrect access password")
            st.stop()
        st.session_state.pop("share_access_input", None)
        if not st.session_state.get("share_notice_accepted"):
            st.title("SleepLens · Shared preview")
            st.info(f"This preview uses synthetic records. Use fictional scenarios only. Questions are sent to the configured third-party model service; metadata-only logs are retained for {sharing.log_days} days.")
            consent = st.checkbox("I understand", key="share_consent")
            if st.button("Start testing", disabled=not consent):
                st.session_state["share_notice_accepted"] = True
                st.rerun()
            st.stop()
    st.markdown(CSS, unsafe_allow_html=True)
    if "dashboard" not in st.session_state or st.session_state.get("product_revision") != APP_BEHAVIOR_REVISION:
        previous = st.session_state.get("dashboard")
        if previous is not None:
            previous.reset_chat()
        st.session_state["dashboard"] = DashboardSession()
        if previous is not None and previous.selection:
            st.session_state["dashboard"].apply_selection(previous.selection["profile_id"], previous.selection["start_date"], previous.selection["compare_previous"], days=1 if previous.selection["start_date"] == previous.selection["end_date"] else 7)
            st.session_state["sync_controls"] = True
        st.session_state["product_revision"] = APP_BEHAVIOR_REVISION
    view = st.session_state["dashboard"]
    _sync_controls(view)
    initial_start = view.selection.get("start_date")
    st.session_state.setdefault("record_start", date.fromisoformat(initial_start) if initial_start else None)
    st.session_state.setdefault("record_compare", view.selection.get("compare_previous", False))
    st.session_state.setdefault("record_span", 1 if view.selection.get("start_date") == view.selection.get("end_date") else 7)
    with st.sidebar:
        st.markdown("### ◔ SleepLens")
        language = st.selectbox("Language / 语言", ["English", "中文"], key="ui_language")
        text = TEXT[language]
        st.divider()
        st.subheader(text["choose"])
        span = st.selectbox("查询范围" if language == "中文" else "Record range", [7, 1],
                            format_func=lambda value: ("单日" if value == 1 else "连续七天") if language == "中文" else ("One day" if value == 1 else "Seven days"), key="record_span")
        with st.form("record_selection"):
            profile = st.selectbox(text["profile"], PROFILE_IDS, key="record_profile")
            start = st.date_input(text["start"], value=None, min_value=min(date(2026, 1, 1), st.session_state["record_start"] or date(2026, 1, 1)),
                                  max_value=max(berlin_today() - timedelta(days=span), st.session_state["record_start"] or date.min), format="YYYY-MM-DD", key="record_start")
            st.caption(("只查询指定的醒来日期。" if language == "中文" else "Queries only the specified waking date.") if span == 1 else ("查询包含起始日及之后六天。" if language == "中文" else "Includes the start date and the following six dates."))
            compare = st.checkbox(text["compare"], key="record_compare", disabled=span == 1)
            apply = st.form_submit_button(text["apply"], key="apply_selection", width="stretch")
        st.caption(text["free"])
        if apply:
            if start is None:
                st.warning("请选择一个起始日期。" if language == "中文" else "Choose a first waking date.")
            else:
                view.apply_selection(profile, start.isoformat(), compare, days=span)
                st.session_state["records_expanded"] = True
                st.success(text["records_ready"])
        st.divider()
        st.caption(text["usage_hint"])
        if st.button(text["reset"], key="reset_chat", width="stretch"):
            view.reset_chat()
        with st.expander(text["library"]):
            st.caption(text["library_note"])
            try:
                knowledge = load_knowledge()
            except (OSError, ValueError, UnicodeError, KeyError, TypeError):
                knowledge = None
                st.caption("睡眠资料暂时不可用。" if language == "中文" else "Sleep information is temporarily unavailable.")
            for source_id in dict.fromkeys(ref["source_id"] for ref in knowledge.references if ref["source_id"].startswith("H")) if knowledge else ():
                refs = [ref for ref in knowledge.references if ref["source_id"] == source_id]
                st.markdown(f"**{refs[0]['title']}**")
                for ref in refs:
                    st.write(ref["text"])
                st.caption(refs[0]["source_url"])
    result = view.analysis
    with st.container(key="topbar"):
        brand, language_control = st.columns([3, 1])
        with brand:
            st.markdown('<div class="brand"><span class="brand-mark" aria-hidden="true">☾</span>SleepLens</div>', unsafe_allow_html=True)
        with language_control:
            st.session_state["header_language"] = language
            st.selectbox("Language / 语言", ["English", "中文"], key="header_language",
                         index=["English", "中文"].index(language), on_change=_change_language,
                         label_visibility="collapsed")
    info = data_catalogue(view.selection.get("profile_id", "P01"), today=berlin_today())
    _first_use_header(info, language, bool(view.turns))
    _example_buttons(info, language, view.selection)
    with st.container(key="record_panel"):
        with st.expander(text["record_panel"], expanded=False, key="records_expanded", on_change="rerun"):
            if result["period"]:
                st.caption(f"{result['profile_id']} · {result['period']['start_date']} — {result['period']['end_date']}")
            _statistics(result, text)
    _first_use_details(info, language)
    conversation = st.container(key="conversation")
    with conversation:
        for turn in view.turns:
            _turn(turn, text)
    prompt = st.chat_input(text["placeholder"], max_chars=4000, key="chat_question")
    if prompt:
        try:
            with conversation:
                with st.chat_message("user"):
                    st.write(prompt)
                with st.spinner(text["thinking"]):
                    view.send(prompt)
            st.session_state["sync_controls"] = True
            st.rerun()
        except ConfigError as exc:
            st.error(text["prompt_error"])
            st.caption(str(exc))
