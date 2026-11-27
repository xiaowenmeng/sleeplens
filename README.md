# SleepLens

睡眠记录分析与问答 agent，提供网页对话、逐夜记录、统计图表和知识库解释。内置数据为合成示例数据。

## 安装和启动

需要 Python 3.11 或以上版本。在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
```

在 `.env` 中填写自己的 API 密钥，并确认接口地址和模型名称与账号权限一致。已有 `.env` 时跳过复制，避免覆盖本地配置。

启动网页：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

macOS / Linux 使用 `.venv/bin/python -m streamlit run app.py`。下文命令均以 Windows 写法为例，macOS / Linux 将 `.\.venv\Scripts\python.exe` 换成 `.venv/bin/python` 即可。

打开 http://127.0.0.1:8501 。浏览记录不调用模型；AI 问答会使用配置账号的 API 额度。

## 首次使用 / First visit

页面顶部介绍项目，并提供提问示例按钮；记录统计和说明可在“数据详情”与“关于 SleepLens / 使用说明”中查看。通过顶部语言选择切换中文或 English；数据、说明和示例跟随切换。展开左上角侧栏，可选择档案及单日、连续七天或连续十四天（完整的两周记录）的醒来日期，再点击“查看记录 / Apply selection”。只有七天范围可以勾选“与前7夜比较”；查看十四天时，问“比上周多睡还是少睡”会比较这两周中较新的一周和较早的一周。修改查询会开启新对话；“清空对话 / Clear conversation”保留当前记录选择。

首页六类提问覆盖单晚时长、深睡占比、完整阶段分布、有效七天均值或前周比较、深睡含义及判断边界。日期和字段来自当前档案，数据不足时不提供相应示例。点击按钮**仅填入聊天框**；可编辑并确认发送，点击本身不初始化模型或产生模型费用。“课堂测试示例”单独收纳无记录日期、诊断边界和范围外请求，用于检查系统如何处理限制。

“数据详情”区分原始字段与计算指标，列出无记录、已存在但不可用、不完整和重复日期；日期按最终醒来日归档。缺失不补零，范围内不保证每日都有完整记录。没有入睡潜伏期、上床时间、分期时间线或诊断评分。来源与计算详情只在回答有实际可展示内容时出现，便于核查相应内容。

SleepLens 面向成年用户，提供记录查询、计算、近期比较及有资料支持的一般睡眠解释；不提供疾病诊断或个人用药方案，资料或记录不足时说明限制。合成档案不对应真实个人；现有测试未证明改善睡眠或临床效果。

**English:** Choose a language at the top. Open the sidebar to select a synthetic profile and a waking date, a seven-day period or the full fourteen days, then apply the selection. Only a seven-day range can be compared with the previous seven nights; while viewing fourteen days, asking how this week compares with the previous week compares the two weeks inside the view. Example buttons only prepare a question: review it and send explicitly. Data details distinguish recorded and calculated metrics, absent dates, unavailable records and incomplete fields. Changing the selection starts a fresh conversation; Clear conversation keeps the selection. SleepLens is for adult record interpretation and general sleep information, with no diagnosis, personal medication plans or established clinical benefit.

界面与以下离线命令复用同一数据概览和示例逻辑；日期、唯一日期数、有效夜数及缺失日期均按当前工具实际读取的文件生成，避免独立维护一份过时的概览：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m sleeplens.onboarding --language zh
.\.venv\Scripts\python.exe -X utf8 -m sleeplens.onboarding --language en
```

## 命令行

检查配置、查看知识库和分析数据均不调用模型：

```powershell
.\.venv\Scripts\python.exe -m sleeplens doctor
.\.venv\Scripts\python.exe -m sleeplens sources
# 最近七晚（含昨晚）：
.\.venv\Scripts\python.exe -m sleeplens analyze --profile P01 --start (Get-Date).AddDays(-6).ToString('yyyy-MM-dd') --end (Get-Date).ToString('yyyy-MM-dd') --compare-previous
```

