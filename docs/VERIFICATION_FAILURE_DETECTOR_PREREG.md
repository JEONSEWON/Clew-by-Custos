# Verification Failure Detector (Pre-registration)

**Status.** New detector family, the second step of the coverage plan whose
first step was latency. Per `feedback_rule_8` this document is pushed and
PR-opened **before any code lands**. The rule in §3, the predictions in §6 and
the rejection conditions in §7 are frozen positions. Adjusting them after seeing
results is not allowed.

Two things were settled by dry-run before this document was frozen, and both
narrowed it: one rule was cut for absence of data, and the surviving rule was
tightened twice. §2 and §8 record what the dry-run rejected, because a
pre-registration that hides its own discarded drafts is worth less.

---

## 0. Why this, and why now

Everything measured today answers one question: *was the same work done twice?*
`repeat`, `context_resend`, `redundant_read` and `duplicate_creation` are all
forms of it. That is one failure mode out of fourteen in the public taxonomy,
and this product's direction is failure and cost as one thing rather than two
lists.

Latency came first, because a failure notice that arrives late is about
something nobody can act on. That step is at a predicted 50.48 minutes awaiting
a live apply ([`ALERT_DELIVERY_CADENCE_RESULTS.md`](ALERT_DELIVERY_CADENCE_RESULTS.md)).
This is the second step.

## 1. What the taxonomy says, and what can actually be cited

From *Why Do Multi-Agent LLM Systems Fail?* (arXiv 2503.13657), category 3,
**"Task Verification and Termination"**: *"Failures stemming from premature
termination, inadequate verification mechanisms, and insufficient validation of
outcomes."* Verbatim from the v1 HTML:

> **FM-3.2: No or Incomplete Verification** — "(partial) omission of proper
> checking or confirmation of task outcomes or system outputs, potentially
> allowing errors or inconsistencies to propagate undetected"

> **FM-3.3: Incorrect Verification** — "Failure to adequately validate or
> cross-check crucial information or decisions during the iterations,
> potentially leading to errors or vulnerabilities"

⚠️ **A citation correction belongs here, and it is not small.** Internal
planning has been quoting per-mode frequencies (FM-3.2 at 8.2%, FM-3.3 at 9.1%,
FM-1.3 at 15.7%) and building a coverage arithmetic on them. **Those numbers are
not in the paper's text.** The v1 HTML gives category-level structure and states
only that "percentages represent how frequently each failure mode and category
appeared in our analysis of 151 traces"; the per-mode numbers exist inside
Figure 2 as an image. They may have been read correctly from that figure, but
they are not text-citable, and any external claim resting on them needs the
figure named as the source. **Nothing in this document rests on them.**

The taxonomy is named **MASFT** in the v1 HTML; internal notes use MAST. Same
taxonomy.

## 2. What the dry-run settled

Measured on 85 real Claude Code sessions, 14,211 tool calls, on the author's
machine (`field_test/diagnostics/_verification_signal_probe.py`).

**The failure signal is structural, not inferred.** Anthropic's `tool_result`
carries an `is_error` boolean and the body carries the command's own words
(`"Exit code 1\n..."`). 384 results carry `is_error: true`, across 63 of 85
sessions.

★ **The pipeline already reads that field and throws it away.** The §29.2
tool-error gate excludes `is_error` spans as infrastructure noise
(`src/clew/ingest/claude_code.py:469`, `src/clew/cost/amplification.py:112`).
That was right for cost: an error response is not evidence of waste, and
counting it inflated amplification. §4 keeps that gate exactly as it is.

### 2.1 FM-3.3 is cut: the corpus has six of the events

An "ignored verification failure" needs a failed verification to ignore. Of the
384 error results, **6 came from a verification command.** Under the definition
that actually matches FM-3.3 (a failed check with no subsequent edit and no
re-run), the corpus yields **0 candidates**; allowing a re-run yields 2.

**FM-3.3 is therefore BLOCKED, not killed** — the same distinction
`project_pingpong_blocked` draws. The rule may be right; there is nothing here
to test it against. It needs a corpus where agents run tests and the tests fail.

