# Cost Table Exgentic Expansion — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8`, this document is
pushed and PR-opened before any pricing entry, alias, or diagnostic
code lands. Model set, sourcing method, verification format, and
alias ordering below are frozen; adjusting them after seeing results
is not allowed.

**Motivation.** The Corpus C (Exgentic) Week 2 diagnostic run
(2026-08-13, see field_test/diagnostics/exgentic_day2_stratified_10.py)
observed that the 5 canonical Exgentic model names resolve against
`src/clew/cost/pricing.py` as follows:

| Exgentic canonical | Current resolution | Warning? | Status |
|---|---|---|---|
| `DeepSeek-V3.2` | `deepseek-v3.2` exact | no | correct |
| `Kimi-K2.5` | Sonnet 4.5 default fallback | **yes** | wrong |
| `claude-opus-4-5` | `opus-4.7` via `claude-opus-4` alias | no | rate accidentally correct (both $5/$25), alias is not explicit |
| `gemini-3-pro-preview` | `gemini-3-pro-preview` exact | no | correct |
| `gpt-5.2-2025-12-11` | `gpt-5` via `gpt-5` alias | no | wrong (5.2 rate ≠ 5 rate per provider docs) |

Session-weighted impact on Corpus C (10,056 sessions, verified from
9-shard load): Kimi-K2.5 (2,285 · 22.7%) is silently rate-wrong via
Sonnet fallback; gpt-5.2 (2,124 · 21.1%) is silently rate-wrong via
alias fallback. Combined: **43.8% of Corpus C sessions carry incorrect
cost rates today.** Fixing these three cases (Kimi K2.5 entry, GPT-5.2
entry, explicit `claude-opus-4-5` alias) is the scope of this
expansion.

This prereg locks the plan to add those entries and aliases so
`WR_cost` on Corpus C is computed from provider-published rates
without changing the metric definition or the adapter contract.

## 0. Honesty preface (what this expansion is and is not)

**What this expansion does:**

- Adds two new pricing entries in `src/clew/cost/pricing.py` — one
  for `kimi-k2.5` (Moonshot) and one for `gpt-5.2` (OpenAI) — with
  provider-source URLs and verification date inline per the existing
  convention.
- Adds three alias mappings so Exgentic's canonical model strings
  (`Kimi-K2.5`, `claude-opus-4-5`, `gpt-5.2-2025-12-11`, all
  normalized lowercase) resolve to the correct entries. Alias
  ordering follows the existing `_ALIASES` longest-prefix rule.
- Adds unit tests in `tests/cost/test_pricing.py` covering the new
  keys, the new aliases, and the shadow ordering (`kimi-k2.5` before
  `kimi-k2-0905`; `gpt-5.2` before `gpt-5.1` / `gpt-5`;
  `claude-opus-4-5` before `claude-opus-4`).
- Re-runs the Day 2 stratified-10 diagnostic (same seed=42) to
  confirm all 10 sessions now resolve to their canonical Exgentic
  models with no fallback warnings.

**What this expansion does NOT do:**

- Does not change `docs/WASTE_RATE_METRIC_PREREG.md` §1 metric
  definitions, §3 detector set, or §4 aggregation rules.
- Does not add or modify a Corpus C adapter — the Exgentic ingest
  path is out of scope of this prereg. That belongs to a separate
  Corpus C adapter prereg (Week 2 Day 4).
- Does not modify Corpus A or B pricing entries. Corpus A
  `WR_cost = 0.2903` and Corpus B `WR_cost = 0.9189` stand.
- Does not commit to any specific `WR_cost` value on Corpus C.
  The Corpus C amendment prereg (separate) is where that
  prediction band lives.
- Does not add a `savings calculator` or `expected-cost` feature.
  Scope is the pricing table only.

## 1. Model set (frozen)

Three actions on the pricing table, one per row:

### 1.1 New entry — `kimi-k2.5` (Moonshot AI)

