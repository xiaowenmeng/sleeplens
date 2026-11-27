# SleepLens v2：评测与局限（复核草稿）

复核日期：2026-11-23。本文及配套 [HUMAN_REVIEW.csv](HUMAN_REVIEW.csv) 中的复核判断均为 **AI 复核建议**，尚未经组员人工终评。原始 `scoring.csv`、`results.json`、运行报告、trace 和冻结材料保持原样。此次只分析已有证据，没有修改应用、调用模型或重新执行测试。

## 评测设计与证据边界

SleepLens 使用 synthetic-sleep-v2 合成记录和 sleep-knowledge-v6 本地摘要语料。知识组件注入核心产品资料，健康资料检索最多返回四个小节。评测在运行前为十道独立题锁定题目、答案要点、判错条件及预期片段：K1–K7 为七道公开开发题，K8–K10 为三道本轮留出题。题目涵盖单段与多段解释、准确缩写、口语改写、表面冲突建议、人群覆盖缺口和历史资料的时效边界。相关能力此前已有测试，因此“本轮留出”不表示全新能力或独立盲测。依据为 [原题](QUESTIONS.txt)、[评分协议](ANSWER_KEY_AND_PROTOCOL.txt)、[答案表](answer_key.csv) 和 [题集](suite.json)。这些准备文件仍标注 v1；实际三个批次的 `report.json.freeze_id` 和快照核验均指向 `sleeplens-eval-20261123-v2`，不能把准备文件版本误当成实际运行版本。

每题使用新会话，页面默认 P01、2026-10-19 至 2026-10-25、关闭前周比较，不向受测应用注入答案。v2 共留下 **13 条运行记录，对应十道独立题**：公开题各一条，留出题各有首批和复测一条。留出两批之间没有改应用、提示词、知识库或模型配置。K10 首批被批次额度中断，只有复测是未受该批次截断的完整尝试；不能声称 v2 十题均完成两次有效回答。

复核分别判断三个层面：工具是否取回资料、模型是否实际收到且正文主张得到支持、最终展示是否完成用户任务。`trace.provided_evidence` 是初始核心资料；本轮检索原文见 `trace.tool_events[*].result.passages`，是否实际发给模型须再对照运行报告的 `ledger[*].received_evidence_ids`。合法引用、内部 `passed`、取得预期小节都不能单独证明任务成功。展示文本按 `trace.answer` 加上存在时的 `trace.verified_record_facts` 核对；被拦候选正文只用于诊断，不计作用户已得到的答案。本轮没有新做网页观察，因此这里的“展示”指代理输出中的展示字段及现有渲染规则，并非新的公网页面截图。

完整证据包的 `FILES_SHA256.json` 所列 65 项文件均存在且校验一致；13 条运行均有原题、预锁定规则、当轮工具原文、trace 和请求账本。没有发现这四类原始证据缺文件的情况。K6 的主张解释和若干评分档位仍待人工裁定，属于语义与规则适用问题，不应写成“trace 缺失”。K9 缺少儿童适用资料是预设语料覆盖缺口；K10 首批没有后续模型回答是实际中断，均应与归档缺失区分。

## 离线回归与实际模型评测结果

冻结 v2 的既有离线回归记录为 **879 项通过，0 失败、0 错误、0 跳过**，依据 [JUnit XML](v2-offline-tests.xml) 的 `testsuite` 属性及 [v2 清单](v2-MANIFEST.json)。本次未重跑。这些离线测试验证既定逻辑和回归条件，不能替代实际模型回答的语义评分。

v1 开发时曾发现屏幕问题的检索查询同时命中屏幕、失眠和用药，同分排序使 H7:EveningLight 落在前四条之外。v2 在既有锚点机制中增加 screens 对应该小节，并增加四项离线回归；独立候选的两次真实复测均取得并引用所需片段。变更见 [修订日志](revision_log.csv) 和 [补丁](screen-anchor.patch)。这只是针对已观察问题的小样本证据，不能外推为所有问法稳定正确；K7 本次取得 H11 也不能归因于屏幕锚点。