A first draft of that rule is recorded because it failed loudly and the failure
is the useful part: *an `is_error` result with no later call of the same tool on
the same normalised input* produced **370 candidates from 384 errors, 96.4%**.
Agents rarely re-run a byte-identical command, so "not retried identically"
collapses into "an error happened". The frozen P2 of the draft said "more than
300 means it is counting errors, not ignored ones", and it counted errors. The
dry-run rejected the rule before the document was frozen, which is what
`feedback_prereg_dryrun_reproduce` is for.

### 2.2 FM-3.2 survives, after two narrowings

| definition | candidates |
|---|---|
| any edit, no verification command | 17 of 60 edit-bearing sessions |
| ...restricted to **checkable** file edits | **10 of 50** (20.0%) |

The first is too loose by inspection: **8 of those 17 sessions edited only
`.md`.** A markdown edit has nothing for `pytest` to catch, so calling it an
unverified change is a false positive by construction rather than by judgement.

The narrowing is not a hand-picked extension list. A file counts as
**checkable** only if the frozen verification list in §3 contains a tool that
checks that language. The two lists are coupled by construction, so neither can
be widened later to move a number without widening the other.

## 3. The rule

### `unverified_edit` (FM-3.2)

**A session that changed checkable code and never ran a check.**

- **Trigger:** the session contains at least one *checkable edit* and **zero**
  verification spans.
- **Checkable edit:** an `Edit` / `Write` / `NotebookEdit` span whose target path
  ends in one of `.py .ts .tsx .js .jsx .mjs .go .rs`.
- **Verification span:** a `Bash` / `PowerShell` span whose command matches one
  of `pytest`, `python -m pytest`, `npm test`, `npm run test`, `npm run build`,
  `yarn test`, `yarn build`, `tsc`, `mypy`, `ruff`, `eslint`, `go test`,
  `cargo test`, `cargo build`, `make test`, `make check`, `vitest`, `jest`.
- **Coupling rule, frozen:** the two lists above move together or not at all.
  An extension may be added only alongside a tool in the verification list that
  checks it, and a tool may be removed only alongside the extensions it was the
  only checker for.
- Reported **per session**, not per span. There is no single edit to point at;
  the claim is about the session's shape.
- Reported in its own fields. It contributes nothing to `waste_span_count`,
  `waste_cost` or either waste rate (§4).

**Known weakness, stated before measuring:** a project whose check is
`./scripts/check` or `tox` or a CI-only step looks unverified when it is not.
Every such miss is a false positive for this rule, which is why §5 gates on
precision rather than recall.

### `ignored_failure` (FM-3.3)

**Not built.** §2.1.

## 4. What is explicitly NOT changed

- **The §29.2 tool-error gate stays.** Cost, waste rate and amplification keep
  excluding `is_error` spans. This rule does not read that field at all.
- **φ, N, the embedding model, and every existing threshold.** This rule is
  structural and runs no embedding.
- **The existing detectors.** Nothing is re-classified, nothing is re-scored.
- **`error_repeat`** keeps its meaning. It is a cascade pattern label on repeat
  candidates (`src/clew/report/markdown.py:205`), **not a detector** — the same
  shape as `requery_known` in CLAUDE.md §1. This rule is not an extension of it
  and must not be described as one.
- **The waste-field boundary.** `wasteful == (waste_span_count > 0)` stays an
  identity (`reference_waste_field_scope_boundary`).
- **Alert rules.** Neither rule A nor rule B learns about this. Whether a
  verification failure should page anyone is a separate question with its own
  pre-registration.
- **`preprocess_trace` is not run on Claude Code traces**, here or anywhere.

## 5. The rejection this must survive

**Precision on hand labels, and the corpus that can carry the claim.**

Two precedents set the bar and both are kills:

- the re-read detector reached precision 0.000 to 0.033 and was killed
  (`docs/REREAD_DETECTOR_PREREG.md` §11)
- args-only real-time blocking reached 0.633 against a pre-registered 0.70 and
  was killed (`reference_args_only_kill`)

**The gate is 0.70, hand-labelled.** Same number as the args-only gate, chosen
before looking, for the same reason.

★ **The author's 85 sessions cannot carry that claim, and this document says so
rather than pretending otherwise.** The rule produces 10 candidates there. At
n=10 a 0.70 point estimate is 7 of 10, whose Clopper-Pearson 95% two-sided lower
bound is about 0.35. That is not a precision measurement; it is a look.

