# SleepLens

睡眠记录分析与问答 agent，提供网页对话、逐夜记录、统计图表和知识库解释。内置数据为合成示例数据。

## 安装和启动

需要 Python 3.11 或以上版本。在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在 `.env` 中填写自己的 API 密钥，并确认接口地址和模型名称与账号权限一致。已有 `.env` 时跳过复制，避免覆盖本地配置。

双击 `start_app.bat`，或运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

打开 http://127.0.0.1:8501 。浏览记录不调用模型；AI 问答会使用配置账号的 API 额度。

## 首次使用 / First visit

页面顶部介绍项目，并提供提问示例按钮；记录统计和说明可在“数据详情”与“关于 SleepLens / 使用说明”中查看。通过顶部语言选择切换中文或 English；数据、说明和示例跟随切换。展开左上角侧栏，可选择档案及单日或连续七天的醒来日期，再点击“查看记录 / Apply selection”。修改查询会开启新对话；“清空对话 / Clear conversation”保留当前记录选择。

首页六类提问覆盖单晚时长、深睡占比、完整阶段分布、有效七天均值或前周比较、深睡含义及判断边界。日期和字段来自当前档案，数据不足时不提供相应示例。点击按钮**仅填入聊天框**；可编辑并确认发送，点击本身不初始化模型或产生模型费用。“课堂测试示例”单独收纳无记录日期、诊断边界和范围外请求，用于检查系统如何处理限制。

“数据详情”区分原始字段与计算指标，列出无记录、已存在但不可用、不完整和重复日期；日期按最终醒来日归档。缺失不补零，范围内不保证每日都有完整记录。没有入睡潜伏期、上床时间、分期时间线或诊断评分。来源与计算详情只在回答有实际可展示内容时出现，便于核查相应内容。

SleepLens 面向成年用户，提供记录查询、计算、近期比较及有资料支持的一般睡眠解释；不提供疾病诊断或个人用药方案，资料或记录不足时说明限制。合成档案不对应真实个人；现有测试未证明改善睡眠或临床效果。

**English:** Choose a language at the top. Open the sidebar to select a synthetic profile and a completed waking date or seven-day period, then apply the selection. Example buttons only prepare a question: review it and send explicitly. Data details distinguish recorded and calculated metrics, absent dates, unavailable records and incomplete fields. Changing the selection starts a fresh conversation; Clear conversation keeps the selection. SleepLens is for adult record interpretation and general sleep information, with no diagnosis, personal medication plans or established clinical benefit.

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
.\.venv\Scripts\python.exe -m sleeplens analyze --profile P01 --start 2026-10-19 --end 2026-10-25 --compare-previous
```

## 文件说明

- `app.py`、`start_app.bat`：网页启动入口。
- `src/sleeplens/`：agent、工具、分析逻辑和网页界面。
- `src/sleeplens/resources/`：运行时读取的提示词、知识库和 Skill；其中的 Markdown 文件需要保留。
- `src/sleeplens/fixtures/display_sleep.json`：网页、命令行和问答工具默认使用的展示数据。
- `src/sleeplens/fixtures/synthetic_sleep.json`：保留的固定回归数据；已有脚本回复和规范示例中的数值以此为准。
- `scripts/build_display_dataset.py`：展示数据的固定种子生成器。
- `scripts/check_current.py`：当前版本的离线对话、双语回复、引用及上下文加载检查。
- `tests/`：当前实现的离线测试，覆盖计算、缺失数据、回答边界、安全、来源和聊天流程。
- `docs/improvement_examples.md`：四条实际改进案例；最少历史证据见同目录的 `improvement_evidence.json`。
- `docs/course_materials/`：保留的课程原始资料、作业要求、报告草稿及历史评测报告；详见其中的 `README.md`，不参与启动或测试。
- `docs/REVIEW_RUBRIC.json`：人工语义复核参考，自动校验不能替代人工评审。
- `artifacts/`：运行时按需生成的聊天诊断、分享日志及离线检查结果，不是启动入口。
- `pyproject.toml`：项目元数据和运行依赖；`requirements.txt` 通过 `-e .` 安装本项目及其依赖。
- `.env.example`、`.streamlit/config.toml`：环境变量模板和网页配置。

本地 `.env`、`.venv/`、`.state/` 和 `artifacts/` 不随源码分享。额度账本和运行日志会在需要时自动生成。交给组员的源码包括根目录入口与配置模板、`src/`、`scripts/`、`tests/` 和 `docs/`；各自在本机安装依赖并配置密钥。

展示数据版本为 `display-sleep-v1`，当前各档案的确切覆盖和缺口见页面“数据详情”或上方概览命令。P01作息有波动，偶尔出现较短的一晚；P02时间变化较大，有分散的记录缺口；P03相对稳定，但每晚时长、夜醒和分期也有变化。生成器使用固定种子 `20261124`，结合各档案的作息基线、相邻夜晚相关的时间波动、周末偏移和少量不规则事件；参数用于展示，未按真实人群拟合，也不代表某种睡眠模式的发生率。记录没有附加咖啡、压力等未经观察的原因。所有分期和时间戳均经过原有完整性校验，时刻保留柏林夏令时切换时的实际偏移。

检查生成结果可复现且数据有效，不会改写文件：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/build_display_dataset.py --check
```

不带 `--check` 可重新生成展示文件。固定回复回归测试显式加载原始回归数据，展示数据另有网页、工具与问答一致性测试。更新后的网页会重建当前对话以避免混用两份数据，保留已选档案和日期。

`SLEEPLENS_REQUEST_LIMIT=0` 表示取消累计调用次数上限，账本仍保留调用历史，并发限制仍由 `SLEEPLENS_MAX_CONCURRENT` 控制。填写正整数可重新启用累计上限；修改配置后重启应用生效。

## 校验与回归

当前版本：**prompt-v30 / sleep-analysis 3.6.0 / sleep-knowledge-v7 / classified-replies-v2**。当前提示词文件虽带版本号，仍由运行代码直接加载，必须保留。
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

课堂演示、组员测试及以后提交源码均使用根目录 `app.py` 和当前 `src/`。旧冻结运行包和旧打包脚本已清理。课程材料中的历史评分只描述当时版本，不能当作当前版本成绩。

选择 P01、新建对话，可依次测试：

- `2026-10-22的深睡占比是多少？`：只查询指定阶段。
- `2026-10-22的深睡占比正常吗？`：数值与当前判断依据限制。
- `查2026-11-20的深睡占比。`：区分无记录与查询失败。
- `那我这算失眠吗？`：个人诊断边界。

普通问答可能调用配置模型；离线验证使用上方测试命令，不需要为演示故意破坏数据文件。

本地公开展示使用当前根目录入口，PowerShell 命令为：

```powershell
.\start_public_share.ps1
# 自定义端口：.\start_public_share.ps1 -Port 8503
.\stop_public_share.ps1
```

分享脚本需要本地 `.venv/` 和 `.state/cloudflared.exe`，生成的临时地址、访问密码及进程信息保存在 `.state/public-preview-access.json`；停止脚本读取它来识别进程。旧 `-Classroom` 参数已移除。启动分享会访问外部隧道服务，须由主持人按需执行；本次清理未启动、停止或修改外部分享服务。模型认证、余额、实际回答与公网可达性仍需单独验证。
