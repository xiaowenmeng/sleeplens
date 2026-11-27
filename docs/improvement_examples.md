# SleepLens 改进案例

以下四例均来自实际存在的历史会话。精简原始证据见 [improvement_evidence.json](improvement_evidence.json)：保留问题、必要上下文、最终展示正文、真实模型调用标记及原文件 SHA-256；完整旧源码、指令快照和重复日志已清理。

“真实模型会话”表示历史记录为 `mode=live` 且有已完成的模型请求。最终展示可能经过应用校验、规范化或保底拼接，不能把所有文字视为模型原样输出。修复后证据均为真实本地工具加人工模型传输的离线检查；本次未运行真实模型，也未重新评分历史版本。

## 1. 纯查询附加多余解释

1. **问题与上下文**：P01，“2026-10-22的深睡占比是多少？”
2. **旧问题（真实模型会话）**：给出72分钟、339分钟和约21%后，继续解释“并不代表健康标准或睡眠质量评分”，还附产品来源。纯数值查询被扩成健康边界说明。证据 ID：`lookup_extra_explanation`。
3. **实际修复**：已有实现按原始请求识别单项阶段占比，在真实工具结果可用后由应用生成所问数值，单项查询不附一般健康解释。相关实现为 `reply_policy.py`、`agent.py`。
4. **验证与限制**：历史离线输出 `lookup_zh` 为“2026-10-22的记录中，深睡为72分钟，总睡眠时长为339分钟，深睡占比约为21.2%。”当前 [test_reply_intent_scope.py](../tests/test_reply_intent_scope.py) 的 `test_lookup_is_one_sentence_without_health_boundary_or_extra_stage_table` 检查中英文及变体。它验证应用范围和计算，不能证明真实模型在其他问题上的表达质量。

## 2. 只问深睡却展示全部阶段

1. **问题与上下文**：P01，`Was my deep sleep percentage normal on October 22, 2026?`
2. **旧问题（真实模型会话＋应用保底）**：最终展示含 Deep、Light、REM 三行表格，随后又解释夜醒、较短睡眠等内容。日志标记 `fallback=stage_assessment`，不能把整张表归为模型直接输出。证据 ID：`deep_only_expanded`。
3. **实际修复**：已有实现以用户原句限制阶段和独立子问题；模型提出的宽泛计划不能把 deep 扩成全阶段，判断依据不足后不继续拼入无关解释。相关实现为 `response_planning.py`、`reply_policy.py`、`failure_display.py`。
4. **验证与限制**：历史离线 `normality_en` 只保留21.2%及当前依据不足说明。当前同一测试文件的 `test_model_refinement_cannot_expand_a_deep_only_request_to_all_stages`、`test_overbroad_proposal_does_not_expand_final_answer_or_visible_calculations` 保护正文和计算详情范围。显式请求完整分布仍有独立测试。未验证所有自然语言变体，也不建立医学正常阈值。

## 3. 诊断追问展开过多

1. **问题与上下文**：先查询 P01 的2026-10-15睡眠时长，再问“那你可不可以说我失眠了”。
2. **旧问题（真实模型会话）**：虽先拒绝诊断，后面仍展开多项记录、症状条件、缺少字段和评估项目；短追问被扩成长篇讨论。没有证据证明这次作出了确诊。证据 ID：`medical_overexplained`。
3. **实际修复**：已有实现让明确个人诊断请求进入本地边界分支；在匹配且有效的同一会话记录中最多承接一项单日事实，切换日期后不复用旧事实。相关实现为 `reply_policy.py`、`agent.py`。
4. **验证与限制**：历史离线 `medical_zh` 展示另一有效日期2026-10-22的简短边界及5小时39分钟记录，不是对原问题的真实模型复测。当前 `test_diagnosis_followup_is_local_and_quotes_only_one_verified_fact` 检查中英文分支无模型请求，`test_medical_followup_does_not_reuse_a_record_after_the_date_changes` 检查日期切换。规则不等于完整语义理解，不能外推为全面医疗安全验证。

## 4. 补充感受后重复整套指标

1. **问题与上下文**：P01，先分析2026-10-19，再补充“我醒来后很容易就入睡了”。
2. **旧问题（真实模型会话，prompt-v29）**：已经回应主观反馈后，又重复7小时45分钟、入睡醒来时刻、夜醒次数和全部分期，削弱后续对话的相关性。证据 ID：`feedback_repeated_metrics`。
3. **实际修复**：已有实现通过 `experience_context.py` 关联原始主观反馈、已确认日期和待答主题；`response_planning.py` 为后续轮次保留相关字段。当前 prompt-v1 与业务规范已经配套；当前交付基线重新从 v1 编号，历史会话中的版本标识保持原样。
4. **验证与限制**：当前 [test_single_night_experience.py](../tests/test_single_night_experience.py) 的 `test_three_turn_updates_keep_date_reports_and_answered_topics`、`test_english_feedback_is_scoped_without_full_metric_inheritance` 使用真实本地工具与人工候选验证上下文；[check_current.py](../scripts/check_current.py) 另有人工对话回放。这些检查支持上下文机制，不证明模型在真实后续对话中一定不重复。

清理后的验证：329项当前离线测试通过；12组人工对话、112种资源加载组合及展示数据可复现检查通过。未调用付费模型，未验证公网或真实模型质量。这些数字是当前离线检查结果，不能替代课程材料中的历史模型评分。
