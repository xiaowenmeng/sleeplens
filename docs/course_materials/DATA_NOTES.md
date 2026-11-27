# Synthetic test-data notes

This classroom runtime uses **display-sleep-v1**, copied byte-for-byte from the current working project. The legacy **synthetic-sleep-v2** fixture and frozen evaluation data are preserved and are not used as the reference values for the classroom display examples. No data was added or overwritten.

| Profile | Age | Synthetic scenario | 12–25 Oct valid nights |
| --- | ---: | --- | ---: |
| P01 | 28 | Variable timing with occasional shorter nights | 14/14 |
| P02 | 35 | Later, more variable timing and scattered gaps | 11/14 |
| P03 | 42 | Relatively steady timing with ordinary variation | 14/14 |

There are 41 stored rows for 42 profile/date slots: P02 on **2026-10-20** is absent; P02 on **2026-10-14** and **2026-10-24** are stored unavailable rows with null measurements. Missing and unavailable rows are both excluded from means, never filled with zero. Outside-range dates such as P01 on **2026-11-01** return no data; they are valid completed dates, not invalid calendar dates.

The loader checks profile IDs and ages, unique profile/date keys, valid dates, minute/validity consistency, stage totals and complete optional details. Timestamp validation checks Europe/Berlin offsets and elapsed UTC minutes; 25 October crosses the Berlin clock change. Present detail fields are `sleep_onset`, `wake_time`, `night_awakenings`, `awake_min`, `deep_sleep_min`, `light_sleep_min`, `rem_sleep_min`, plus `profile_id`, `record_date`, `sleep_min`, `sleep_valid`. No bedtime, sleep-latency, coffee/stress, free-text notes, diagnosis or clinical sleep-quality score is recorded.

## Reference scenarios actually calculated offline

| Scenario | Valid nights | Mean sleep (min) | Comparison |
| --- | --- | ---: | --- |
| P01, 19–25 Oct | 7/7 | 446.285714… | Previous 12–18 Oct: 437.142857…; difference +9.142857… |
| P02, 19–25 Oct | 5/7 | 436.8 | Previous 12–18 Oct: 6/7, 420.5; difference +16.3 |
| P03, 19–25 Oct | 7/7 | 459.142857… | Previous 12–18 Oct: 468; difference −8.857142… |
| P03, 20 Oct only | 1/1 | 386 | 2 awakenings, 33 awake minutes; deep/light/REM 69/225/92 |
| P02, 20 Oct only | 0/1 | null | Missing record |
| P02, 24 Oct only | 0/1 | null | Unavailable record |
| P01, 1 Nov only | 0/1 | null | No stored record |
| P01, 12–18 Oct with previous comparison | 7/7 | 437.142857… | Previous 5–11 Oct: 0/7; comparison withheld |

Exact tool payloads for the main scenarios are in `DATA_VERIFICATION.json`. Means use only valid nights, and the four-valid-night gate in **each** period controls whether a weekly difference is displayed. This gate is a product policy, not a medical/statistical guarantee. A valid zero could be represented by the schema but is not present in display-sleep-v1; no zero record was manufactured for class.

The example prompts refer to existing users, dates and fields. Data availability and deterministic calculations were checked; live-model understanding, English wording, advice correctness and resilience to attacks remain unverified. Do not reuse frozen v2 numerical answer keys for this display dataset (for example, the old P01 weekly mean of 390 minutes is not the current display reference).
