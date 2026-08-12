# LLM-judge Scale Expansion — Amendment v2 (Pre-registration)

**Status.** Pre-registration amendment to
`docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md` and to
`docs/LLM_JUDGE_AMENDMENT_v1.md`. Per `feedback_rule_8`, this document is
pushed and PR-opened before any measurement code or diagnostic script
runs. Sample expansion, cost budget, sampling protocol, and pre-committed
prediction bands below are frozen; adjusting after seeing results is
not allowed.

**Motivation.** Amendment v1 (2026-08-06) established the LLM-judge
detector's post-parser-fix precision at `matches / pairs = 83 / 159 =
0.5220` on 5 CC sessions. The base prereg §12 GO threshold (≥5%) was
cleared decisively, but n=5 is a fragile evidentiary base — the 95%
CI on `0.5220` from 5 sessions spans roughly `[0.30, 0.75]`, wide
enough that the "post-parser-fix precision is materially above 5%"
claim is defensible but "precision is 52%" as a headline number
overstates the certainty.

This amendment locks a scale expansion (5 → 48 sessions) to tighten
the CI, add cross-corpus generalization evidence (Toolathlon
non-coding tasks alongside Corpus A coding sessions), and produce a
Beta-pitch-ready number that survives external replication.

## 0. Honesty preface (what this expansion is and is not)

**What this expansion does:**

- Runs the identical amendment-v1 rubric (system prompt + response
  parser) against a 48-session pool: 28 CC sessions
  (all of `data/hf_recon/trace_commons_paths.txt`) plus 20 Toolathlon
  trajectories sampled deterministically from the frozen §2 manifest.
- Reports precision separately per corpus (CC 28 vs. Toolathlon 20)
  AND unified across the 48-session pool, so cross-corpus divergence
  (if any) is visible not hidden.
- Reports 95% bootstrap CI on the unified precision, bounded by the
  fixed sample size.
- Cost cap ≤ $3.00 (~10× the v1 re-measurement budget, still small).

**What this expansion does NOT do:**

- Does not change the detector spec (system prompt, response parser,
  Jaccard pre-filter threshold `0.30`, 50-pair-per-session cap) —
  those are locked at amendment v1.
- Does not add a recall measurement. Recall requires labeled ground
  truth on the same 48 sessions, which does not exist. Precision on
  judge-evaluated pairs remains the single reported number.
- Does not commit to any specific new precision value. The
  re-measurement is the question, not the answer. Prediction bands
  in §4 are the pre-committed expectation; misses are documented in
  §8 honestly.
- Does not touch Corpus A `WR_char / WR_cost / SDR@10` numbers from
  `WASTE_RATE_METRIC_PREREG.md` §13.1 (a different measurement).
- Does not add a "labeled subset ground truth" measurement. See §6.4
  for the reason and the follow-up hook.

## 1. Session pool (frozen)

### 1.1 CC subset (28 sessions)

All entries of `data/hf_recon/trace_commons_paths.txt` (already frozen
in `WASTE_RATE_METRIC_PREREG.md` §2.1 with manifest sha256
`<from the wasterate prereg>`; the same manifest applies here).

Rationale: n=28 fully replicates the v1 pool (5) plus 23 previously
unmeasured CC sessions. This gives a clean expansion of v1's
precision estimate on the same corpus type.

### 1.2 Toolathlon subset (20 sessions)

**Deterministic sampling:**

- Source: same frozen manifest as
  `docs/WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md` §2
  (sha256 `9648d18876685ae54ee20abcb88e191f0914f20f2025ff38a9d2cedb0699d4f7`,
  66 files, 6,780 trajectories).
- Sampling method: `random.Random(seed=42)` shuffle over
  `sorted((file_name, line_number))` pairs of successfully-built
  trajectories from `waste_rate_metric_toolathlon_v2.RESULTS.json`
  (`built=True` rows only, i.e. `agent_llm_requests > 0`). Take
  first 20.
- Fixed seed guarantees reproducibility. The sampling script emits
  the 20 `(file_name, line_number)` pairs to a companion file
  `field_test/diagnostics/llm_judge_v2_toolathlon_sample.json`
  (uncommitted, but the pairs are appended to §8 of this document at
  results time for future reproducibility).

Rationale: 20 sessions gives a cross-corpus check without exhausting
budget. Toolathlon's `tool_use_id` structure (`call_79190340`,
`call_52801306` — 8-hex-suffix) differs from CC's
(`toolu_01FfKEsX3F8hLwKHu1RJZYjQ` — 22-char base62). The v1
ephemeral-ID clause was written against CC's pattern; whether it
generalizes to Toolathlon's pattern is one of the questions this
scale expansion answers.

### 1.3 Total: 48 sessions

## 2. Detector configuration (unchanged from v1)

- System prompt: as in amendment v1 §1.1 (with ephemeral-ID clause).
- Response parser: as in amendment v1 §1.2 (fence-stripping).
- Judge model: `claude-haiku-4-5`.
- Jaccard pre-filter threshold: `0.30`.
- Max pairs judged per session: `50` (cap).
- Match confidence gate: `≥ 0.85`.

**Not changed.** This is a scale expansion, not a rubric change.

## 3. Cost budget (frozen)

**Per-session cost from v1:** average $0.027 per CC session (5
sessions, $0.133 total).

**Projected 48-session cost:** $1.30 baseline (mid-estimate).

**Hard cap:** **$3.00** (2× safety factor above baseline).
Running total exceeding $2.70 → soft warn; exceeding $3.00 → hard
stop, remaining sessions unmeasured, results section documents which
sessions were dropped.

## 4. Predictions (pre-committed)

**P1a · CC precision.** Precision on the 28 CC sessions will fall in
`[0.40, 0.60]`. Rationale: v1's 5-session estimate 0.5220 is the
best available prior; expansion to 28 with the same rubric should
stay near this value unless new sessions have systematically
different tool_result patterns.

**P1b · Toolathlon precision.** Precision on the 20 Toolathlon
sessions will fall in `[0.10, 0.60]`. Rationale: wider band because
v1's ephemeral-ID clause was designed against CC's `toolu_*`
identifier pattern; Toolathlon uses `call_*` pattern, and the clause
may under- or over-fire.

**P2 · Unified precision CI width.** 95% bootstrap CI (`n_boot=1000`,
`seed=42`) on the unified 48-session precision will have width
`≤ 0.15`. Rationale: n=48 vs. n=5 shrinks the CI ~3× under the
central limit theorem; 0.15 is a conservative expected width.

**P3 · Ephemeral-ID pattern dominance.** Of matches found on the CC
subset, ≥ 70% will cite tool_result / tool_use_id equivalence as
their primary reasoning (v1 §4.3 attribution). Rationale: v1
attribution showed ~96% of matches (80/83) followed this pattern;
70% is the conservative lower bound preserving the amendment v1
attribution claim.

**What would violate expectations (would trigger honest §8 note):**

- Any P1a / P1b / P2 / P3 miss.
- Unified precision below v1's 5% base-prereg GO threshold (would
  invalidate the amendment v1 GO — critical failure, backout §5).
- Cost budget exceeded before all 48 sessions measured.

Meeting predictions is not evidence of correctness — it is
consistent-with-expectation. Missing them triggers a diagnostic
note but does not invalidate v1's GO judgment (unless P1a drops
below 5% GO).

## 5. Backout plan

- If unified precision < 5% (below base prereg GO threshold): open
  a critical review, do not update the amendment v1 GO status
  post-hoc, publish the miss with root cause diagnostic, plan v3.
- If cost budget exceeded before completion: run partial pool
  results, document dropped sessions honestly in §8, no post-hoc
  band adjustment.
- If Toolathlon sample-file structure differs from expectation
  (e.g. some `built=True` traces produce zero judged pairs due to
  Jaccard pre-filter never triggering): document count, adjust
  reporting to precision-on-actually-judged, do not re-shuffle.

## 6. Method

1. **Sampling script:** `field_test/diagnostics/llm_judge_v2_sample.py`
   (new, uncommitted per `feedback_diagnostics_uncommitted`).
   Reads `waste_rate_metric_toolathlon_v2.RESULTS.json`,
   deterministically samples 20 `built=True` trajectories with
   `random.Random(seed=42)`, emits companion file.
2. **Measurement script:** extend
   `field_test/diagnostics/llm_judge_go_nogo_measurement.py` (existing,
   uncommitted) to loop over both corpora with the 48-session pool.
   Each session's LLM-judge invocations follow the v1 detector
   config (§2).
3. **Unified precision + per-corpus precision computed.**
4. **Bootstrap CI:** `n_boot=1000`, `seed=42`, weighted-ratio
   resampling over the union of all judge invocations.
5. **Match attribution:** re-run the v1 §4.3 keyword classifier on
   post-amendment matches; report per-corpus tool_result-pattern
   share.
6. **Cost accounting:** running total per session; hard stop at $3.00.
7. **Append results as §8** of this document.

### 6.4 Why no ground-truth labeled recall measurement

Recall would require: for each of the ~50 candidate pairs per
session (post-Jaccard-pre-filter), a human label of "true semantic
duplicate" or "not". At 48 × 50 = 2,400 pairs, hand-labeling would
take ~30 hours and remains susceptible to labeler bias. Deferred
to a future v3 or dedicated recall-benchmark prereg.

## 7. Explicit non-commitments

- Not committing that the CC 28-session precision will remain at
  0.5220. It may shift up or down; §4 bands allow both.
- Not committing that Toolathlon precision will be comparable to CC.
  Cross-corpus divergence is a scientific outcome, not a threshold
  gate.
- Not committing to a v3 amendment. Depends on §8 findings.
- Not committing the exact 20 Toolathlon `(file, line)` pairs at
  prereg time — those are determined by seed 42 at run time. The
  determinism guarantees reproducibility.

## 8. Commit chain (per `feedback_rule_8`)

Three commits, no squash/rebase:

1. `docs: LLM-judge Scale Expansion Amendment v2 prereg` — this file
   only. PR opened for approval.
2. **After approval:** `feat(llm_judge): scale expansion measurement
   scripts` if any code change required (probably no source change,
   only diagnostic scripts which stay uncommitted; if so, this
   commit becomes `docs: sampling record + measurement notes` or is
   folded into commit 3).
3. `docs(llm_judge): append §9 Scale Expansion results` — final
   post-measurement append.

## 9. Results (executed 2026-08-11 → 2026-08-12)

### 9.1 Scan metadata

- **CC subset:** 28 sessions from `data/hf_recon/trace_commons_paths.txt` (§1.1).
- **Toolathlon subset:** 20 `(file, lineno)` pairs sampled by `random.Random(seed=42)` over sorted `built=True` rows of `waste_rate_metric_toolathlon_v2.RESULTS.json` (§1.2). Deterministic sample; full pair list committed to `field_test/diagnostics/llm_judge_v2_expansion.RESULTS.json` `toolathlon_sample_pairs` field.
- **Judge model:** `claude-haiku-4-5` (§2).
- **Detector config:** v1 rubric unchanged (system prompt + parser).
- **Sampling seed:** 42.
- **Bootstrap:** 1000 iterations, seed 42.
- **Elapsed:** ~12h wall time (started 21:24 KST 2026-08-11, completed early 2026-08-12). Estimate of 1.5-2h in §3 was materially wrong — actual latency dominated by per-pair Anthropic API round-trip (average ~2s per call, well above the naïve arithmetic assumption). Documented; not a scientific issue.
- **Cost:** **$2.5779** (86% of §3 hard cap $3.00; below §3 hard-stop $2.70 by $0.12).
- **Coverage:** all 48 sessions successfully measured. No sessions dropped, no adapter errors.

### 9.2 Per-corpus aggregate

| Corpus | n_sessions | matches | pairs | precision |
|---|---:|---:|---:|---:|
| A · CC (trace-commons) | 28 | 571 | 1,178 | **0.4847** |
| B · Toolathlon (seed-42 sample) | 20 | 96 | 924 | **0.1039** |
| Unified | 48 | 667 | 2,102 | **0.3173** |

### 9.3 Unified 95% bootstrap CI (n=1000, seed=42)

| Statistic | Value |
|---|---:|
| Lower 2.5% | 0.2311 |
| Median | 0.3176 |
| Upper 97.5% | 0.4103 |
| **CI width** | **0.1792** |

### 9.4 Ephemeral-ID attribution (§4 P3 basis)

Match reasoning classified by v1 §4.3 keyword set (`tool_use_id`, `ephemeral`, `identifier`, etc.):

| Corpus | matches classified as ephemeral-ID | total matches | share |
|---|---:|---:|---:|
| CC | 548 | 571 | **95.97%** |
| Toolathlon | 85 | 96 | **88.54%** |

### 9.5 Prediction verdict (§4)

| ID | Prediction band | Observed | Verdict |
|---|---|---|---|
| **P1a** | CC precision ∈ [0.40, 0.60] | **0.4847** | ✅ **PASS** |
| **P1b** | Toolathlon precision ∈ [0.10, 0.60] | **0.1039** | ⚠️ **PASS (grazes lower bound)** |
| **P2** | Unified CI width ≤ 0.15 | **0.1792** | ❌ **MISS (+0.029 over)** |
| **P3** | CC ephemeral-ID share ≥ 70% | **95.97%** | ✅ **PASS** |
| Base-prereg GO threshold (unified ≥ 0.05) | 0.3173 | ✅ well above; v1 GO stands |

**3/4 pass. P2 CI-width miss documented honestly per §4 non-commitment 3.**

### 9.6 P2 CI-width miss · honest root cause

The 95% CI on the unified precision spans **[0.2311, 0.4103]**, width **0.179** — just above the predicted `≤ 0.15` ceiling. Root cause is per-session heterogeneity that the n=5 v1 sample masked:

- **CC per-session precision spread:** min 0.000 (2 sessions: `674e0f5c` with 14 pairs / 0 matches; `da6566ff` with 5 pairs / 0 matches), max 0.940 (`09d9abe9`).
- **Toolathlon per-session precision spread:** min 0.000 (5 sessions: `claude-4.5-haiku-1001_2`, `gpt-5_3`, `gpt-5.1_2`, `gemini-3-pro-preview_1`, `gemini-2.5-flash_2`), max 0.580 (`grok-4-fast_3`).

Bootstrap resampling over sessions surfaces this heterogeneity; the wider CI is the honest reflection of what an n=48 sample actually supports. Tightening below 0.15 would require either n ≥ ~80 or a stratified sampling design that reduces between-session variance. **Neither is done post-hoc; the miss stands.**

### 9.7 Honest interpretation

**Detector precision is real, but narrower than the v1 headline number suggested.**

The v1 precision 0.5220 (n=5) sat comfortably above 0.30 in this expansion, but the point estimate on n=48 is **0.3173** (unified), not 0.52. The v1 number was measured on 5 CC sessions where the tool_result / tool_use_id pattern was concentrated. On a broader CC sample (28), the pattern remains dominant but per-session precision is more variable — some sessions have very few or no such repetitions.

**Extrapolating to Toolathlon (non-coding tool-use):** precision drops to **0.104**, indicating that the v1 ephemeral-ID rubric — designed against CC's `toolu_*` identifier pattern — captures a much smaller share of Toolathlon's `call_*` pattern. The 88.54% ephemeral-ID share within Toolathlon matches means that when the detector *does* find a semantic match on Toolathlon, it is almost always the same tool_use_id repetition pattern; but such matches are rarer per session because Toolathlon trajectories use more diverse tool sequences with fewer verbatim tool_result repeats.

**What is safe to say in pitch material:**

- ✅ "LLM-judge precision on 48 measured agent sessions: **31.7%** (95% CI [23.1%, 41.0%])."
- ✅ "On Claude Code coding sessions (n=28): **48.5%** precision. On Toolathlon non-coding trajectories (n=20): **10.4%**."
- ✅ "96% (CC) / 89% (Toolathlon) of matches attribute to `tool_use_id` ephemeral-identifier equivalence."
- ⚠️ **What is NOT safe:** "LLM-judge finds 52% semantic duplicates" (the v1 headline). That number came from n=5 and does not survive n=48. **Corrected number is 31.7% unified or 48.5% CC-only.**

### 9.8 New finding · Model family effect on Toolathlon

Top Toolathlon precision by model:

| Model family (Toolathlon session) | Precision |
|---|---:|
| grok-4-fast (`grok-4-fast_3::L17`) | 0.580 |
| grok-4 (`grok-4_3::L59`) | 0.300 |
| glm-4.6 (`glm-4.6_3::L7`) | 0.200 |
| grok-code-fast-1 (`grok-code-fast-1_1::L73`) | 0.180 |
| grok-4-fast (`grok-4-fast_2::L11`) | 0.180 |
| ...(descending)... | |
| gpt-5, gpt-5.1, gemini-*, claude-haiku-4.5 | 0.000 |

**Observation (not a claim):** Grok-family models (grok-4, grok-4-fast, grok-code-fast-1) cluster near the top of Toolathlon per-session precision. GPT-5 and Gemini families cluster near zero. Anthropic Claude-4.5-haiku scored 0. This is a **model-family effect on tool_result-repetition patterns**, not a Clew capability claim. Documented for future investigation; not a prereg prediction and not evidence of any waste-detection difference across model families (which would require separate controls).

### 9.9 v1 headline update recommendation

The public README currently cites LLM-judge precision as **52.20% on 5 CC sessions** (from Amendment v1, `README.md` §"LLM-as-Judge Semantic Duplicate (opt-in)"). Following this Amendment v2 measurement:

- v1's 52.20% number **stands** as a historical anchor (v1 GO judgment unchanged).
- README should be updated (separate docs PR) to add: **"On the expanded 28-CC + 20-Toolathlon sample (n=48), post-parser-fix precision is 31.7% (95% CI [23.1%, 41.0%]); on the CC subset alone, 48.5%; on Toolathlon, 10.4%."**
- The 52.20% headline is retained but qualified as v1's smaller-sample estimate.
- Follows anti-self-deception discipline: earlier numbers are not deleted, they are contextualized with the fuller data.

### 9.10 Diagnostic script output

- `field_test/diagnostics/llm_judge_v2_expansion.py` (uncommitted per `feedback_diagnostics_uncommitted`).
- `field_test/diagnostics/llm_judge_v2_expansion.RESULTS.json` (uncommitted; contains per-session rows including all match reasoning strings).
- `field_test/diagnostics/llm_judge_v2_stdout.log` (uncommitted; full stdout of the 12h run).

### 9.11 Follow-ups (not blocking; deferred)

1. **Recall / ground-truth benchmark.** This expansion measures precision only. A future v3 with hand-labeled ground truth (subset ~200 pairs) would give the actual F1.
2. **Model-family variance study.** §9.8 observation is worth a dedicated prereg with proper controls (task-mix, trace-length, and success-rate matching across model families).
3. **Toolathlon-specific rubric tuning.** The 10.4% precision on Toolathlon suggests the `toolu_*`-optimized clause under-serves `call_*` patterns. A rubric v3 could add pattern-specific detection. Requires new prereg.
4. **README pitch update PR.** Add the 31.7% / 48.5% / 10.4% numbers alongside v1's 52.20% per §9.9. Small docs PR.