So the labelling corpus is **Corpus D**
(`choucsan/mimo-claude-code-traces-1k`, rev `39cc3fc3`, MIT, 1,017 sessions),
already frozen and already read by the Claude Code adapter with zero
modifications
([`WASTE_RATE_CORPUS_D_MIMO_CC_RESULTS.md`](WASTE_RATE_CORPUS_D_MIMO_CC_RESULTS.md)).
The author's 85 sessions are the development set that produced §2 and are **not**
labelled or reported as evidence.

Labelling protocol, fixed here:

1. **Random sample, not top-N.** 40 candidates drawn uniformly from Corpus D's
   candidates. Drawing the sessions with the most tool calls is the length
   confound that produced AUC 0.455 once already (`feedback_length_confound`).
2. A candidate is labelled **true** only if the trace shows a change to
   checkable code and no check of any kind, including checks this rule's pattern
   list would miss. A session that verified by some route the list does not know
   is labelled **false**. That asymmetry is deliberate: it labels against us.
3. Labels written and committed **before** precision is computed.
4. **Clopper-Pearson 95% two-sided** reported alongside the point estimate
   (`reference_clopper_pearson_convention`). The gate is on the point estimate;
   the interval is reported, never used to rescue a miss.

## 6. Predictions (written before any code)

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | on the author's 85 sessions the implementation flags **exactly 10**, the §2.2 count | any other number: the detector and the probe disagree about the same rule |
| **P2** | Corpus D yields **at least 40** candidates, enough to sample | fewer than 40, and the corpus cannot carry the claim either |
| **P3** | precision ≥ **0.70** on 40 random Corpus D candidates | below 0.70 |
| **P4** | Corpus D candidate rate is within **5 to 40%** of its sessions that edit checkable files | outside that band: the rule behaves differently on traces we did not generate, and the 20.0% here was a property of one author |
| **P5** | every cost and waste-rate figure on the 85 sessions and on Corpus D is **bit-identical** before and after this lands | any change at all |

P3 is the one that matters. P5 is the guard on §4: this rule must be observably
incapable of moving a cost number.

**Written expectation, not a prediction:** P4 is the one most likely to miss.
The 20.0% rate here comes from one person's habits on one machine, and Corpus D
is 1,017 sessions from elsewhere.

## 7. What would make this fail

- **P3 misses**: `unverified_edit` is killed and the reason is published. The
  likely cause is the pattern list, and widening it after seeing the number is
  not available.
- **P2 misses**: there is no corpus that can carry a precision claim for this
  rule, and it does not ship. It is reported as blocked for data, like FM-3.3.
- **P4 misses**: the rule ships, if P3 passes, with the measured spread stated
  as a limit on the claim rather than buried.
- **P5 misses**: stop immediately. A detector that moves a published cost figure
  has crossed the boundary §4 draws, and the fix is not a re-tuning.
- **P1 misses**: stop before labelling anything. Labelling the output of a rule
  that does not implement §3 measures nothing.

Any of these is published as a result, in the same place as the missed Corpus D
prediction and the rejected P5 of the latency amendment.

## 8. Order of work

1. This document, merged, before any code. (rule 8)
2. `unverified_edit` implemented, and P1 checked against the probe on the 85
   sessions. Stop here if it misses.
3. Run on Corpus D, check P2 and P4.
4. Draw 40 at random, hand-label, commit the labels.
5. Compute P3. Check P5 by diffing every cost field on both corpora.
6. Publish the result whether it passes or not. Ship only if P3 is met.

Step 4 does not begin before step 2 passes, and precision is not computed before
step 4's labels are committed.

---

## Appendix: numbers this document is built on

All first-hand, 85 Claude Code sessions on the author's machine, 2026-08-31.

| | |
|---|---|
| tool calls | 14,211 |
| edit calls (`Edit` / `Write` / `NotebookEdit`) | 1,910 |
| verification calls | 749 |
| `is_error: true` results | 384 |
| ...of which from a verification command | **6** |
| sessions | 85 |
| sessions editing a checkable file | 50 |
| **`unverified_edit` candidates** | **10 (20.0% of 50)** |
| draft FM-3.3 rule, rejected by dry-run | 370 candidates from 384 errors |
| FM-3.3 rule as it should be defined | 0 candidates |
