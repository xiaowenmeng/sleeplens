"""Conservative output gates; these are not a semantic or medical verifier."""

import json
import re
from dataclasses import dataclass, replace

from sleeplens.knowledge import TOPIC_TERMS, term_matches
from sleeplens.presentation import record_summary
from sleeplens.application_dialogue import is_product_description
from sleeplens.record_grounding import NUMBER, QUANTITIES, cited_quantity_supported, health_context, record_validation_text, supports_measurement, validate_record_claims, discourse_quantity, product_definition_quantity


SUMMARY_TOKEN = "{{sleep_summary}}"
INTERCEPTION_POLICY_VERSION = "grounded-errors-v2"


@dataclass(frozen=True)
class HealthReview:
    blocking_problem: str | None
    warnings: tuple[dict, ...]


@dataclass(frozen=True)
class SupportedAnswer:
    text: str
    removed_blocks: int
    has_record: bool = False
_DOSE_NUMBER = rf"(?:{NUMBER}|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|quarter)"
_MEDICINE_QUANTITY = re.compile(
    rf"{_DOSE_NUMBER}\s*(?P<unit>mg(?![a-z])|milligrams?(?![a-z])|毫克|毫升|片(?:药|安眠|褪黑素)?|(?:an?\s+)?(?:tablets?|pills?)(?![a-z]))", re.I)

_CLAUSE_BOUNDARY = r"[，,；;。！？!?\n]|(?<!不)但是?|不过|然而|可是|而且|而是|\bbut\b|\bhowever\b"


def _negative_prefix(text, position):
    prefix = re.split(_CLAUSE_BOUNDARY, text[:position], flags=re.I)[-1][-60:]
    # A refusal is not a prescription. Comparatives such as 'not less than'
    # and double negation must not turn an actual dose into an exemption.
    if re.search(r"并非不|不是不|(?:不能|无法|不应)(?:不|否认)|\b(?:cannot|can't) (?:not|deny)\b|低于|高于|少于|多于|至少|超过|below|above|less|more|under|over", prefix, re.I):
        return False
    negatives = list(re.finditer(r"不能|无法|不会|不应|不要|不建议|不得|不提供|\b(?:cannot|can't|do not|don't|must not|will not)\b", prefix, re.I))
    if not negatives:
        return False
    tail = prefix[negatives[-1].end():]
    if re.search(r"因此|所以|然后|因而|那么|仍然|还是|\b(?:therefore|then|yet|so)\b", tail, re.I):
        return False
    if (re.search(r"判断|确认|诊断|确定|证明|confirm|diagnos|determine|prove", tail, re.I)
            and re.search(r"建议|推荐|服用|应该|recommend|should|taking|take", tail, re.I)):
        return False
    return True


def _evidence_limitation(clause):
    """Recognize statements about evidence/permissions, not positive advice."""
    clause = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", clause).strip(" \t。.!：:*")
    # Do not erase a positive recommendation merely because the same clause
    # starts with an uncertainty statement.
    action = re.search(r"建议|试试|应该|尽量|服用|recommend|should|take", clause, re.I)
    if action and not _negative_prefix(clause, action.start()):
        return False
    return bool(re.search(
        r"(?:不能|无法|不足以)(?:[^，。；\n]{0,16})(?:判断|诊断|确诊|证明|认定|确认|推断|评估|保证)|"
        r"(?:不代表|不等于|不构成|并非|不是)[^，。；\n]{0,24}(?:评分|质量|健康|诊断|达标|标准)|"
        r"(?:没有|未提供|未设定|不提供)[^，。；\n]{0,24}(?:达标线|评分|正常值|阶段.{0,8}标准|统一.{0,8}标准)|"
        r"(?:资料|知识库|本地|记录|数据)[^，。；\n]{0,30}(?:未覆盖|没有覆盖|未收录|缺少|没能读取|读取失败|没有说明|没有讨论|没有给出|不支持|没有.{0,12}依据)|"
        r"我没有(?:为此)?(?:加入|提供|给出|设定)[^，。；\n]{0,20}(?:标准|结论|方案|阈值)|"
        r"不把[^，。；\n]{0,60}(?:反推|反过来理解)|"
        r"^(?:是否|如何|具体|个别化|个体)[^，。；\n]{0,60}(?:专业人员|医生|评估|判断|因人而异)|"
        r"(?:不能|无法|不会|不提供)[^，。；\n]{0,12}(?:建议|推荐|提供|开具)[^，。；\n]{0,15}(?:服用|用药|剂量|处方)|"
        r"\b(?:cannot|can't|do not|does not|don't|doesn't)\b.{0,35}\b(?:establish|diagnose|determine|confirm|prove|recommend|prescribe)\b|"
        r"\b(?:not a|not an)\b.{0,20}\b(?:score|diagnosis|quality rating)\b|"
        r"\b(?:sources?|evidence|records?|data)\b.{0,30}\b(?:unavailable|not available|not covered|missing)\b",
        clause, re.I))