以下为原 `scoring.csv` 的 **AI 初评**，人工终评前保留该标识：

| 组别 | 独立题数／运行数 | 通过 | 部分通过 | 失败 | 未完成（批次中断） |
| --- | --- | ---: | ---: | ---: | ---: |
| 七道公开开发题 K1–K7 | 7／7 | 4 | 3 | 0 | 0 |
| 三道留出题首批 K8–K10 | 3／3 | 0 | 2 | 0 | 1 |
| 同一批留出题复测 K8–K10 | 3／3 | 1 | 0 | 2 | 0 |

原初评的留出首次完整通过数为 **0/3**，全部十题首次完整通过数为 **4/10**，其中一题未完成。13 条运行原初评合计为 5 通过、5 部分通过、2 失败、1 未完成；不能将 13 条当成 13 道独立题，也不把部分通过折算成通过。K8 的复测通过和 K9/K10 的复测失败说明同题重复结果不同；三道留出题均未形成两次完整通过的证据。

## 逐项复核中的关键判断

### K6：不能用未取得 H9 代替逐句核验

K6 的展示正文先明确没有统一夜醒次数阈值、不能只凭计数判断，再提出“夜醒持续多久、醒后能否再入睡、白天状态以及持续时间一起看”。当轮实际取得并发送给后续模型请求的健康片段为 H8:NightWaking、H3:StimulusControl、H4:FirstSteps、H6:Pattern，另有初始 B1/B2 核心资料。定位：开发批次 [K6 trace](evidence/knowledge-dev-20261123T164155Z-21117007/traces/chat-938e8e150b964ea0baba82f086305f06-001.json) 的 `tool_events[0].result.passages[0..3]` 和 `provided_evidence`；[请求账本](evidence/knowledge-dev-20261123T164155Z-21117007/report.json) 的 `ledger[13]`、`ledger[14]`（本文数组索引均从 0 起）。

| 展示主张 | 当轮原文核验 | AI 复核判断 |
| --- | --- | --- |
| 没有统一次数阈值、计数不能确诊 | H8 明确写 `An awakening count alone does not establish a diagnosis` 及 `no universal normal-count cutoff` | 直接支持，已完成题目核心要求 |
| 周期间可短暂觉醒、模式随年龄变化 | H6:Pattern 明确写 `Brief awakenings can occur between cycles. Sleep patterns change with age.` | 直接支持 |
| 夜醒持续多久 | B1:Fields 定义 `awake_min` 为入睡与最终醒来间清醒总分钟数；B1:ProductStages 说明其汇总中途清醒区间。H8 有维持睡眠困难的描述 | 可支持记录清醒时长作为描述性信息；没有直接写“每次夜醒时长是诊断条件”，总时长也不等于每次时长 |
| 醒后能否再入睡 | H8 明确写 `waking early without being able to return to sleep`；H3 提及无法睡着及困后返回床 | H8 直接支持早醒后无法再睡；推广到所有夜醒属于有限概括，不必强制另取 H9 |
| 白天状态 | H8 明确列出未恢复感、白天嗜睡、注意力困难 | 直接支持 |
| “以及持续时间” | 如指每次清醒时长，可参考上述 B1；如指症状持续几天／几月，当轮 H8/H3/H4:FirstSteps/H6 均未明确提供病程信息 | 语义仍待人工确认；K3 取得过的 H4:WhenToSeekHelp 不能跨会话借给 K6，预期答案也不能冒充模型收到的片段 |

预锁定 K6 答案本就要求考虑“症状持续情况、白天影响等”，且允许同等支持片段。因此原初评笼统写“额外临床判断条件缺乏本轮片段支持”过宽。**AI 复核建议暂保留部分通过、待人工确认**：核心回答完整，白天状态与再入睡不能当成无依据；保留争议仅针对“持续时间”的指向及描述性记录信息能否支持该整句。这里没有编造次数、病程阈值或直接诊断，不建议仅因 H9 未检索到改判失败。若组员将其接受为符合锁定答案的定性概括，可改为通过；这不是本轮自动作出的终评。

