# Cost Table Toolathlon Expansion — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8`, this document is
pushed and PR-opened before any pricing entry, alias, or diagnostic
code lands. Model set, sourcing method, verification format, and
re-scan predictions below are frozen; adjusting them after seeing
results is not allowed.

**Motivation.** `docs/WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md`
§10.2 documented that 98.2% of Toolathlon trajectories (6,538 / 6,659
included) are excluded from `WR_cost` because their `modelname_run`
values (e.g. `claude-4-sonnet-0514`, `gpt-5.1`, `qwen-3-coder`) are
absent from `src/clew/cost/pricing.py`. The metric spec's §1.2
`WR_cost = None` fallback is honored, but the resulting Corpus B
`union_wr_cost` is uninformative (`None`). This prereg locks the plan
to extend the pricing table so `WR_cost` becomes computable on
Toolathlon without changing the metric definition itself.

## 0. Honesty preface (what this expansion is and is not)

**What this expansion does:**

- Adds pricing entries in `src/clew/cost/pricing.py` for the 22
  distinct model families that appear in the frozen Toolathlon
  manifest (§2 of the amendment).
- For each entry, pins a **source URL** and an **ISO-8601 verification
  date** in an accompanying comment or docstring, following the
  convention already used for the existing 8 entries.
- Adds alias mappings so that the exact `modelname_run` strings
  seen in Toolathlon (`claude-4-sonnet-0514_1`, `gpt-5.1_3`,
  `qwen-3-coder_2`, etc. — noting the `_1`/`_2`/`_3` run-index
  suffix that Toolathlon appends) resolve to canonical entries.
- Re-runs the Toolathlon `waste_rate_metric_toolathlon_v2.py`
  diagnostic against the same frozen manifest to produce a new
  `union_wr_cost` figure.

**What this expansion does NOT do:**

- Does not change `docs/WASTE_RATE_METRIC_PREREG.md` §1 metric
  definitions, §3 detector set, or §4 aggregation rules.
- Does not change the amendment prereg
  (`WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md`) §1
  reconstruction rule or §5 prediction bands. Those predictions
  (P1, P2, P4) already passed; this expansion only unblocks P3-adjacent
  reporting on Corpus B.
- Does not modify Corpus A pricing entries. Corpus A `WR_cost = 0.2903`
  from `WASTE_RATE_METRIC_PREREG.md` §13.1 stands.
- Does not add a "savings calculator" feature. That is scoped to a
  separate follow-up chain if warranted after this expansion lands.
- Does not commit to any specific new `union_wr_cost` value on
  Toolathlon. The re-run is the question, not the answer.

## 1. Model set (frozen)

The 22 model families appearing in the Toolathlon manifest, extracted
from the 66 JSONL filenames by stripping the `_1`/`_2`/`_3` run-index
suffix:

**Anthropic (4):** `claude-4-sonnet-0514`, `claude-4.5-haiku-1001`,
`claude-4.5-opus`, `claude-4.5-sonnet-0929`.

**OpenAI (7):** `gpt-5`, `gpt-5-high`, `gpt-5-mini`, `gpt-5.1`,
`o3`, `o4-mini`, plus `grok-code-fast-1` (misfiled — see §1.3 below).

Correction: `grok-code-fast-1` is xAI. Corrected count: **OpenAI 6**.

**Google (3):** `gemini-2.5-flash`, `gemini-2.5-pro`,
`gemini-3-pro-preview`.

**xAI (3):** `grok-4`, `grok-4-fast`, `grok-code-fast-1`.

**DeepSeek (2):** `deepseek-3.2-thinking`, `deepseek-v3.2-exp`.

**Others (4):** `glm-4.6` (Zhipu), `kimi-k2-0905` (Moonshot),
`minimax-m2` (MiniMax), `qwen-3-coder` (Alibaba).

**Total: 22 model families.**

### 1.1 Not in scope

- **Provider-alias variants** — e.g. `gpt-5-high` vs `gpt-5` may share
  the same base rate on OpenAI's page; if so, both entries point at
  the same `ModelPricing` object. If OpenAI publishes distinct rates,
  both entries carry the distinct rates separately.
- **Feature-tier variants** (thinking mode, reasoning mode) are
  priced by their published effective rate on the provider's own
  page. `deepseek-3.2-thinking` is priced separately from `deepseek-v3.2-exp`
  only if the provider explicitly differentiates.
- **Preview / experimental models** (`gemini-3-pro-preview`,
  `deepseek-v3.2-exp`) — priced by their preview-window rate as of
  the verification date; a footnote flags the "preview pricing may
  change" caveat.

### 1.2 Run-index suffix handling

Toolathlon files are named `<model>_<run>.jsonl` where `<run> ∈ {1,2,3}`.
The `modelname_run` field inside each trajectory carries the same
`<model>_<run>` string (e.g. `claude-4-sonnet-0514_1`, verified 2026-08-11
via the timing probe).

The pricing lookup must strip the `_1`/`_2`/`_3` suffix before matching.
This is implemented in the aliases table (not a change to the
lookup algorithm — `_ALIASES` already handles substring rewrites).

## 2. Sourcing rules (frozen)

For each of the 22 model families:

### 2.1 Source URL priority

1. **First choice:** the provider's own public pricing page (Anthropic,
   OpenAI, Google AI Studio / Vertex, xAI, DeepSeek, Zhipu, Moonshot,
   MiniMax, Alibaba Cloud).