## 文件说明

- `app.py`：网页启动入口，本地运行和 Streamlit Community Cloud 部署均使用它。
- `src/sleeplens/`：agent、工具、分析逻辑和网页界面。
- `src/sleeplens/resources/`：运行时读取的提示词、知识库和 Skill；其中的 Markdown 文件需要保留。
- `src/sleeplens/display_data.py`：网页、命令行和问答工具默认使用的展示数据，运行时按当天日期生成。
- `src/sleeplens/fixtures/display_sleep.json`：展示数据在固定日期（2026-11-26）的快照，供测试和离线检查使用。
- `src/sleeplens/fixtures/synthetic_sleep.json`：保留的固定回归数据；已有脚本回复和规范示例中的数值以此为准。
- `scripts/build_display_dataset.py`：写入或核对上述快照。
- `scripts/check_current.py`：当前版本的离线对话、双语回复、引用及上下文加载检查。
- `tests/`：当前实现的离线测试，覆盖计算、缺失数据、回答边界、安全、来源和聊天流程。
- `artifacts/`：运行时按需生成的聊天诊断、分享日志及离线检查结果，不是启动入口。
- `pyproject.toml`：项目元数据和运行依赖；`requirements.txt` 通过 `-e .` 安装本项目及其依赖。
- `.env.example`、`.streamlit/config.toml`：环境变量模板和网页配置。

本地 `.env`、`.venv/`、`.state/` 和 `artifacts/` 不随源码分享。额度账本和运行日志会在需要时自动生成。交给组员的源码包括根目录入口与配置模板、`src/`、`scripts/` 和 `tests/`；各自在本机安装依赖并配置密钥。

展示数据版本为 `display-sleep-v1`，始终覆盖截至今天（Europe/Berlin）的最近14个醒来日期，包括今天醒来的昨晚，因此数据不会过期。同一天内页面、工具和问答看到的记录完全一致；日期变化后整个窗口向前滚动，同一日历日期的数值可能与前一天看到的不同，已打开的页面会自动切换到新窗口并开始新对话。当前各档案的确切覆盖和缺口见页面“数据详情”或上方概览命令。P01作息有波动，偶尔出现较短的一晚；P02时间变化较大，有分散的记录缺口；P03相对稳定，但每晚时长、夜醒和分期也有变化。生成器使用固定种子 `20261124`，结合各档案的作息基线、相邻夜晚相关的时间波动、周末偏移和少量不规则事件；参数用于展示，未按真实人群拟合，也不代表某种睡眠模式的发生率。记录没有附加咖啡、压力等未经观察的原因。所有分期和时间戳均经过原有完整性校验，时刻保留柏林夏令时切换时的实际偏移。

“昨晚”和“昨天”都指今天早上醒来的那一晚（今天的醒来日期），“前天”指昨天醒来的那一晚；“今晚”属于明天的醒来日期，尚不能查询。

检查快照与生成器一致且数据有效，不会改写文件：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/build_display_dataset.py --check
```

不带 `--check` 可重新写入快照；修改生成参数后需要更新快照。固定回复回归测试显式加载原始回归数据，展示数据另有网页、工具与问答一致性测试。更新后的网页会重建当前对话以避免混用两份数据，保留已选档案和日期。

`SLEEPLENS_REQUEST_LIMIT=0` 表示取消累计调用次数上限，账本仍保留调用历史，并发限制仍由 `SLEEPLENS_MAX_CONCURRENT` 控制。填写正整数可重新启用累计上限；修改配置后重启应用生效。

## 校验与回归

当前版本：**prompt-v1 / sleep-analysis 3.6.0 / sleep-knowledge-v1 / classified-replies-v2**。当前交付基线的 prompt 与 knowledge 从 v1 开始编号；提示词文件 `src/sleeplens/resources/prompts/system_v1.md` 由运行代码直接加载，必须保留。

课程历史报告、改进证据、既有运行日志和 Git 历史仍保留各自的原始版本标识；这些记录不属于当前 v1 的评测结果。
首次使用测试时安装测试依赖：`.\.venv\Scripts\python.exe -m pip install -e ".[test]"`。
随后在项目根目录运行以下命令，均不调用付费模型：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
.\.venv\Scripts\python.exe -X utf8 scripts/check_current.py
.\.venv\Scripts\python.exe -X utf8 scripts/build_display_dataset.py --check
```