### K8：两次片段相同，差别在首批新增的机制

首批和复测均实际收到同一 H2:Caffeine 文本：`Caffeine can interfere with sleep for up to eight hours. Late-afternoon coffee may therefore affect bedtime. Avoid nicotine, alcohol before bed and heavy late meals. Sensitivity varies; eight hours is not a guaranteed individual clearance time.` 文本及发送确认分别见首批 [trace](evidence/knowledge-holdout-20261123T164342Z-f4eb2656/traces/chat-d461abc95f1b4642a3e6382f331396cc-001.json)、复测 [trace](evidence/knowledge-holdout-20261123T164510Z-59e9032b/traces/chat-bac9b6ee09f94f6783c8cab2537b5c39-001.json) 的 `tool_events[0].result.passages[0]`，以及对应报告的 `ledger[1].received_evidence_ids`。

| 核验表述 | 首批展示 | 复测展示 | 与实际 H2 文本比较 |
| --- | --- | --- | --- |
| 代谢慢是主要原因 | “主要原因是咖啡因在体内代谢得比较慢” | 没有此句 | H2 没有慢代谢机制、半衰期或“主要原因”排序。检索查询含“半衰期”也不是证据 |
| 个体敏感度差异 | 两次均写“个体敏感度差异很大” | 同左 | `Sensitivity varies` 直接支持有差异；“很大”的强度未被量化，不宜写成来源量化结论 |
| 八小时并不保证代谢清除 | “八小时并不是每个人都能把咖啡因完全代谢掉的时间保证” | “八小时并不是每个人都能保证的代谢清除时间” | `not a guaranteed individual clearance time` 直接支持，不能因出现“代谢”二字就一律判无依据 |

两次均定位 NIH/NHLBI《Healthy Sleep Habits》的 Caffeine 小节，保留时间窗和非个人因果边界。首批因多出未受支持的“主要原因”机制而不完整通过、复测删除后通过，二者的通过边界一致；但首批的**失败档位不一致**：K8 预锁定判错条件明确包括“添加现有片段不支持的机制”，协议第 10 条将超出依据的确定结论记为失败。**AI 复核建议首批由部分通过改为失败，复测维持通过**；不将两次共同且有原文支持的清除时间限定语作为扣分理由。

### K4：核心正确，但附加趋势用途没有证据

K4 的 N3 关系、腕部运动／心率估算及与实验室分期的区别均有 H6:NREM、H10:Estimates 和 H6:Pattern 支持。但最终还展示“因此手表上的深睡分钟数适合用来看自己长期的变化趋势”。当轮片段没有提供设备长期趋势可靠性或该用途适合性的验证；B1/B2 的产品字段与描述性统计规则也不能当成 Fitbit 纵向性能证据。定位见 [K4 trace](evidence/knowledge-dev-20261123T164155Z-21117007/traces/chat-6295a71065b44cd381bbea23ab54a7fa-001.json) 的 `answer` 最后一段、`tool_events[0].result.passages` 和 `provided_evidence`。**AI 复核建议由通过改为失败**，理由限于这一超出依据的确定用途结论，适用协议第 5、9、10 条；不将其误写成 N3 核心答错。该严格档位须由组员确认。

K1 和 K5 建议维持部分通过：资料确实已提供，候选中也有核心内容，但经过数值限定词校验和删段后，最终分别漏掉成人时长参考值、NHLBI 午睡建议及两份资料的完整比较。K2、K3、K7 建议维持通过。每条的原评分、完整展示文本、原文、证据路径和理由均保留在复核 CSV。

## 失败分析