2. **Second choice** (only when the provider does not publish a
   pricing page): a canonical aggregator that the provider itself
   links (e.g. Azure catalog for a Microsoft-hosted variant, OpenRouter
   for community-published rates). The aggregator source must be
   linked from the provider's own docs, or the entry falls to §2.4.
3. **Prohibited:** blog posts, secondary market analyses, or
   community wikis.

### 2.2 Fields to record per entry

Following the existing convention in `src/clew/cost/pricing.py`:

- `base_input_per_mtok` (uncached input, $/MTok)
- `cache_read_per_mtok` (cache hit; if provider does not price this
  separately, equals `base_input_per_mtok`)
- `cache_write_5m_per_mtok` (5-minute TTL write; if not priced
  separately, equals `base_input_per_mtok`)
- `cache_write_1h_per_mtok` (1-hour TTL write; if not priced
  separately, equals `base_input_per_mtok`)
- `output_per_mtok` (output, $/MTok)

### 2.3 Verification metadata (in-file comment or docstring)

Each entry carries a companion comment or docstring line:

```
# claude-4.5-sonnet-0929: source https://... verified 2026-08-11
```

The `verified` date is the day the source URL was fetched. No entry
carries only a URL without a date; no entry carries only a date
without a URL.

### 2.4 Unpriced fallback

If a model family has no public pricing page and no provider-linked
aggregator, the entry is **omitted** from the pricing table and the
alias table. Toolathlon trajectories using that model continue to
fall into the `WR_cost = None` exclusion path per parent §1.2. A
one-line note in this prereg's §7 records the omission with the
model name.

## 3. What is not changed

- `docs/WASTE_RATE_METRIC_PREREG.md` §1 metric definitions —
  unchanged.
- `docs/WASTE_RATE_TOOLATHLON_ADAPTER_AMENDMENT_PREREG.md` §1
  reconstruction rule — unchanged.
- Existing 8 pricing entries (Sonnet 4.5 / 4.6, Opus 4.7, Haiku 4.5,
  GPT-4o / GPT-4o mini, Gemini 1.5 Pro / Flash) — unchanged; their
  source URLs and verification dates stand.
- `src/clew/ingest/toolathlon.py` — unchanged.
- Detector code — unchanged.
- Corpus A `WR_cost = 0.2903` — unchanged.

## 4. Predictions (pre-committed)

**P1.** After expansion, ≥ 90% of Toolathlon trajectories will have a
priced model (i.e. `n_priced / n_included ≥ 0.90`). Rationale: all 22
listed model families are commercially deployed with public pricing
except in cases §2.4 covers.

**P2.** Corpus B `union_wr_cost` after expansion will fall in
`[0.05, 0.60]`. Rationale: WR_char is 0.9342, and cache-tier
distribution on Toolathlon is unknown but expected to fall between
CC-like patterns (heavy cache use → low WR_cost near 0.29) and
uncached patterns (WR_cost approaches WR_char).

**P3.** Per-detector shares under the new pricing will keep
`context_resend` as the dominant contributor (≥ 95% of
`union_wr_cost` numerator). Rationale: the same structural
argument in amendment §10.6 applies to cost as to bytes.

**What would violate expectations (would trigger honest §7 note):**

- Any P1-P3 miss.
- New cost values that swing `union_wr_char` (a byte-level metric,
  should be invariant to pricing changes).

Meeting all predictions is not evidence of correctness — it is
consistent-with-expectation. Missing them triggers a diagnostic
note but does not invalidate the metric.

## 5. Method

1. Add pricing entries in `src/clew/cost/pricing.py` per §2, one per
   §1 model family. Each entry carries the §2.3 verification
   metadata inline.
2. Add alias mappings so `modelname_run` strings (with `_1`/`_2`/`_3`
   suffix) resolve. Existing `_ALIASES` structure covers this.
3. Add unit tests in `tests/cost/test_pricing.py` covering:
   (a) each new key resolves to a `ModelPricing` object,
   (b) each new alias (including with `_1`/`_2`/`_3` suffix) resolves,
   (c) cache-tier column defaults (equal to `base_input` when
   provider does not distinguish),
   (d) no existing entry is disturbed.
4. Re-run `field_test/diagnostics/waste_rate_metric_toolathlon_v2.py`
   against the same frozen manifest.
5. Append results as §7 of this document.

## 6. Explicit non-commitments

- Not committing to any specific `base_input_per_mtok` value for any
  model. The values arrive when §5.1 executes.
- Not committing that the source URL will remain stable — providers
  can and do restructure their pricing pages. The `verified` date is
  the honest anchor.
- Not committing to a v2 that tracks pricing changes over time.
  This is a one-shot expansion; future re-verification is a
  separate chain.
- Not committing that all 22 model families will land. §2.4 explicitly
  allows omissions with recorded rationale.

## 7. Commit chain (per `feedback_rule_8`)

Three commits, no squash/rebase:

1. `docs: Cost Table Toolathlon Expansion prereg` — this file only.
   PR opened for approval.
2. **After approval:** `feat(cost): Toolathlon model pricing entries + aliases`
   — `src/clew/cost/pricing.py` + `tests/cost/test_pricing.py`.
3. `docs(waste_rate): append Toolathlon re-scan with expanded pricing`
   — new §11 in the amendment prereg documenting the new Corpus B
   `union_wr_cost`, or a new §7 in this file — choice locked at
   commit-3 time based on where the reader will look first.

## 8. Results (to be appended after commits 2 and 3 land)

_To be appended._