`pytest` 默认只收集 `tests/`。测试阻止真实模型调用与外部网络连接，保留框架内部需要的本机回环连接。

所有活动测试使用当前应用、提示词、业务规范和知识库。`synthetic_sleep.json` 继续用于可控的固定数值回归，`display_sleep.json` 用于当前展示与工具一致性，两者不混用。离线回放读取自包含输入，不依赖旧聊天日志、旧源码或历史哈希清单。

`check_current.py` 每次在 `artifacts/checks/` 新建结果目录，也可用 `--output` 指定新目录；已存在的目标会被拒绝，避免覆盖旧结果。检查中的回复均为人工候选，离线通过不等于真实模型生成质量已改善。

仍待人工验证的事项包括非数值主张的完整语义支持、真实模型表达、用户帮助程度与线上服务表现；合法引用和正确数值不能替代这些验证。

`tests/test_single_night_experience.py` 保护主观反馈与日期关联、双语界面及真实数据缺口；`tests/test_reply_intent_scope.py` 保护单项查询范围、正常性判断边界和诊断追问；`tests/test_stage_assessment_fallback.py` 保护相对日期、分母和失败处理。完整测试中也保留来源、安全、计算及聊天流程检查。

## 课堂演示与分享

课堂演示、组员测试及以后提交源码均使用根目录 `app.py` 和当前 `src/`。

选择 P01、新建对话，可依次测试：

- `昨晚的深睡占比是多少？`：只查询指定阶段。
- `昨晚的深睡占比正常吗？`：数值与当前判断依据限制。
- `查2026-01-05的深睡占比。`：区分无记录与查询失败（早于最近两周，没有记录）。
- `那我这算失眠吗？`：个人诊断边界。

普通问答可能调用配置模型；离线验证使用上方测试命令，不需要为演示故意破坏数据文件。

### 在线分享（Streamlit Community Cloud）

在线版本部署在 Streamlit Community Cloud，入口文件为 `app.py`，依赖由 `requirements.txt` 安装。配置写在应用的 **Settings → Secrets** 中，不要提交到仓库；顶层的 secrets 会作为环境变量提供给应用，与本地 `.env` 使用相同的名称：

```toml
DEEPSEEK_API_KEY = "..."
DEEPSEEK_BASE_URL = "https://api.chatanywhere.tech/v1"
DEEPSEEK_MODEL = "deepseek-v4-flash"
SLEEPLENS_SHARE_MODE = "1"
SLEEPLENS_SHARE_PASSWORD = "至少12个字符的访问密码"
SLEEPLENS_SHARE_LOG_DAYS = "7"
SLEEPLENS_REQUEST_LIMIT = "300"
```

公开链接任何人都能打开，因此建议开启分享模式：访客需输入访问密码，并在使用前确认说明（合成数据、只用虚构情境、问题会发送给第三方模型服务、只保留不含对话内容的运行记录）。分享模式下只记录运行元数据，不保存问答内容。`SLEEPLENS_REQUEST_LIMIT` 设为正整数可限制模型调用总次数，避免额度被耗尽；调用账本保存在应用容器内，应用重启或重新部署后会重新计数。修改 secrets 后，在 Cloud 控制台中重启应用（Reboot app）以确保新配置生效。

本地也可以在 `.env` 中设置 `SLEEPLENS_SHARE_MODE=1` 和访问密码，预览同样的密码页和说明页。模型认证、余额、实际回答与公网可达性仍需在部署后单独验证。