**K9：儿童对象误分与最终答案必须分开看。** 两批 trace 的内部 `query_plan` 都记录 `population_scope=adult`、`special_population=false`、`task=combined`、`wants_improvement=true`；应用 `response_plan` 因而要求 P01 页面所选周的记录及建议。首批用户确实看到“不建议直接照搬成人建议”和儿童覆盖缺口，但后半段仍以没有儿童适用证明的 H8 为孩子提供观察项目及就医触发说明，其中打鼾／呼吸不畅的依据也不在当轮片段中。因此 AI 建议首批由部分通过改为失败，适用 K9 的“将成人依据直接套用给孩子”判错条件；失败原因不是没有给成人改善建议。复测中，模型生成过把成人“周末差异约一小时”用于孩子的候选段落，该段位于 `answer_validation.repairs[0].candidate` 和复测报告 `ledger[3].assistant_messages`，**没有展示给用户**。随后模型尝试调用 `analyze_sleep` 并新增 `response_plan`；在已经执行知识检索后引入不同计划，命中冻结 `agent.py:440` 的计划不可变检查，最终记录 `invalid_response_plan`，该次个人记录查询没有执行。用户最终只得到“本轮问题理解未能通过校验，未执行这批查询。”，故复测维持任务失败。证据见首批 [K9 trace](evidence/knowledge-holdout-20261123T164342Z-f4eb2656/traces/chat-99c4919ef9b440afbc24578f7f138c85-001.json)、复测 [K9 trace](evidence/knowledge-holdout-20261123T164510Z-59e9032b/traces/chat-60ea29e311d74ca5a915c69ab424451c-001.json) 及复测 [报告](evidence/knowledge-holdout-20261123T164510Z-59e9032b/report.json) 的 `ledger[2..4]`。这些记录证明了错误分类、校验修复及计划冲突路径；不将未展示候选称作已向儿童发出的建议。

**K10：正确资料取回后，错误任务路由触发记录守卫。** 首批 K8/K9 用完五次真实请求，K10 的第六次请求发起检索；工具返回 H10:AwakeDefinition、H9:Diary 等片段，但下一次模型请求被该批 `max_requests=6` 拦下。首批报告 `ledger[5]` 仅证明模型收到初始 B1/B2，trace 的第二个 `model_calls` 为 error，不能把工具返回当作已被模型读取；最终展示“评估已停止：request_limit”，维持**批次额度中断、未完成**，不评分为知识错误。复测的 `ledger[6]` 明确包含 H10:AwakeDefinition、H9:Diary，且候选已解释两种 awake 定义并列出日记项目，证明资料被模型实际使用。然而 `query_plan.task=combined`、`response_plan.needs_interpretation=true`，页面 `selected_query` 非空，又尚无 `record_output`，于是冻结 `agent.py:631` 的条件直接触发“Obtain the requested record result with analyze_sleep…”守卫。该条件不要求先识别到某个字段句或个人数值，因此此前“字段定义被当作个人事实”的说法应具体化为**知识题误路由 combined，加上默认页面选择，触发缺少记录查询校验**。第三次模型请求随后调用 `analyze_sleep(P01, 2026-10-19, 2026-10-25, compare_previous=false)`，取得 7/7 晚、390 分钟的周均值，耗完应用单轮三次模型请求；循环结束记录 `error.code=model_limit`，回退设置 `verified_current_records`。最终展示“本轮解释未能通过依据核对，先展示已核实的记录。”及无关的 6 小时 30 分钟周均值，没有回答字段定义和日记问题，故维持**任务失败**。复测虽恰在共享预算 260/260、批次 8/8 时结束，trace 证明它触发的是应用单轮上限，不能归因为首批的批次截断。证据见首批 [K10 trace](evidence/knowledge-holdout-20261123T164342Z-f4eb2656/traces/chat-2af7842af0c648aab3241f0f310a5b59-001.json)、首批 [报告](evidence/knowledge-holdout-20261123T164342Z-f4eb2656/report.json) 的 `budget`／`ledger[5]`，以及复测 [K10 trace](evidence/knowledge-holdout-20261123T164510Z-59e9032b/traces/chat-4d126dfc5c654df999ab5b8b493d4793-001.json) 的 `answer_validation`、`tool_events[1]`、`error`、`verified_record_facts` 和复测报告 `ledger[5..7]`。