def _help_offer(clause):
    return bool(re.fullmatch(
        r"\s*(?:如果你(?:需要|愿意|想了解)|如需|我(?:还)?可以|也可以)[^。！？\n]{0,70}"
        r"(?:查看|查询|解读|解释|展开|了解|看|分析)[^。！？\n]{0,30}[。.!]?\s*|"
        r"\s*(?:I can|If you (?:want|wish)).{0,80}(?:look up|explain|review|interpret).{0,40}[.!]?\s*",
        clause, re.I))


def is_evidence_gap_answer(text):
    """An explicit gap/refusal needs no citation proving that gap exists."""
    clauses = [c.strip() for c in re.split(_CLAUSE_BOUNDARY, text, flags=re.I) if c.strip()]
    def context_only(clause):
        return bool(re.fullmatch(r"对[^。；\n]{0,60}(?:来说|而言)|"
                                 r"(?:是否|能否|如何)[^。；\n]{0,60}|"
                                 r"需要结合[^。；\n]{0,60}判断|"
                                 r"不需要你自己在[^。；\n]{0,30}建议之间二选一", clause)
                    or (clause.startswith("如果") and len(clause) <= 80
                        and not re.search(r"就|应|建议|服用|采取|必须|需要", clause)))
    return bool(clauses and any(_evidence_limitation(c) for c in clauses)
                and all(_evidence_limitation(c) or _help_offer(c) or context_only(c) for c in clauses))


def _assertion_text(text):
    # Evaluate each clause independently, so 'cannot diagnose, but you are
    # healthy' still requires evidence for its positive second clause.
    return "。".join(c for c in re.split(_CLAUSE_BOUNDARY, text, flags=re.I)
                    if not _evidence_limitation(c) and not _help_offer(c))


def _has_medicine_quantity(text):
    for match in _MEDICINE_QUANTITY.finditer(text):
        if _negative_prefix(text, match.start()):
            continue
        if (match["unit"] != "片"
                or re.match(r"\s*(?:[，。；;!?！？]|$|即可|就行|左右)", text[match.end():])
                or re.search(r"药|服用|口服|褪黑素|维生素|片剂|medication|melatonin|supplement", text[max(0, match.start()-40):match.end()+40], re.I)):
            return True
    return False


def _has_diagnosis(text):
    diagnoses = re.finditer(r"(?:你|您)(?:已经|确实|就是)?(?:患有|得了)|可以确诊|确诊为|you (?:definitely )?have (?:insomnia|sleep apnea)|I diagnose", text, re.I)
    return any(not _negative_prefix(text, match.start()) for match in diagnoses)


def _response_scaffold(text):
    """Introductions and requests for clarification make no medical claim."""
    if QUANTITY.search(text) or _has_medicine_quantity(text) or _has_diagnosis(text):
        return False
    if re.search(r"应该|尽量|避免|保持|固定|服用|提前|减少|增加|导致|有助于|能改善|会影响|保证|治愈|治好|\b(?:should|take|avoid|causes?|improves?|cures?|guarantee)\b", text, re.I):
        return False
    return bool(re.search(r"先(?:给出|提供).{0,20}(?:建议|方向|做法)|"
                          r"^(?:你可以|可以|不妨)(?:先)?从[^。！？\n]{1,40}入手[:：。.]?\s*$|"
                          r"(?:下列|以下|这几方面|接下来).{0,50}[:：]\s*$|"
                          r"(?:建议|做法|方向|几点|两点|方面|改善)[^。！？\n]{0,40}[:：]\s*$|"
                          r"(?:告诉我|说明要看).{0,70}(?:哪|困扰|几天|方面)", text))