- Provider: Moonshot AI (MoonshotAI namespace on OpenRouter).
- Source: `https://openrouter.ai/moonshotai/kimi-k2.5` — OpenRouter's
  pricing page for the model. The Moonshot platform documentation
  (`platform.kimi.ai/docs/pricing/chat`) as of 2026-08-13 lists K3,
  K2.7 Code, K2.6, and Moonshot V1 but no longer K2.5 (superseded on
  the vendor platform). OpenRouter is used per §2.1 second-choice
  rule because Moonshot's own page no longer publishes K2.5. This
  fallback is recorded in §7.
- Verification date: 2026-08-13.
- Rate to enter: base_input $0.375/MTok, output $2.025/MTok. Cache
  tier is not published for K2.5; per §2.2 default, cache_read /
  cache_write columns equal base_input.

### 1.2 New entry — `gpt-5.2` (OpenAI)

- Provider: OpenAI.
- Source: `https://developers.openai.com/api/docs/pricing` —
  OpenAI's official developer pricing page.
- Verification date: 2026-08-13.
- Rate to enter: base_input $1.75/MTok, output $14.00/MTok,
  cache_read $0.175/MTok (explicitly published). Cache write tiers
  are not separately published on the OpenAI developer pricing page
  for GPT-5.2, so cache_write_5m / cache_write_1h default to
  base_input (§2.2 rule).

### 1.3 Alias-only — `claude-opus-4-5` → `opus-4.7`

- No new pricing entry. Anthropic's `claude.com/pricing` page (verified
  2026-08-13) lists Claude Opus 4.5 at input $5/MTok and output
  $25/MTok, exactly matching the existing `opus-4.7` Clew entry
  ($5/$25). The two model tiers share the same rate.
- The alias `("claude-opus-4-5", "opus-4.7")` is added strictly for
  explicitness: today `claude-opus-4-5` resolves to `opus-4.7` via
  the more-general `("claude-opus-4", "opus-4.7")` alias with no
  warning. An explicit alias makes the intent visible in the file
  and locks it against future accidental drift when `claude-opus-4`
  is repointed to a newer entry.

### 1.4 Alias ordering (frozen)

Per the existing longest-prefix rule (`_ALIASES` is an ordered
tuple, first match wins after normalization), the three new aliases
insert in this order (relative to existing entries):

- `("kimi-k2.5", "kimi-k2.5")` — **before** the existing
  `("kimi-k2-0905", "kimi-k2-0905")` (`kimi-k2.5` is longer and
  more specific).
- `("gpt-5.2", "gpt-5.2")` — **before** `("gpt-5.1", "gpt-5")`,
  `("gpt-5-mini", "gpt-5-mini")`, `("gpt-5-high", "gpt-5")`, and
  `("gpt-5", "gpt-5")`. The Exgentic canonical `gpt-5.2-2025-12-11`
  resolves via startswith on the `gpt-5.2` prefix.
- `("claude-opus-4-5", "opus-4.7")` — **before** the existing
  `("claude-opus-4", "opus-4.7")`.

### 1.5 Not in scope

- `DeepSeek-V3.2` — already resolves correctly to the existing
  `deepseek-v3.2` entry ($0.28 / $0.42). No change.
- `gemini-3-pro-preview` — already resolves correctly to the existing
  exact-match entry ($2.00 / $12.00). No change.
- Future Exgentic v3 or Kimi K3 models — not in scope. A follow-up
  chain if they land on the benchmark.

## 2. Sourcing rules (frozen)

### 2.1 Source URL priority

