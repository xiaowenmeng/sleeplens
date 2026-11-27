# SleepLens v1: Evaluation, Version Management and Business Case Plan

Date: 2026-11-27  
Status: Implementation plan; the formal measurements described here have not yet been completed under this plan.

This plan establishes the current v1 as the first verifiable baseline. Define the metrics and accounting rules before testing, then compare quality, cost and latency after each update. All numerical thresholds below are proposed starting points, not instructor requirements or observed results. Finalize them before formal testing.

## Existing Foundations and Main Gaps

The project already has a review rubric, offline tests and request logs. The main gaps are:

- A unified connection between business objectives, evaluation metrics and acceptance thresholds.
- A complete agent release record linking code, prompt, knowledge, business skill and data.
- Request, cost and latency accounting across tasks that span multiple turns.
- A business case worksheet supported by comparison data, cost sources and explicit scenario assumptions.

The existing rubric is `docs/REVIEW_RUBRIC.json`. Align its version label with the current v1 during implementation.

## 1. Define Business Objectives, Metrics and Acceptance Thresholds

Business objective: help adults understand their existing sleep records faster and more accurately, and assess whether offering this feature is worth the brand's investment.

| Objective | Metric | Proposed Initial Acceptance Threshold |
| --- | --- | --- |
| Complete the user's task accurately | Complete-task pass rate: correct, complete, within the requested scope and supported by applicable evidence | ≥90%; also report successes/attempts |
| Read and calculate records correctly | Accuracy of dates, profiles, denominators, values and missing-data handling | 100% on the test set, allowing specified rounding tolerances |
| Maintain safety boundaries | Counts of fabricated records, unauthorized actions, secret disclosure, unsupported diagnoses or personalized medication regimens | Zero observed severe failures; any such failure blocks progression to a pilot |
| Respond consistently | Proportion of cases passing every repeated run | ≥80%; retain the outcome of every run |
| Provide an acceptable experience | Elapsed time for user turns involving model requests | Provisional median ≤15 seconds and P95 ≤30 seconds |
| Improve on the existing process | User comprehension accuracy and task completion time | Accuracy at least as high as the comparison process; median completion time reduced by ≥20% |

Evaluate these criteria separately. Strong writing cannot compensate for wrong numbers or a severe boundary violation. Zero observed severe failures in a small sample does not mean zero risk. Report the sample size alongside latency percentiles.

Retain the existing rubric while clearly separating task success, factual/evidence correctness and clarity of expression. Freeze the rubric and thresholds before formal testing. Explain and version any later changes.

## 2. Establish Agent Releases and Evaluation Records

Introduce an overall `agent_version`, starting with `agent-v1`. Keep separate versions for the prompt, knowledge and business skill. Save the complete configuration and file hashes for every evaluation.

| Release Record | Required Information |
| --- | --- |
| Release identity | Agent, prompt, knowledge, business skill, code and data snapshot |
| Runtime conditions | Date, requested model, actual response model, service endpoint and generation parameters |
| Evaluation conditions | Test-set version, rubric version, repetition count and reviewer |
| Results | Task pass rate, repeated-run consistency, severe failures, cost and latency |
| Reason for change | Issue ID, original evidence, root cause, principal change, same-case retest and regression results |

Use the following process for future updates:

1. Register the issue and preserve the original input, final displayed answer and execution trace.
2. Diagnose the cause, distinguishing instructions, knowledge, retrieval, generation, tools, task routing and service failures.
3. Publish a new agent release, such as `agent-v2`, with its principal changes and component versions.
4. Retest the original case under the same conditions and run the fixed regression suite.
5. Compare repaired cases and newly failing cases, including changes in cost and latency.
6. Use cases not previously used for tuning for the final check. Once a case informs a fix, treat it as a known regression case thereafter.

Keep case-level comparisons rather than reporting totals alone. The summary table below is a template; all values await measurement.

| Release | Complete Passes/Attempts | Cases Passing Every Repeat | Severe Failures | Fixed/New Failures | Cost per Successful Task | Median/P95 Latency |
| --- | --- | --- | --- | --- | --- | --- |
| agent-v1 | To measure | To measure | To measure | Baseline | To measure | To measure |
| agent-v2 | To measure | To measure | To measure | Compared with v1 | To measure | To measure |

Do not pool results from different code or data snapshots merely because their release labels match. Identify changes to the test set or rubric; those results are not automatically directly comparable.

## 3. Complete Operational Accounting

### 3.1 Define the Units

- **Model request:** one actual API call.
- **User turn:** one question submitted by the user; it may trigger multiple model requests.
- **Business task:** one user objective; it may require several conversational turns.

Add a `task_id` to link the turns and requests belonging to one task. Record per-request latency, input/output usage, error types, corrective calls and the final task outcome.

### 3.2 Address Existing Measurement Gaps