ADVICE = re.compile(
    r"建议|改善|怎么办|怎么(?:才能|才|样才能)?(?:睡|改善睡眠)|如何(?:才能|才)?(?:睡|改善睡眠)|试试|尽量|避免|保持[^，。！？\n]{0,15}作息|固定[^，。！？\n]{0,15}(?:起床|睡)|"
    r"\b(?:advice|recommend|try|avoid|keep a regular|improve|help me sleep)\b", re.I)
QUANTITY = re.compile(
    r"(?:[-+−]?\d+(?:\.\d+)?|[零一二两三四五六七八九十百半]+|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|half))\s*(?:%|分钟|小时|晚|夜|天|分(?=\W|$)|"
    r"minutes?(?![a-z])|mins?(?![a-z])|hours?(?![a-z])|hrs?(?![a-z])|nights?(?![a-z])|days?(?![a-z]))|"
    r"(?:平均|均值|\baverage\b|\bmean\b)[^\d\n]{0,12}\d+(?:\.\d+)?", re.I)


def numeric_values(text):
    """Normalize common English/Chinese duration numbers in the small corpus."""
    english = dict(zip(("zero one two three four five six seven eight nine ten eleven twelve "
                        "twenty thirty forty fifty sixty half").split(),
                       (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 20, 30, 40, 50, 60, .5)))
    values = {float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)}
    values.update(english[word] for word in re.findall(r"[a-z]+", text.lower()) if word in english)
    digits = {char: value for value, char in enumerate("零一二三四五六七八九")}
    digits.update({"两": 2, "半": .5})
    for word in re.findall(r"[零一二两三四五六七八九十半]+", text):
        if word in digits:
            values.add(float(digits[word]))
        elif word.count("十") == 1:
            left, right = word.split("十")
            if (not left or left in digits) and (not right or right in digits):
                values.add(float((digits.get(left, 1) * 10) + digits.get(right, 0)))
    return values


def supported_quantity(quantity, evidence, *, match=None):
    """Match common duration units too, so 20 minutes cannot support 20 hours."""
    if match is None:
        match = next(QUANTITIES.finditer(quantity), None)
    if match is not None and re.search(r"小时|分钟|分$|hours?|hrs?|minutes?|mins?|\bh\b", match.group(), re.I):
        return cited_quantity_supported(match, evidence)
    def unit(text):
        if re.search(r"分钟|minutes?|mins?", text, re.I):
            return "minute"
        if re.search(r"小时|hours?|hrs?|\bh\b", text, re.I):
            return "hour"
        if re.search(r"晚|夜|nights?", text, re.I):
            return "night"
        if re.search(r"天|days?", text, re.I):
            return "day"
        return None
    target = unit(quantity)
    if not target:
        return numeric_values(quantity).issubset(numeric_values(evidence))
    evidence = re.sub(r"\b(?:the|an?|a relaxing) hour\b", "one hour", evidence, flags=re.I)
    return any(unit(part) == target and numeric_values(quantity).issubset(numeric_values(part))
               for part in QUANTITY.findall(evidence))


