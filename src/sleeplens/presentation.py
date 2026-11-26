"""Human-readable offline results; raw tool values remain unrounded."""


WARNING_TEXT = {
    "zero_value_requires_verification": "有效0分钟记录已保留，但需核验；不能据此认定整夜未睡。",
    "incomplete_coverage": "有不可用记录，均值仅描述有效夜；缺失分布可能影响比较。",
    "descriptive_comparison_only": "差值只描述记录时长，不代表统计显著、变化原因、睡眠质量或诊断。",
    "comparison_requires_four_nights": "两段均至少4夜有效才比较，这是产品规则，不是医学标准。",
}

ERROR_TEXT = {
    "unknown_profile": "请选择P01、P02或P03。",
    "invalid_compare_previous": "比较选项必须是布尔值。",
    "invalid_date": "请输入真实日期，格式为YYYY-MM-DD。",
    "invalid_period": "请选择一个醒来日期，或正好包含7天的起止日期。",
    "single_day_comparison_not_supported": "单日查询请关闭与前7夜比较。",
    "date_out_of_range": "无法计算超出日历范围的前一周期。",
    "period_not_finished": "只能分析在今天之前已结束的周期。",
    "dataset_unavailable": "无法读取本地数据，未生成统计结果。",
}


def format_analysis(result: dict) -> str:
    lines = ["SleepLens · 离线分析（合成数据；未调用模型）", f"状态：{result['status']}"]
    if result["error"]:
        error = result["error"]
        lines.append("原因：" + ERROR_TEXT.get(error["code"], error["message"]))
        return "\n".join(lines)
    lines.extend([f"角色：{result['profile_id']}",
                  f"数据版本：{result['dataset_version']}；规则版本：{result['rule_version']}"])
    for scope, label in (("current", "本期"), ("previous", "前期")):
        stats = result[scope]
        if stats is None:
            continue
        period = result["period"] if scope == "current" else result["previous_period"]
        mean = "不可计算" if stats["mean_sleep_min"] is None else f"{stats['mean_sleep_min']:.1f}分钟"
        lines.append(
            f"{label} {period['start_date']}—{period['end_date']}："
            f"有效{stats['valid_nights']}/{stats['expected_nights']}夜，覆盖率{stats['coverage']:.1%}，"
            f"有效记录均值{mean}"
        )
    state = result["comparison_state"]
    if state == "available":
        lines.append(f"本期减前期：{result['difference_min']:+.1f}分钟")
    elif state == "insufficient_data":
        lines.append("两周差值：不可计算（至少一段有效记录不足4夜）")
    seen = set()
    for warning in result["warnings"]:
        code = warning["code"]
        if code not in seen:
            lines.append("提示：" + WARNING_TEXT.get(code, warning["message"]))
            seen.add(code)
    return "\n".join(lines)
