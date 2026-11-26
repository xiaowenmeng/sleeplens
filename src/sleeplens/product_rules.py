"""Explain deterministic product rules without asking an LLM to infer gates."""

import re
from dataclasses import dataclass

from sleeplens.analysis import MIN_COMPARISON_NIGHTS


NUMBERS = {**{str(i): i for i in range(8)}, **dict(zip("零一二三四五六七", range(8))),
           "两": 2, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
NUMBER = r"(?:[0-7零一二两三四五六七]|zero|one|two|three|four|five|six|seven)"


@dataclass(frozen=True)
class RuleExplanation:
    text: str
    current_valid_nights: int | None
    previous_valid_nights: int | None
    comparison_allowed: bool | None


def _single_count(patterns, question):
    values = {NUMBERS[match.lower()] for pattern in patterns for match in re.findall(pattern, question, re.I)}
    return next(iter(values)) if len(values) == 1 else None


def explain_product_rules(question, language):
    """Only pure rule questions; never replace requested personal analysis."""
    if not re.search(r"计算规则|展示规则|显示规则|分母|门槛|医学标准|四夜|four.night|calculation rule|comparison rule|denominator|threshold", question, re.I):
        return None
    if re.search(r"诊断|用药|剂量|diagnos|dosage|medication", question, re.I):
        return None
    if not re.search(r"有效|分母|均值|平均|比较|四夜|valid nights?|denominator|mean|average|comparison|four.night", question, re.I):
        return None
    if re.search(r"(?<![a-z0-9])P0[123](?![a-z0-9])|\d{4}-\d{2}-\d{2}|我的记录|my records", question, re.I):
        return None
    mean = bool(re.search(r"平均|均值|分母|mean|average|denominator", question, re.I))
    comparison = bool(re.search(r"比较|变长|变短|前期|前一期|门槛|四夜|医学标准|compare|comparison|previous|threshold|four.night", question, re.I))
    if not mean and not comparison:
        return None
    current_question = re.sub(r"(?:前期|前一期|previous)[^，。;；\n]*", "", question, flags=re.I)
    current = _single_count([
        r"(?:只有|仅有|本期(?:只有|有)?)\s*(" + NUMBER + r")\s*(?:个)?(?:有效)?(?:晚|夜)",
        r"(?:only|current(?: period)? (?:has|contains))\s+(" + NUMBER + r")\s+(?:(?:valid|recorded)\s+)?nights?\b",
    ], current_question)
    previous = _single_count([
        r"(?:前期|前一期)(?:只有|有)?\s*(" + NUMBER + r")\s*(?:个)?(?:有效)?(?:晚|夜)",
        r"previous(?: period)? (?:has|contains)\s+(" + NUMBER + r")\s+(?:(?:valid|recorded)\s+)?nights?\b",
    ], question)
    if previous is None and re.search(r"前(?:一)?期(?:的)?(?:记录)?(?:是|为)?(?:完整|齐全)|previous(?: period)?(?: records)? (?:is |are )?(?:complete|has all seven)", question, re.I):
        previous = 7
    counts = [count for count in (current, previous) if count is not None]
    allowed = False if any(count < MIN_COMPARISON_NIGHTS for count in counts) else (
        True if current is not None and previous is not None else None)
    zh = language == "Chinese"
    parts = []
    if mean:
        text = ("均值＝有效记录分钟数之和÷有效夜数，缺失夜晚不补零，也不固定除以7。" if zh
                else "Mean = sum of valid recorded minutes / valid nights; missing nights are not zeros and the denominator is not always seven. ")
        if current == 0:
            text += "有效夜数为0时，均值为空值，不是0。" if zh else "With zero valid nights, the mean is null, not zero. "
        elif current is not None:
            text += (f"你假设本期有{current}晚有效记录，分母就是{current}，结果只描述这些有效夜晚。" if zh
                     else f"In your hypothetical current period with {current} valid nights, divide by {current}; the result describes those nights only. ")
        parts.append(text + " [B2:Coverage]")
    if comparison:
        text = (f"只有两期各至少{MIN_COMPARISON_NIGHTS}晚有效记录，才展示“本期均值－前期均值”的差值；否则不报告数值差、百分比变化或变长/变短的方向。" if zh
                else f"A difference (current mean minus previous mean) is available only when BOTH periods have at least {MIN_COMPARISON_NIGHTS} valid nights; otherwise report no numeric, percentage or directional change. ")
        if allowed is False:
            text += "你描述的情境不满足双方门槛，因此不能比较变化。" if zh else "Your hypothetical scenario does not meet both requirements, so no change can be reported. "
        elif allowed is True:
            text += "你假设的双方有效夜数满足展示门槛。" if zh else "Your hypothetical counts meet the display gate. "
        text += "这是产品展示规则，不是医学标准或显著性检验。" if zh else "This is a product display rule, not a medical standard or significance test."
        parts.append(text + " [B2:Comparison]")
    return RuleExplanation("\n\n".join(parts), current, previous, allowed)


def explain_blank_and_valid_zero(question, language):
    if not (re.search(r"blank|missing|空白|缺失", question, re.I)
            and re.search(r"zero|零", question, re.I)
            and re.search(r"average|coverage|平均|覆盖", question, re.I)):
        return None
    if language == "Chinese":
        return ("不一样。空白或缺失夜晚不进入有效分钟总和，也不计入均值的有效夜数分母；它会降低七夜记录覆盖率。[B1:Validity][B2:Coverage]\n\n"
                "标记为有效的零值以0分钟参与统计，同时计入均值分母和有效夜数，因此会计入覆盖率；均值可能比把它当缺失时更低。均值始终除以有效夜数，覆盖率为有效夜数÷7。[B1:Validity][B2:Coverage]\n\n"
                "有效零值仍需要核实，不能证明那晚实际完全没有睡眠。[B1:Validity]")
    return ("No. A blank or missing night is excluded from both the recorded-minute sum and the valid-night denominator, and reduces seven-night coverage. [B1:Validity][B2:Coverage]\n\n"
            "A zero marked valid contributes 0 minutes but DOES count as a valid night in the average's denominator and in coverage. It can therefore lower the average compared with treating that night as missing. Mean = sum of valid minutes / valid nights; coverage = valid nights / 7. [B1:Validity][B2:Coverage]\n\n"
            "A valid zero is retained for verification; it does not prove that no sleep actually occurred. [B1:Validity]")