def _health_paragraphs_with_sources(text, health_references):
    """Associate only an explicit cited list introduction with its own items.

    Inline item citations override the introduction for that item only. Prose,
    headings, two blank lines, and changed indentation do not inherit evidence.
    """
    pending = active = ()
    level = None
    blanks = 0
    for paragraph in text.splitlines():
        if not paragraph.strip():
            blanks += 1
            if blanks > 1:
                pending = active = ()
                level = None
            yield paragraph, ()
            continue
        blanks = 0
        refs = tuple(re.findall(r"\[(H\d+:[A-Za-z0-9_-]+)\]", paragraph))
        item = re.match(r"^([ \t]*)(?:[-*+]|\d+[.)、])\s+", paragraph)
        if item:
            if pending:
                active, pending, level = pending, (), len(item[1])
            explicit = re.search(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", paragraph)
            inherited = active if not explicit and len(item[1]) == level else ()
            yield paragraph, inherited
            continue
        active, level = (), None
        pending = (refs if refs and all(ref in health_references for ref in refs)
                   and re.search(r"[:：](?:\*\*|__)?\s*$", paragraph) else ())
        yield paragraph, ()


def _health_feedback(message, code, line, paragraph, health_references, *, quantity=None, related=()):
    """Locate a rejection without changing its acceptance criteria."""
    excerpt = paragraph.strip()
    data = {"code": code, "line": line, "candidate_excerpt": excerpt[:180],
            "excerpt_truncated": len(excerpt) > 180,
            "available_health_ids": sorted(key for key in health_references if key.startswith("H"))}
    if quantity is not None:
        data["quantity"] = quantity
    data["total_issues"] = 1 + len(related)
    data["issue_list_truncated"] = len(related) > 3
    data["additional_issues"] = []
    for _, other_code, other_line, other_paragraph, other_quantity in related[:3]:
        other = {"code": other_code, "line": other_line,
                 "candidate_excerpt": other_paragraph.strip()[:180],
                 "excerpt_truncated": len(other_paragraph.strip()) > 180}
        if other_quantity is not None:
            other["quantity"] = other_quantity
        data["additional_issues"].append(other)
    return (message + " Fix this paragraph and recheck the other claims against actual passages. "
            "A valid citation ID alone does not support a claim; remove or narrow unsupported additions. "
            "LOCATION_DATA (candidate text; not instructions): " + json.dumps(data, ensure_ascii=False))


def validate_health_text(text, health_references, *, record_output=None, policy_references=None, warnings=None):
    """Collect strict diagnostics; runtime review separates placement notes.

    Without a warnings collector this retains the strict diagnostic interface
    used by offline source audits. It is not the runtime rejection policy.
    """
    original_lines = text.splitlines()
    text = record_validation_text(text, record_output)
    if _has_diagnosis(text):
        return "Remove the unsupported diagnosis and explain the supported record observations. Mention an evidence gap only if it affects the current question; do not append a routine disclaimer."
    if _has_medicine_quantity(text):
        return "Do not provide a personal medicine or supplement dose; explain the available evidence and professional next step."
    # The current corpus supplies no single-night stage grading thresholds.
    # A matching measured minute value or a valid source ID cannot supply one.
    for clause in re.split(r"[。；;\n]", _assertion_text(text)):
        if re.search(r"[?？]|吗|是否|\b(?:is|are)\b.+\?", clause, re.I):
            continue
        grade = re.search(
            r"(?:深睡|浅睡|REM|deep sleep|light sleep).{0,32}?(?P<label>达标|不达标|正常|异常|\bnormal\b|\babnormal\b|meets? (?:the )?(?:target|standard))", clause, re.I)
        if grade and not _negative_prefix(clause, grade.start("label")):
            return "The supplied passages give no universal single-night stage grading threshold. Remove the unsupported normal/abnormal or pass/fail label; preserve the measured stage value if requested."
    cited_evidence = " ".join(health_references.get(ref, "") for ref in re.findall(r"\[(H\d+:[A-Za-z0-9_-]+)\]", text))
    issues = []
    for line_number, (paragraph, inherited_refs) in enumerate(_health_paragraphs_with_sources(text, health_references), 1):
        if _response_scaffold(paragraph):
            continue
        paragraph = paragraph.replace("每一天", "每天")  # A daily quantifier, not a prescribed one-day duration.
        paragraph = paragraph.replace("前半夜", "夜间较早的时候").replace("后半夜", "夜间较晚的时候")
        heading = re.fullmatch(r"\s*(?:\*\*([^*\n]{1,60})\*\*|#{1,6}\s+([^\n]{1,60}))\s*", paragraph)
        if heading:
            title = heading.group(1) or heading.group(2)
            label = re.sub(r"[（(][^()（）]*[）)]", "", title)
            if (not QUANTITY.search(title) and not re.search(
                    r"保证|治愈|治好|痊愈|guarantee|cure|你.{0,25}(?:正常|健康|失眠)", title, re.I)
                    and not re.search(r"(?:建议|应该|需要|should|recommend)\s*(?:你|您)?\s*(?:服用|固定|避免|起床|入睡|take|avoid|keep)", label, re.I)):
                continue  # A topic label is not itself a medical recommendation.
            if (record_output and not re.search(r"正常|健康|达标|标准|失眠|至少|\bnormal\b|healthy|insomnia", title, re.I)
                    and not ADVICE.search(title) and validate_record_claims(title, record_output, {}) is None):
                continue  # A grounded record/date heading is not a clinical assertion.
            if not QUANTITY.search(title) and (not needs_health_evidence("", title) or re.search(r"是什么|能否|是否|关于|包含.*内容|\bwhat\b|\babout\b|contents", title, re.I)):
                continue  # A question/section label is not a sourced health assertion.
        paragraph = re.sub(r"^\s*(?:第[一二三四五六七八九十\d]+天|Day\s*\d+)\s*[:：.-]?\s*", "", paragraph, flags=re.I)
        if is_evidence_gap_answer(paragraph):
            continue
        if re.fullmatch(r"\s*(?:接下来|未来|我的)?[一二三四五六七八九十\d]+天(?:的)?计划[:：]?\s*", paragraph):
            continue
        substantive = (len(re.findall(r"[\u4e00-\u9fff]", paragraph)) >= 18 or len(paragraph.split()) >= 10)
        question_only = bool(re.fullmatch(r"[^。！.!\n]{1,160}[？?]", paragraph.strip()))
        if question_only and not ADVICE.search(paragraph):
            continue
        if not substantive and not needs_health_evidence("", paragraph) and not QUANTITY.search(paragraph):
            continue
        refs = re.findall(r"\[(H\d+:[A-Za-z0-9_-]+)\]", paragraph) or inherited_refs
        evidence = " ".join(health_references.get(ref, "") for ref in refs)
        if "H1:AdultDuration" in refs and re.search(r"(?:达到|刚到|贴着).{0,8}上限|(?:参考|建议).{0,5}上限", paragraph) and not re.search(r"没有上限|不是上限|不能.*上限", paragraph):
            return "The cited adult-duration passage supplies a lower reference ('at least'), not an upper limit. Correct the direction of that interpretation."
        summary = bool(re.match(r"\s*(?:所以|因此|总之|总结|也就是说|综上|in summary|therefore|thus)", paragraph, re.I))
        directive = bool(re.search(r"建议\s*(?:你|您|把|在|每|睡|服|固定|减少)|试试|尽量|应该|\b(?:you should|try|recommend taking)\b", paragraph, re.I))
        if (not evidence and cited_evidence and (not ADVICE.search(paragraph) or (summary and not directive))
                and re.search(r"不能|无法|未知|不足以|不等于|不在|总结|所以|因此|unknown|cannot|does not|in summary|therefore", paragraph, re.I)):
            evidence = cited_evidence  # A closing limitation may refer to sources already cited in this answer.
        product_ids = re.findall(r"\[(B\d+:[A-Za-z0-9_-]+)\]", paragraph)
        product_evidence = " ".join((policy_references or {}).get(ref, "") for ref in product_ids)
        plain = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", paragraph)
        measures = list(QUANTITIES.finditer(plain))
        clinical = bool(ADVICE.search(plain) or re.search(r"正常|健康|达标|参考|标准|失眠|至少|\bnormal\b|\bhealthy\b|reference|recommend|insomnia|at least", plain, re.I))
        if not evidence and not clinical and (product_evidence or any(supports_measurement(plain, m, record_output) is True for m in measures)):
            continue  # Grounded measurements/product definitions are not medical claims.
        if (not evidence and not clinical and record_output
                and re.search(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", plain)
                and validate_record_claims(plain, record_output, {}) is None):
            continue  # Verified clock fields need record evidence, not a health citation.
        if (not evidence and product_evidence and not ADVICE.search(plain)
                and (is_evidence_gap_answer(plain) or re.search(r"不能|无法|不等于|不代表|不提供|不构成|未设|没有|不是|cannot|does not|not a", plain, re.I))):
            evidence = product_evidence
        if not evidence and product_ids and clinical:
            issues.append(("A product rule cannot support this health recommendation; use an applicable health source.",
                           "wrong_evidence_kind", line_number, paragraph, None))
            continue
        if not evidence:
            issues.append(("Each substantive health recommendation needs its own available supporting health citation. Omit unsupported additions.",
                           "missing_health_citation", line_number, paragraph, None))
            if warnings is None or not cited_evidence:
                continue
            # A citation at answer level can supply a general numeric context.
            # This does not assign that citation to a sentence or bypass the
            # independent field/date check for personal measurements.
            evidence = cited_evidence
        for match in measures:
            if discourse_quantity(plain, match) or product_definition_quantity(plain, match, policy_references, evidence_text=paragraph):
                continue
            if supports_measurement(plain, match, record_output, evidence) is True:
                continue
            quantity = match.group()
            if not supported_quantity(quantity, evidence, match=match):
                issues.append(("A health quantity is absent from its cited passage. Remove it; do not invent precise durations.",
                               "unsupported_health_quantity", line_number, paragraph, quantity))
                break
    if warnings is not None and cited_evidence:
        warnings.extend({"code": "citation_coverage", "line": issue[2],
                         "message": "This paragraph has no separate citation; the answer contains supplied health references. Claim support still needs review."}
                        for issue in issues if issue[1] == "missing_health_citation")
        issues = [issue for issue in issues if issue[1] != "missing_health_citation"]
    if issues:
        issues = [(message, code, line, original_lines[line-1] if 0 < line <= len(original_lines) else paragraph, quantity)
                  for message, code, line, paragraph, quantity in issues]
        message, code, line, paragraph, quantity = issues[0]
        return _health_feedback(message, code, line, paragraph, health_references,
                                quantity=quantity, related=issues[1:])
    return None


def review_health_text(text, health_references, *, record_output=None, policy_references=None):
    """Apply the user-facing policy, rather than strict citation-layout rules."""
    warnings = []
    problem = validate_health_text(text, health_references, record_output=record_output,
                                   policy_references=policy_references, warnings=warnings)
    return HealthReview(problem, tuple(warnings))


def contradicts_coffee_context(text, plan):
    return bool((plan.no_coffee or plan.no_caffeine) and re.search(
        r"咖啡(?!因)[^。\n]{0,30}(?:提前|减少|挪|上午)|(?:move|reduce|avoid).*\bcoffee\b", text, re.I))


def supported_answer_blocks(text, *, knowledge, available_ids, health_references,
                            policy_references, record_output, plan, require_removal=True):
    """Keep independently checkable paragraphs after bounded repair fails.

    Never add/replace a source or manufacture a sentence. Uncited contextual
    fragments cannot acquire evidence merely because another block survived.
    Recheck the complete retained text to catch cross-paragraph interactions.
    """
    raw_blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    blocks, pending = [], []
    for block in raw_blocks:
        plain = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", block).strip()
        heading = bool(re.fullmatch(r"(?:#{1,6}\s+[^\n]+|\*\*[^*\n]+\*\*)", plain))
        if heading or re.search(r"[:：](?:\*\*)?\s*$", block):
            pending.append(block)
            continue
        blocks.append("\n\n".join(pending + [block]))
        pending = []
    if pending:
        blocks.append("\n\n".join(pending))
    kept = []
    has_record = has_action = False
    for position, block in enumerate(blocks):
        dependency_text = re.sub(r"(?m)^\s*(?:#{1,6}\s+[^\n]+|\*\*[^*\n]+\*\*)\s*$", "", block).lstrip()
        if len(kept) < position and (re.search(
                r"上述|前述|上面|按以上|照此|\b(?:as above|that plan)\b", block, re.I)
                or re.match(r"(?:[-*+]\s*)?(?:因此|所以|therefore\b|thus\b)", dependency_text, re.I)):
            continue  # Do not detach a conclusion from a discarded premise.
        if "{{" in block:  # Rendered facts remain separately available in UI.
            continue
        check = knowledge.check_citations(block, available_ids=available_ids)
        if check["status"] == "invalid" or contradicts_coffee_context(block, plan):
            continue
        if validate_record_text(block, record_output, require_summary=False,
                                health_references=health_references, policy_references=policy_references):
            continue
        plain = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", block).strip()
        if re.fullmatch(r"(?:#{1,6}\s+[^\n]+|\*\*[^*\n]+\*\*)", plain):
            continue
        measured = bool(record_output and (
            any(supports_measurement(plain, m, record_output) is True for m in QUANTITIES.finditer(plain))
            or re.search(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", plain)))
        has_health = any(ref["source_id"].startswith("H") for ref in check["references"])
        if not has_health and not measured:
            continue
        block_plan = replace(plan, task="records") if measured else plan
        if needs_health_for_task("", block, block_plan, has_health):
            if not has_health:
                continue
            if review_health_text(block, health_references, record_output=record_output,
                                  policy_references=policy_references).blocking_problem:
                continue
        kept.append(block)
        has_record |= measured
        has_action |= bool(has_health and re.search(
            r"(?:建议|可以|试试|尽量|不妨|请|应当|应该|先|把).{0,18}(?:保持|固定|预留|留出|安排|避免|减少|留意|记录|咨询|评估|调整)|"
            r"(?:^|[。！？\n:：])\s*(?:[-*+]\s*)?(?:保持|固定|预留|留出|安排|避免|减少|留意|试试)|"
            r"\b(?:keep|allow|avoid|try|consult|consider|set aside|make time)\b", plain, re.I))
    if not kept or (require_removal and len(kept) == len(blocks)):
        return None
    if (plan.task == "records" and not has_record) or (plan.wants_improvement and not has_action):
        return None
    answer = "\n\n".join(kept)
    if knowledge.check_citations(answer, available_ids=available_ids)["status"] == "invalid":
        return None
    if validate_record_text(answer, record_output, require_summary=False,
                            health_references=health_references, policy_references=policy_references):
        return None
    has_health = bool(re.search(r"\[H\d+:[A-Za-z0-9_-]+\]", answer))
    final_plan = replace(plan, task="records") if has_record and not has_health else plan
    if needs_health_for_task("", answer, final_plan, has_health):
        if not has_health or review_health_text(answer, health_references, record_output=record_output,
                                               policy_references=policy_references).blocking_problem:
            return None
    return SupportedAnswer(answer, len(blocks) - len(kept), has_record)


def needs_health_evidence(question, answer):
    """Catch topical guidance even when the model omits its search tool call."""
    if re.fullmatch(r"[^。！.!\n]{1,100}[？?]", answer.strip()) and not ADVICE.search(answer):
        return False  # A short clarification can legitimately have no evidence.
    if ADVICE.search(question) or ADVICE.search(answer):
        return True
    if re.search(r"成人|睡多久|几小时.*够|需要.*睡|应该.*睡|how (?:much|many).*sleep|enough sleep|hours.*need", question, re.I):
        return True
    lower = (question + " " + answer).lower()
    return any(term_matches(term, lower) for topic, terms in TOPIC_TERMS.items()
               if topic not in {"duration", "quality", "general_advice"} for term in terms)


def needs_health_for_task(question, answer, plan, has_health_citation):
    """Do not confuse product limitations or offers of help with health advice."""
    if _has_medicine_quantity(answer) or _has_diagnosis(answer):
        return True
    answer = _assertion_text(answer)
    if plan.task in {"conversation", "capability", "definition"} and is_product_description(answer):
        return False
    if has_health_citation or plan.task == "health":
        return True
    if plan.task == "combined":
        return bool(plan.personal_assessment or plan.wants_improvement or ADVICE.search(answer) or
                    re.search(r"正常|健康|达标|参考|失眠|睡眠标准|至少.*小时|\bnormal\b|\bhealthy\b|insomnia|reference|recommended", question + " " + answer, re.I))
    if plan.task == "definition" or (plan.task == "capability" and set(plan.topics) <= {"wearables"}):
        action = re.search(
            r"(?:建议|试试|可以|应该|尽量|避免|try|should|avoid|recommend)[^，。！？\n]{0,25}"
            r"(?:提前|减少|服用|吃药|放松|上床|起床|咖啡|午睡|sleep|caffeine|medication|nap)|"
            r"困了[^，。！？\n]{0,8}上床|固定[^，。！？\n]{0,8}起床", answer, re.I)
        return bool(action)
    if plan.task == "records":
        return bool(ADVICE.search(answer) or re.search(r"正常|健康|达标|参考|失眠|\bnormal\b|\bhealthy\b|insomnia|recommend|reference", answer, re.I))
    return needs_health_evidence("" if plan.task == "definition" else question, answer)


def validate_record_text(text, output, *, require_summary, health_references, policy_references=None):
    """Allow grounded model prose; the summary placeholder is optional."""
    text = record_validation_text(text, output)
    if "{{" in text.replace(SUMMARY_TOKEN, "") or text.count(SUMMARY_TOKEN) > 1:
        return "Only one {{sleep_summary}} placeholder is supported."
    if SUMMARY_TOKEN in text and output is None:
        return "No usable record result is available for {{sleep_summary}}."
    if output is None:
        return validate_record_claims(text, output, health_references, policy_references)
    problem = validate_record_claims(text.replace(SUMMARY_TOKEN, ""), output, health_references, policy_references)
    if problem:
        return problem
    for paragraph in re.split(r"\n+", text.replace(SUMMARY_TOKEN, "")):
        evidence = health_context(paragraph, health_references, answer=text)
        policy = False
        if (not require_summary and re.search(r"规则|门槛|standard|threshold|gate", paragraph, re.I)
                and not re.search(r"平均|均值|mean|average", paragraph, re.I)):
            policy_refs = re.findall(r"\[(B\d+:[A-Za-z0-9_-]+)\]", paragraph)
            evidence += " ".join((policy_references or {}).get(ref, "") for ref in policy_refs)
            policy = bool(policy_refs)
        plain = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", paragraph)
        for match in QUANTITIES.finditer(plain):
            if discourse_quantity(plain, match) or product_definition_quantity(plain, match, policy_references, evidence_text=paragraph):
                continue
            if supports_measurement(plain, match, output, evidence) is True:
                continue
            quantity = match.group()
            supported = (numeric_values(quantity).issubset(numeric_values(evidence)) if policy
                         else supported_quantity(quantity, evidence, match=match))
            if not evidence or not supported:
                return f"Quantity '{quantity}' has no matching record or supporting source. Correct that specific claim; do not invent a replacement."
    return None


def validate_interpretation(text, output, *, assessment=False):
    """Flag missing record interpretation, never require disclaimer wording.

    This is a completeness hint, not a semantic grounding or medical verifier.
    Record accuracy and unsafe/unsupported claims have separate checks.
    """
    text = re.sub(r"\[[BH]\d+:[A-Za-z0-9_-]+\]", "", text.replace(SUMMARY_TOKEN, ""))
    linked = re.search(r"这(?:一)?(?:晚|天|次|周)|当晚|本次|当前|本周|你的|你这|所选|这些记录|记录(?:显示|中|到|的)|this (?:night|day|record|week)|your|recorded|selected", text, re.I)
    measured = any(supports_measurement(text, m, output) is True for m in QUANTITIES.finditer(text))
    # Limitation-only clauses do not supply an observation about the records.
    observations = _assertion_text(text)
    interpretation = re.search(
        r"低于|高于|达到|符合|值得|关注|提示|说明|结合|最短|最长|较短|较长|更短|更长|"
        r"接近|相近|相差|差不多|波动|集中|对照|"
        r"below|above|meet|suggest|consider|means|shortest|longest|shorter|longer|"
        r"similar|close|comparable|difference|var(?:y|ies|iation)|stands? out|contrast",
        observations, re.I)
    if not interpretation or not (linked or measured):
        return "Interpret the returned records in relation to the question. Give a useful record-linked observation in natural language. Definitions, values or a generic limitation alone do not answer it; no disclaimer wording or fixed layout is required."
    if assessment and not re.search(r"时长|睡了|小时|duration|hours?|slept", text, re.I):
        return "Answer the requested duration assessment, not stage definitions alone. Check source population and time scope internally. Use a reference comparison only if applicable; otherwise briefly explain the specific gap needed to answer the question, without forcing a compliance conclusion or a limitation footer."
    return None