- The local-answer branch currently reports elapsed time as `0`. Replace this with measured time. Zero API cost and zero elapsed time are separate claims.
- Shared-mode logs mainly retain total tokens. Accurate pricing also requires metadata such as input/output usage, actual model and pricing source. Preserve the existing practice of excluding conversation text from shared-mode logs.
- Distinguish model-call attempts from API requests actually sent. A quota rejection before sending is not a sent request.
- Preserve failed, timed-out and additional calls. Mark unavailable usage as unknown rather than assuming it was free.

### 3.3 Summarize Cost and Latency

Report cost and elapsed time per model request, user turn and business task. Separate local answers from answers involving model requests.

> Average API cost per successful task = API cost of all tasks in the batch ÷ number of successful tasks

The numerator includes failed tasks, corrective calls and additional calls. Do not calculate this metric when no task succeeds. Disclose incomplete usage data rather than pricing unknown calls at zero.

The price table must identify the actual provider, model, billing category, currency, verification date and source. Verify prices when preparing the formal calculation; this plan supplies no monetary estimates. Label estimated costs and actual provider charges separately.

### 3.4 Document Dependencies and Recovery

Create a dependency table covering the model service, any intermediary endpoint, hosting, network and local resources. For each dependency, record its purpose, failure symptoms, existing controls, recovery procedure and responsible maintainer.

## 4. Run a Formal v1 Evaluation

Start with **12 development tasks and 4 final holdout tasks, repeated three times each**, adjusting the scope to the available budget. These are project proposals, not instructor-mandated counts.

Cover the following task types:

- Normal record queries and knowledge explanations.
- Missing or unavailable records and comparison eligibility rules.
- Date/profile changes and multi-turn follow-ups.
- Out-of-scope requests, adversarial attacks and service failures.

Freeze the data snapshot before testing so that rolling dates do not change the answer key. Automatically check numbers, arguments and tool results. Human reviewers check whether the final answer visible to the user is complete and supported. AI-assisted grading must be calibrated against human grades.

Report overall results, results by task type and repeated-run consistency. Record unexecuted, interrupted and partially successful attempts separately. Forty-eight task attempts are neither 48 independent cases nor 48 model requests. Calculate the budget from each task's maximum turns and request limits.

## 5. Build the Business Case Worksheet and Run a Comparison

### 5.1 Worksheet Structure

| Worksheet | Contents |
| --- | --- |
| Inputs and Sources | Usage volume, labor rates and API prices; label each input as measured, externally sourced or assumed |
| User Task Comparison | Time, accuracy and error types when using existing charts/documentation versus SleepLens |
| Operating Costs | API, hosting, review, content maintenance, regression testing and one-time development investment |
| Business Scenarios | Costs, monetizable benefits and break-even conditions under conservative, base and optimistic assumptions |
| Conclusions and Evidence | Demonstrated findings, remaining assumptions and a recommendation to improve or pilot |

### 5.2 Small User Comparison

Recruit **6–8 classmates** initially. Use tasks involving value lookup, two-week comparison, missing-data interpretation and understanding metrics. Compare:

- The comparison process: inspect existing charts and field documentation and complete the task manually.
- The SleepLens process: use the assistant to complete a task of matched difficulty.

Use two matched sets of questions and alternate the order of the two processes to reduce memory and practice effects. Record comprehension accuracy, completion time and error types. Treat the small sample as exploratory evidence. Multiple tasks and repeated actions do not constitute additional independent participants.

### 5.3 Separate User Value from Brand Returns

- **User value:** less time spent interpreting records and better comprehension accuracy.
- **Brand value:** possible reductions in support work, improved experience or paid revenue, each requiring appropriate evidence.

Do not multiply users' saved time by the brand's employee wage rate and call the result cash savings. Use the following brand-level calculation:

> Monthly net benefit = attributable support cost savings + evidence-supported incremental gross profit − API − hosting − review − maintenance − expected error-handling costs

Keep benefits without supporting evidence as scenario assumptions. Show development investment separately. Each scenario must state its assumptions about volume, adoption, task success, human intervention and maintenance, and identify which variables change the break-even conclusion.

Proposed business acceptance criterion: the user comparison meets its predefined targets and the base scenario supports investment; losses and residual risks in the conservative scenario can be explicitly explained and accepted.

## Implementation Order and Deliverables

1. Complete Sections 1 and 2: define metrics, thresholds, the rubric and release-record structure.
2. Complete Section 3: add task linkage, request accounting, measured latency and cost calculation.
3. Freeze the code, configuration and data for the v1 used in formal testing.
4. Execute Sections 4 and 5: live-model evaluation, human review, user comparison and business calculations.
5. Produce a consistent evaluation protocol, case-level scores, release comparison, operational summary and business case worksheet.

This document plans future work. Proposed thresholds, sample sizes and scenario amounts must not be presented as completed measurements.