1. **First choice:** the provider's own public pricing page.
2. **Second choice** (only when the provider does not publish, or has
   deprecated the specific version from its page): a canonical
   aggregator provider-facing enough to mirror the rate (OpenRouter
   for MoonshotAI's Kimi K2.5).
3. **Prohibited:** blog posts, secondary market analyses, community
   wikis, unofficial pricing calculator sites.

### 2.2 Fields to record per new entry

- `base_input_per_mtok` (uncached input, $/MTok).
- `cache_read_per_mtok` (cache hit; equal to `base_input_per_mtok`
  when the provider does not price this separately).
- `cache_write_5m_per_mtok` (5-minute TTL write; default equals
  `base_input_per_mtok` when not separately priced).
- `cache_write_1h_per_mtok` (1-hour TTL write; default equals
  `base_input_per_mtok` when not separately priced).
- `output_per_mtok`.

### 2.3 Verification metadata (in-file comment)

Each new entry carries the block-comment convention already used for
the Toolathlon Expansion entries:

```
# Source: https://... (verified 2026-08-13)
"kimi-k2.5": ModelPricing(...),
```

The `verified` date is the day this prereg's fetches were performed
(2026-08-13). No entry carries only a URL without a date.

## 3. What is not changed

- `docs/WASTE_RATE_METRIC_PREREG.md` — unchanged.
- `docs/WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md` —
  unchanged. Corpus B `union_wr_cost = 0.9189` stands.
- `docs/COST_TABLE_TOOLATHLON_EXPANSION_PREREG.md` — unchanged;
  no Toolathlon entry is modified.
- All 25 existing pricing entries (Anthropic 4 + OpenAI GPT-4o
  family 2 + Google Gemini 1.5 family 2 + Toolathlon Expansion 15
  + Exgentic-share exact matches 2) — unchanged. Their source URLs
  and verification dates stand.
- `src/clew/cost/pricing.py` `get_pricing()` resolution algorithm —
  unchanged. Only PRICING dict entries and `_ALIASES` tuple are
  modified.
- Detector code — unchanged.
- Ingest code — unchanged.
- Corpus A / Corpus B / prior Corpus C diagnostic numbers computed
  before this expansion — retained in history; the Day 2 diagnostic
  §4 will be re-run and its new output logged, but the prior
  observation stays in the record as the pre-expansion snapshot.

## 4. Predictions (pre-committed)

**P1 (coverage).** After expansion, 100% of the 10,056 Corpus C
sessions will resolve to their canonical Exgentic model with no
`pricing: unknown model` fallback warning. Rationale: 3 sessions'
worth of models (Kimi 22.7%, Opus 4.5 19.1%, GPT-5.2 21.1%) plus the
2 already-correct (DeepSeek 22.9%, Gemini 14.2%) equals 100% by
construction; each of the 5 canonical strings has a defined
resolution after the alias insertions.

**P2 (Day 2 re-run · rate correctness).** Re-running the Day 2
stratified-10 diagnostic (same seed=42) will produce no
`unknown model` warnings and all 10 sessions will report an
explicit canonical model key in `input_cost_rate` provenance.

**P3 (aggregate WR_cost sign of change).** Corpus C `union_wr_cost`
after expansion will differ from the pre-expansion (rate-wrong)
diagnostic value on the same 10-session sample; specifically, the
median per-session `wr_cost` will *decrease* relative to the
pre-expansion diagnostic, because Kimi K2.5 ($0.375/$2.025) is
substantially cheaper on input than the Sonnet 4.5 fallback
($3.00/$15.00), so its share of the resend cost — and therefore
the whole session's `wr_cost` — shifts. Direction is committed;
magnitude is not (band left open, per anti-hype: don't box in a
number we cannot forecast).

**P4 (WR_char invariance).** `wr_char` on the same 10-session Day 2
sample will be **exactly** the same after expansion (byte-level
metric, invariant to pricing changes). Any change here is a
regression, not an expected outcome, and would trigger §7.

**What would violate expectations (would trigger honest §7 note):**

- Any P1-P4 miss.
- A new pricing entry landing without its inline `Source: … (verified
  2026-08-13)` comment.
- Test suite breakage of any pre-existing pricing case.

Meeting all predictions is not evidence of correctness — it is
consistent-with-expectation. Missing them triggers a diagnostic
note but does not invalidate the metric.

## 5. Method

1. Add 2 new pricing entries in `src/clew/cost/pricing.py` per §1
   and §2. Each entry carries the §2.3 verification metadata inline.
2. Add 3 alias mappings in `_ALIASES` per §1.4 ordering.
3. Add unit tests in `tests/cost/test_pricing.py` covering:
   (a) each new key resolves to a `ModelPricing` object,
   (b) each new alias (including canonical `gpt-5.2-2025-12-11` via
       prefix match) resolves,
   (c) `("kimi-k2.5", ...)` inserts before `("kimi-k2-0905", ...)` —
       Kimi-K2.5 does not fall through to K2-0905,
   (d) `("gpt-5.2", ...)` inserts before all `("gpt-5*", ...)` — GPT-5.2
       does not fall through to GPT-5.1 or GPT-5,
   (e) `("claude-opus-4-5", ...)` inserts before `("claude-opus-4", ...)`,
   (f) all pre-existing pricing cases (Toolathlon Expansion 22, Corpus
       A / B / CC baselines) still pass unchanged.
4. Re-run `field_test/diagnostics/exgentic_day2_stratified_10.py`
   with same seed=42 and record: (i) count of `unknown model` warnings
   (target: 0), (ii) 10-row canonical-model provenance table,
   (iii) new median wr_cost, (iv) wr_char invariance check.
5. Append results as §8 of this document.

## 6. Explicit non-commitments

- Not committing to any specific `base_input_per_mtok` or output
  value at merge time. Values were fetched 2026-08-13; if a provider
  reprices between merge and post-scan verification, the entry
  reflects the 2026-08-13 fetch and a follow-up chain updates it.
- Not committing that the source URLs will remain stable — providers
  can and do restructure. The `verified` date is the honest anchor.
- Not committing that Kimi K2.5 cache tiers reflect Moonshot's true
  billing. Their platform no longer lists K2.5; OpenRouter's rate is
  cache-tier-flat, so Clew's entry falls back to base_input for all
  cache columns per §2.2. This choice is documented; a future
  Moonshot re-publication would trigger a follow-up chain.
- Not committing to Corpus C `union_wr_cost` numeric value.
  The Corpus C amendment prereg (separate, Week 2 Day 4) owns that
  prediction.

## 7. Notes on scope choices (open for §8 amendment)

- Kimi-K2.5 pricing sourced from OpenRouter, not Moonshot. Moonshot's
  own platform docs (`platform.kimi.ai/docs/pricing/chat`) list K3
  through K2.6 and V1 as of 2026-08-13; K2.5 has been superseded on
  the vendor page. Per §2.1 second-choice, OpenRouter is a
  provider-facing mirror. This is the same pattern the Toolathlon
  Expansion prereg §7 documented for MiniMax M2 (aggregator source
  when the provider's page did not list the exact SKU).
- Claude Opus 4.5 receives no new pricing entry because the rate
  ($5/$25) matches the existing `opus-4.7` entry exactly. Merging
  Opus 4.5 rate into a new entry with the same numbers would create
  a maintenance duplicate. The alias makes the intent explicit
  without duplicating the rate — this is a deliberate choice
  documented here so a future reader does not "restore" the missing
  entry believing it was overlooked.

## 8. Commit chain (per `feedback_rule_8`)

Three commits, no squash/rebase:

1. `docs: Cost Table Exgentic Expansion prereg` — this file only.
   PR opened for approval.
2. **After approval:** `feat(cost): Kimi-K2.5 + GPT-5.2 pricing entries + Exgentic aliases`
   — `src/clew/cost/pricing.py` + `tests/cost/test_pricing.py`.
3. `docs(cost_exgentic): append post-expansion Day 2 re-run` —
   §8 of this file with the 10-row re-run table and the P1-P4
   verdict lines.

## 9. Results (post-expansion Day 2 re-run · 2026-08-13)

**Re-run command:** `python -m field_test.diagnostics.exgentic_day2_stratified_10`
(same seed=42, same 10-session pick as Day 2 pre-expansion).

**Diagnostic script:** `field_test/diagnostics/exgentic_day2_stratified_10.py`
(uncommitted per `feedback_diagnostics_uncommitted`; augmented to record
per-session `canonical_pricing_key`, `input_rate_per_mtok`,
`total_llm_input_cost_usd`, and `resent_cost_usd` for provenance).

### 9.1 Per-session resolution (all 10 sessions)

| # | Model → Canonical | Rate $/MTok | wr_char | wr_cost | total_cost $ |
|---|---|---:|---:|---:|---:|
| 0 | `gpt-5.2-2025-12-11` → `gpt-5.2` | 1.750 | 0.8249 | 0.8249 | 0.1210 |
| 1 | `gpt-5.2-2025-12-11` → `gpt-5.2` | 1.750 | 0.9080 | 0.9080 | 0.2385 |
| 2 | `DeepSeek-V3.2` → `deepseek-v3.2` | 0.280 | 0.8810 | 0.8810 | 0.7848 |
| 3 | `Kimi-K2.5` → `kimi-k2.5` | 0.375 | 0.6601 | 0.6601 | 0.2276 |
| 4 | `DeepSeek-V3.2` → `deepseek-v3.2` | 0.280 | 0.9325 | 0.9325 | 0.2887 |
| 5 | `gpt-5.2-2025-12-11` → `gpt-5.2` | 1.750 | 0.8105 | 0.8105 | 0.2194 |
| 6 | `DeepSeek-V3.2` → `deepseek-v3.2` | 0.280 | 0.9056 | 0.9056 | 0.2198 |
| 7 | `DeepSeek-V3.2` → `deepseek-v3.2` | 0.280 | 0.8579 | 0.8579 | 0.0206 |
| 8 | `Kimi-K2.5` → `kimi-k2.5` | 0.375 | 0.9564 | 0.9564 | 1.9778 |
| 9 | `DeepSeek-V3.2` → `deepseek-v3.2` | 0.280 | 0.9589 | 0.9589 | 0.1719 |

**Every session resolves to its canonical Exgentic model with zero
`unknown model` UserWarnings.** No `sonnet-4.5` fallback path taken.

### 9.2 Aggregate

- Token invariant preserved: 10/10.
- `wr_char`: min 0.6601 · p10 0.8105 · median 0.9056 · p90 0.9589 · max 0.9589
- `wr_cost`: min 0.6601 · p10 0.8105 · median 0.9056 · p90 0.9589 · max 0.9589
- `cost_accuracy_flag = "estimated"` for 10/10 (per Corpus B parity;
  Exgentic dataset has no `cache_read` / `cache_write` tier data, so
  the detector cannot mark cost as "accurate" — this is orthogonal to
  the pricing-table gap and remains unchanged by this expansion).

### 9.3 Pre-expansion vs post-expansion comparison

Same 10 sessions, same converter, same detector, seed=42:

| # | Model | Pre-expansion wr_char | Post-expansion wr_char | Pre wr_cost | Post wr_cost |
|---|---|---:|---:|---:|---:|
| 0-9 | (5 DeepSeek + 3 gpt-5.2 + 2 Kimi) | 0.6601-0.9589 | **identical** | 0.6601-0.9589 | **identical** |

Every `wr_char` and every per-session `wr_cost` matches to 4 decimal
places. Zero drift. `resent_cost_usd` absolute values did shift (Kimi
sessions dropped ~8× on absolute cost as expected from the Sonnet 4.5
$3.00/MTok → Kimi K2.5 $0.375/MTok rate change), but the per-session
ratio is unchanged. See §9.5 for why this is not a bug.

### 9.4 Prediction verdicts

| ID | Prediction | Observed | Verdict |
|---|---|---|---|
| **P1** | 100% Corpus C sessions resolve without unknown-model warning | 10/10 on Day 2 sample (109/109 pricing test cases pass) | ✅ **PASS** |
| **P2** | Day 2 re-run has zero fallback warnings | 0 warnings across all 10 sessions | ✅ **PASS** |
| **P3** | Median per-session `wr_cost` on the Day 2 sample *decreases* relative to pre-expansion | Median unchanged (0.9056 → 0.9056); all 10 per-session `wr_cost` values identical to pre-expansion to 4 decimal places | ❌ **MISS** (see §9.5) |
| **P4** | `wr_char` invariant to pricing change (byte metric) | All 10 per-session `wr_char` values identical to pre-expansion | ✅ **PASS** |

**3/4 pass.** No prediction band was adjusted post-hoc.

### 9.5 P3 miss — root cause analysis

**The prediction was wrong in principle, not in magnitude.**

`wr_cost` on the uncached-only path decomposes to:
`wr_cost = resent_cost / total_llm_input_cost`
       `= (resent_input_tokens × input_rate) / (total_input_tokens × input_rate)`
       `= resent_input_tokens / total_input_tokens`
       `= wr_char`.

The `input_rate` factor **cancels** between numerator and denominator
whenever the same rate applies to every LLM call in the session. Since
each Exgentic session uses a single model (verified from the `models`
top-level column, always a single-element list on all 10 sessions),
every rate change on that model shifts `resent_cost` and
`total_llm_input_cost` by the same multiplier, leaving the ratio
unchanged.

The rate change **did land** (§9.3 absolute `resent_cost_usd` for the
2 Kimi sessions dropped by exactly the factor `0.375 / 3.00 = 0.125`,
matching the Sonnet 4.5 → Kimi K2.5 rate ratio), it just does not
propagate to the per-session `wr_cost` ratio.

**Where P3 would have been correct:** cross-session aggregates that
weight cost across a *mix* of models (e.g. a Corpus C `union_wr_cost`
computed as `sum(resent_cost_i) / sum(total_cost_i)` across all
10,057 sessions). There, a Kimi rate correction re-weights that
model's contribution to the numerator/denominator separately from
DeepSeek / gpt-5.2 / Opus / Gemini contributions, and the aggregate
`wr_cost` *does* shift. The Day 2 stratified-10 sample was too small
and per-session displayed for that effect to surface. P3 as written
predicted a per-session-median shift that is structurally impossible
on the uncached path.

**Documented lesson (not a metric change):** in the Corpus C
amendment prereg (Week 2 Day 4, separate PR), `union_wr_cost`
prediction bands must be framed as cross-session aggregates, not as
per-session medians. The per-session `wr_cost` is byte-equivalent
under the uncached-only path shared across Corpus B and Corpus C.

### 9.6 What is verified by this re-run

- The 2 new PRICING entries (`kimi-k2.5`, `gpt-5.2`) and 3 aliases
  land in `get_pricing()` per §5.1-5.2.
- All 5 Exgentic canonical strings — including the 3 with silent-wrong
  behavior before this expansion — now route to their intended canonical
  keys without warnings.
- Absolute `total_llm_input_cost_usd` on Kimi K2.5 sessions correctly
  reflects the new rate (~8× drop from the Sonnet 4.5 fallback).
- `wr_char` invariance to pricing is preserved (byte metric).
- Adapter converter (`exgentic_convert_and_ingest.py`) and detector
  code paths are untouched, per §3.

### 9.7 What is NOT verified by this re-run

- Full-corpus (10,056 sessions) resolution — inferred from test suite
  coverage (109 pricing-key permutations, no fallback path exercised),
  not empirically re-run. The Corpus C amendment prereg's Day 3 full
  scan will produce the direct empirical proof point.
- Cross-session `union_wr_cost` — out of scope for this pricing prereg
  (Corpus C amendment prereg owns that number).
- Kimi K2.5 cache tier — Moonshot no longer publishes cache-tier split
  for this model on their platform; the base-fallback used here is
  documented in §1.1 and §6 explicit non-commitments.
