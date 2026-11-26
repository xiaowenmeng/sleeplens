"""Read-only sleep analysis and knowledge search."""

import json

from sleeplens.analysis import analyze_sleep
from sleeplens.knowledge import search_sleep_knowledge


ANALYZE_TOOL_NAME = "analyze_sleep"
SEARCH_TOOL_NAME = "search_sleep_knowledge"
SEARCH_TOOL_SCHEMA = {
    "type": "function", "function": {
        "name": SEARCH_TOOL_NAME,
        "description": "Search curated sleep evidence: CDC, NIH/NHLBI, NHS, AASM and explicitly scoped manufacturer documentation. Covers sleep habits, NREM/deep/light/REM, stage variation, awakenings, circadian timing, diaries, tracker limitations, insomnia, CBT-I and breathing symptoms. General definitions need no profile/date. Returns up to four complementary passages with exact citation IDs, dates and scope. Not a live web search.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "A focused Chinese or English topic query, 1–500 characters."}},
                       "required": ["query"], "additionalProperties": False},
    },
}
ANALYZE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": ANALYZE_TOOL_NAME,
        "description": (
            "Read sleep records for P01, P02 or P03 and calculate statistics "
            "for one completed waking date (start_date=end_date, compare_previous=false), or a completed seven-day period. Explicit user dates override page defaults; never expand a single date into a week. Optionally compare "
            "the preceding seven days. Ask for missing profile/dates first. "
            "Missing nights are not zero. A difference is available only if each "
            "period has at least four valid nights (product rule, not medical advice). "
            "Available dates: the 14 waking dates ending today, including today's waking date "
            "(last night's sleep); the runtime facts give the exact range. Other dates up to today "
            "are accepted but may return no data. Read-only."
            " Returns sleep-onset and wake-up timestamps, night awakening counts, awake minutes, "
            "and deep/light/REM minutes with weekly means and detail_nights coverage. "
            "Also returns profile_age in years from the validated selected profile; do not assume it is unknown when supplied. "
            "Mean clock times use local Europe/Berlin time (onsets anchored at noon across midnight). "
            "SleepLens defines light as combined N1+N2, deep as N3 and REM separately; these are recorded totals, not healthy targets. "
            "Bedtime and sleep latency are not recorded."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "profile_id": {"type": "string", "enum": ["P01", "P02", "P03"]},
                "start_date": {"type": "string", "description": "Inclusive waking date, YYYY-MM-DD."},
                "end_date": {"type": "string", "description": "Inclusive waking date: equal to start_date for one day, or start_date plus six days for a week."},
                "compare_previous": {"type": "boolean", "description": "False for a single date; for a week, whether to compare the preceding seven days."},
            },
            "required": ["profile_id", "start_date", "end_date", "compare_previous"],
            "additionalProperties": False,
        },
    },
}


def _unique_arguments(pairs):
    args = {}
    for name, value in pairs:
        if name in args:
            raise ValueError("Duplicate argument.")
        args[name] = value
    return args


def dispatch_tool(name: str, arguments: str | dict, *, excluded_topics=(), query_override=None) -> dict:
    """Execute only the known function and strictly validate its arguments."""
    if name not in {ANALYZE_TOOL_NAME, SEARCH_TOOL_NAME}:
        return {"status": "invalid_input", "error": "Unknown tool."}
    try:
        args = json.loads(arguments, object_pairs_hook=_unique_arguments) if isinstance(arguments, str) else arguments
    except (ValueError, TypeError):
        return {"status": "invalid_input", "error": "Arguments must be valid JSON."}
    if name == SEARCH_TOOL_NAME:
        if not isinstance(args, dict) or set(args) != {"query"}:
            return {"status": "invalid_input", "error": "Only a query is accepted.", "passages": []}
        original = args["query"]
        if type(original) is not str or not original.strip() or len(original) > 500:
            return search_sleep_knowledge(original)
        return search_sleep_knowledge(query_override or original, excluded_topics=excluded_topics)
    if name == ANALYZE_TOOL_NAME:
        if not isinstance(args, dict) or set(args) != {
            "profile_id", "start_date", "end_date", "compare_previous"
        }:
            return {"status": "invalid_input", "error": "Exactly four analysis arguments are required."}
        return analyze_sleep(**args)