上述路径只做静态核对，未重新执行应用。用于定位的冻结源码为 agent.py（历史源码路径：`src/sleeplens/agent.py`，旧快照已清理）（计划检查 430–460 行、记录守卫 631–636 行、单轮循环及退出 398／712 行）、failure_display.py（历史源码路径：`src/sleeplens/failure_display.py`，旧快照已清理）（79–91 行）和 web.py（历史源码路径：`src/sleeplens/web.py`，旧快照已清理） 的 `verified_record_facts` 渲染。源码解释条件，trace 与请求账本确认该次实际发生了什么。

## 建议改分及待人工确认的汇总

以下均为 **AI 复核建议，未替换原 AI 初评**。三项建议改分为 K4 公开题：通过→失败；K8 留出首批：部分通过→失败；K9 留出首批：部分通过→失败。K6 暂保留部分通过、待确认定性概括是否可接受，其余维持原档位。请组员在 CSV 的“人工终评”“人工复核人”“人工改分理由”三列填写终评，三列目前均留空。

| 口径 | 公开题：通过／部分／失败 | 留出首批：通过／部分／失败／未完成 | 留出复测：通过／部分／失败 | 十题首次完整通过 |
| --- | --- | --- | --- | --- |
| 原 AI 初评，继续保留 | 4／3／0 | 0／2／0／1 | 1／0／2 | 4/10 |
| 若仅接受 K8、K9 首批两项改分 | 4／3／0 | 0／0／2／1 | 1／0／2 | 4/10 |
| 若三项建议改分全部确认，K6 保留部分 | 3／3／1 | 0／0／2／1 | 1／0／2 | 3/10 |
| 在上一行基础上，若人工另接受 K6 为通过 | 4／2／1 | 0／0／2／1 | 1／0／2 | 4/10 |

三项建议全获确认时，13 条运行合计将从 **5 通过、5 部分、2 失败、1 未完成**变成 **4 通过、3 部分、5 失败、1 未完成**；若再将 K6 改为通过，则为 **5 通过、2 部分、5 失败、1 未完成**。留出首次完整通过仍为 0/3，留出复测仍为 1/3。人工终评前不将这些条件汇总写成已确认成绩。

## 公网验收、复现和局限

此前的公网三轮演示属于**已有验收**，包括查周均、前周比较和结合记录给建议。冻结证据 [previous-public-acceptance.json](previous-public-acceptance.json) 保存了同一会话的三轮展示结果和诊断元数据；其中仍有 `needs_review`、`partial` 和回退状态，不能改写为三轮均完整通过。本轮 v2 知识评测运行冻结副本的代理层 `ChatSession`，**没有新增 v2 公网页面验收**，也没有统一重启公网进程后重新验收。

三个批次均记录实际响应型号 `deepseek-v4.1-flash-1017`；本地快照不能固定远端权重。复测报告显示共享预算已到 260/260、剩余零；本次复核没有新请求或重置预算。原始首答、失败、复测和原 AI 初评全部保留。后续若依据 K8–K10 修复，应另建冻结版本，将这些题纳入已知回归并准备新的留出题；原综合验收 Q9 仍未执行，不能将本知识集结果当作原九题综合验收成绩。

样本仅有十题，使用合成记录，知识人群覆盖有限，检索、生成、意图分类、校验及展示回退均可能造成失败。离线全通过没有消除实际任务失败；取回正确资料也没有保证用户拿到答案。这些证据支持报告具体能力与已观察边界，不支持将 SleepLens 描述为已验证的医疗工具或稳定全通过产品。
