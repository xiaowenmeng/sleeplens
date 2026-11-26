"""Scoped conversational hints. User reports never become measured fields."""

import re


EXPERIENCE_PATTERNS = {
    "return_to_sleep": r"(?:醒|夜醒).{0,20}(?:入睡|睡着|再睡)|(?:再|重新).{0,8}(?:入睡|睡着)|(?:back|return) to sleep|fall(?:ing)? back asleep|fell back asleep",
    "daytime": r"(?:白天|第二天|次日|早上|起床|醒来|睡醒).{0,18}(?:精神|恢复|困|累|疲|清醒)|精神.{0,8}(?:好|不错|差|恢复)|仍然(?:很)?(?:疲惫|困|累)|daytime|(?:feel|felt|feeling|still).{0,16}(?:rested|refreshed|tired|sleepy|fatigue)|energy.{0,8}(?:good|poor)",
}


def experience_fields(text):
    return tuple(name for name, pattern in EXPERIENCE_PATTERNS.items() if re.search(pattern, text, re.I))


def pending_questions(answer):
    """Track only recognizable questions actually present in accepted prose."""
    fields = []
    for match in re.finditer(r"[^。！.!?？\n]*[?？]", answer):
        fields.extend(experience_fields(match.group()))
    return list(dict.fromkeys(fields))


def feedback_fields(question, pending=()):
    # A turn can both answer a pending question and ask a new one. Extract
    # declarative clauses without treating questions as reported experiences.
    fields = []
    for clause in re.findall(r"[^，,。！？!?；;\n]+[。！？!?；;]?", question):
        if re.search(r"[?？]|吗|如何|怎么样|是否|为什么|怎么|多少|多久|几次|几点|"
                     r"分析|解读|解释|查询|列出|查一下|请问|帮我.{0,6}(?:查|看)|"
                     r"^(?:can|does|is|should|why|how|what)\b|\b(?:analy[sz]e|interpret|explain|show)\b|look up|tell me", clause.strip(), re.I):
            continue
        fields.extend(experience_fields(clause))
    if fields:
        return tuple(dict.fromkeys(fields))
    # Elliptical answers are safe to attach only to one explicit pending topic.
    if len(pending) == 1 and re.fullmatch(
        r"\s*(?:很容易|容易|不容易|很难|还好|挺好|很好|不错|很困|很累|没精神|"
        r"(?:yes|no|easily|good|fine|tired|sleepy))[^。！？?\n]{0,8}[。.!！]?\s*", question, re.I
    ):
        return tuple(pending)
    return ()


def scoped_experience(plan, selection, previous, question, turn_number):
    """Keep raw reports only within the same confirmed profile/date scope."""
    profile = plan.profile_id or (selection or {}).get("profile_id")
    period = (list(plan.period) if plan.period else
              [selection["start_date"], selection["end_date"]]
              if selection and not plan.experience_reply and plan.task in {"records", "combined"} else None)
    scope = {"profile_id": profile, "period": period}
    old = previous.get("experience_context") or {}
    same_scope = bool(profile and period and old.get("scope") == scope)
    reports = dict(old.get("reports", {})) if same_scope else {}
    if plan.experience_reply and profile and period:
        for field in plan.experience_fields:
            reports[field] = {"text": question, "turn": turn_number, "source": "user_report"}
    return {"scope": scope, "reports": reports,
            "answered_fields": list(reports),
            "pending_questions": [field for field in old.get("pending_questions", []) if field not in reports] if same_scope else [],
            "current_reply_fields": list(plan.experience_fields),
            "association": "confirmed_record_scope" if profile and period else "needs_clarification"}
