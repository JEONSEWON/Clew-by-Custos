# File Re-Read Detector — Pre-registration (v0.3.0)

**Status.** Pre-registration. Per `feedback_rule_8`, this document is pushed and
PR-opened before any production code change lands. Numbers and KILL conditions
below are the pre-committed frozen positions; adjusting them after seeing
implementation results is not allowed.

**Motivation.** Phase 0 measurement on trace-commons 28 Claude Code sessions
(`field_test/diagnostics/phase0_m2_file_reread.py`) established that the existing
repeat detector reaches only a small fraction of the file re-read waste signal
in real Claude Code traces. Phase 1 verification
(`field_test/diagnostics/phase1_verify_reread.py`) sharpened the numbers and
resolved two open questions: (a) the exact overlap between the existing
`_normalize_input` route and the new no-modification target, (b) the size of
the Bash/PowerShell-based file-modification blindspot. This detector targets
the largest measured recall gap among Clew v0.3.0's repeat-family candidates;
the other two candidates (normalization expansion, abnormal retry) had weaker
or unclear-precision signals on the same dataset and are de-scoped from v0.3.0.

## 1. Detection definition (deterministic signals only)

A **file re-read waste** is emitted when all three hold:

1. **Structural signal.** Two spans `Ra`, `Rb` in the same trace, with:
   - `Ra.agent_or_node_id ∈ {Read, NotebookRead}` and same for `Rb`.
   - Same canonicalized path: `os.path.normpath(Ra.file_path).casefold()
     == os.path.normpath(Rb.file_path).casefold()`, where `file_path` is
     extracted from `json.loads(input_text)` and drawn from the first present
     of `{file_path, notebook_path, path, filepath}`.
   - `Ra.start_time < Rb.start_time` (ordered).
   - `Ra`, `Rb` share the same nearest AGENT ancestor (§16 gate, existing).

2. **State-change gate (no writer-tool between).** Between `Ra.end_time` and
   `Rb.start_time`, there exists **no** span `Wx` such that:
   - `Wx.agent_or_node_id ∈ {Edit, Write, MultiEdit, NotebookEdit}`, and
   - the same canonicalized path.

3. **Shell-conservative gate (no Bash/PowerShell between).** Between
   `Ra.end_time` and `Rb.start_time`, there exists **no** span `Sx` such that:
   - `Sx.agent_or_node_id ∈ {Bash, PowerShell}`, regardless of the command
     content.

If all three hold → `Rb` is flagged as a file re-read waste with origin `Ra`.

**Design of gate 3 (Bash-conservative policy).** Bash/PowerShell tool calls
can modify files via `>`, `>>`, `sed -i`, `mv`, `cp`, `rm`, `tee`, `patch`, git
write operations, `python -c`, `awk -i inplace`, etc. A pattern-based
classifier for these commands is possible (Phase 1 built one) but has known
false-negatives: custom shell scripts, subshells, and commands the classifier
does not enumerate can silently modify files. To defend precision, v0.3.0
excludes **any** pair with a Bash/PowerShell span in the interval. Cost of
this policy on trace-commons: 98 no-modification pairs (314 → 216) are
excluded, of which the classifier saw 44 as modification-looking and 54 as no
match. v0.3.1+ may revisit with a command-content gate if precision holds.

**Not part of v0.3.0 (deliberately out of scope):**
- Semantic-equivalent paths across symlinks / mount points. `os.path.normpath`
  does not follow symlinks.
- File modification signal from OTel/OpenInference metadata that a future
  adapter might carry.
- External file modification (developer's IDE, CI runner, cron) between Reads —
  no in-trace signal available; K5 catches this via manual spot-check.

## 2. Gate placement (cascade vs report)

**Decision: state-change gate + shell-conservative gate both live in cascade,
not report.**

Rationale (code-grounded):
- The existing tool-error gate lives at report layer (`report/_enrich.py`)
  because `is_error` is adapter-level metadata not visible to `structural.py`.
- The state-change gate and shell-conservative gate both require
  cross-referencing spans within the trace — cascade-time operations. They
  belong where `find_repeat_candidates` and `cascade()` already operate.
- The existing sha256 output-equality gate in `cascade.py:62-63` remains
  authoritative for output-identity waste. It naturally rejects pairs whose
  content-observable state actually changed. The state-change and
  shell-conservative gates are complementary — they reject pairs where content
  is identical by coincidence (write+revert, no-op write) but a modifier ran.

**Layering order (proposed):**
```
find_reread_candidates(trace)                # new, in structural.py
    → §16 parent-AGENT gate (existing helper)
    → cascade() branch: state-change gate
                        (no Edit/Write/MultiEdit/NotebookEdit on same path
                         in interval) — new
    → cascade() branch: shell-conservative gate
                        (no Bash/PowerShell in interval) — new
    → cascade() branch: sha256(output_a) == sha256(output_b) gate — existing
    → report/_enrich enrichment (existing modified_in_between field remains
      available for report display but is no longer the gate authority)
```

## 3. Adapter scope

**v0.3.0 supports Claude Code JSONL only.**

- Path extraction relies on `json.loads(input_text)["file_path"]` shape, which is
  the CC adapter contract (`ingest/claude_code.py:87`).
- Bash/PowerShell tool-name recognition also relies on the CC adapter's naming
  convention.
- OTel / OpenInference / RedundancyBench / Toolathlon adapters do not populate
  a Read-vs-Edit-vs-Shell tool taxonomy in the same shape. Extending to those
  adapters requires per-adapter tool-name mapping and per-adapter measurement
  of the same buckets. De-scoped for v0.3.0.

**How the detector behaves on non-CC traces:**
- If `Read`/`NotebookRead` tool spans do not appear (i.e., `agent_or_node_id`
  never matches), the detector emits zero candidates. Passive no-op.
- If a future adapter emits Read-like spans with a different path-field name,
  the extraction returns `None` and the span is silently skipped. This is a
  pre-committed compromise: no measurement outside CC.

## 4. Predictions (frozen — must be committed before implementation)

Baseline (Phase 0 + Phase 1 measured on trace-commons 28 CC sessions):
- 4,262 tool spans total.
- 847 Read/NotebookRead spans, 1,613 Edit-class spans, N Bash/PowerShell spans.
- 1,908 same-path Read pairs total.
  - 314 with no writer-tool between (Phase 0 M2).
  - 1,594 with writer-tool between (excluded by state-change gate).
- Of the 314 no-writer pairs (Phase 1 Q1-b buckets):
  - 216 have **no** Bash/PowerShell in the interval → survive shell-conservative gate.
  - 32 have a Bash matching a definite-write pattern (`>`, `>>`, `sed -i`, `mv`,
    `cp`, `rm`, `touch`, `tee`, `patch`, `dd of=`, etc.).
  - 0 have a git-write pattern (trace-commons artifact, not a general bound —
    see §10).
  - 12 have a possible-write pattern (`python -c`, `node -e`, `npm install`,
    `pip install`, `tar`, `make`, `cargo`, `go`).
  - 54 have Bash with no modification pattern (excluded anyway for precision).
- Of the 1,908 same-path pairs, 103 already match under the existing
  `_normalize_input` grouping. Of those 103: 20 are no-writer pairs (real
  overlap with the new detector's target), 83 are writer-between (cascade
  sha256 already handles).

Predicted post-detector outputs on the same 28 sessions:
- **File re-read waste candidates emitted by `find_reread_candidates`: 216**
  (upper bound; may drop slightly after §16 parent-AGENT gate on real data).
- **Marginal recall gain over current cascade: +196 no-writer, no-shell pairs**
  (= 216 shell-conservative survivors − 20 already reachable).
- **Bash-blindspot false positives from the new detector: 0** (excluded by
  construction). Trade-off: 98 of 314 no-writer pairs (31.2%) are sacrificed
  to defend precision; a v0.3.1 command-content gate may recover some.
- **Effect on frozen-set F1 (pingpong_aba, repeat_node — both `llm` kind):
  zero.** The new detector operates only on `tool`-kind Read spans and does
  not touch any code path used by `llm` kind detection.
- **Effect on RedundancyBench F1:** predicted change **≥ 0** (either unchanged
  or improved). RB does not annotate file re-reads (all four categories are
  tool-call redundancy at the API level), so recall shouldn't change; precision
  shouldn't drop because the new detector emits on distinct span shape.
  Specific frozen prediction: **RB F1 stays within ±0.005 of 0.2642**.
- **Full test suite:** 239 → 239+N passed (N ≥ 5 new tests for the reread
  detector; existing 239 unchanged).

## 5. Success / KILL criteria (pre-committed, not adjustable)

**Success conditions** (all must hold to ship v0.3.0):
- **S1.** `find_reread_candidates` emits ≥ **200** candidates on trace-commons
  28 CC sessions after all cascade gates. Measured Phase 1 upper bound: 216.
- **S2.** Post-cascade waste output on the same 28 sessions increases to
  ≥ **200** total waste spans (from pre-v0.3.0 baseline of 34). Predicted
  under Option A: 34 baseline + ~194 new = ~228.
- **S3.** Frozen-set F1 (repeat_node, pingpong_aba) unchanged bit-for-bit.
- **S4.** RB F1 change within ±0.005 of 0.2642.
- **S5.** Full test suite: all currently-passing 239 tests still pass; new
  tests for reread detector cover at least: (a) same-path different-args pair,
  (b) same-path with intervening Edit → not flagged, (c) same-path with
  intervening Write → not flagged, (d) same-path with intervening
  Bash/PowerShell → not flagged (shell-conservative gate), (e) NotebookRead
  + NotebookEdit interaction, (f) different-agent-ancestor pair filtered by
  §16 gate.
- **S6.** Leakage guard (`tests/test_leakage.py` or equivalent) still passes;
  new detector never reads eval labels / dev set directories.

**KILL conditions** (any one triggers de-scope of the reread detector; the
0.3.0 release ships without it):
- **K1.** Candidates emitted < 100 (indicates path extraction or gate
  mis-implemented — 216 measurement did not carry to actual detector).
- **K2.** Frozen-set F1 changes at all (indicates the new code touched code
  paths it should not have).
- **K3.** RB F1 drops below 0.2592 (= 0.2642 − 0.005).
- **K4.** Manual review of a random 30-pair sample from the new detector's
  output on trace-commons 28 sessions reveals precision < 0.70. Definitions:
  - **Precision** = fraction of flagged pairs a human annotator confirms as
    "wasteful re-read" (same file, no legitimate reason to re-read).
  - **Sample construction**: random 30 pairs drawn from the new detector's
    output. Random seed: **42** (pre-committed here; regenerating the sample
    after seeing results is forbidden).
  - **Annotator**: session owner (project maintainer).
  - **Timing**: after implementation, before merge.
- **K5.** Manual sample (same 30-pair set from K4) reveals evidence of external
  file modification (developer's IDE / CI runner / terminal outside the trace
  / cron job) in > 15% of flagged pairs. Detects the one blindspot the
  shell-conservative gate does not close. If exceeded, the detector cannot
  distinguish trace-visible re-reads from filesystem-external state changes on
  this dataset — de-scope.
- **K6.** New detector adds a hard dependency on any package not already in
  the `[detect]` extras list (must remain lightweight per v0.2.0 packaging
  split).

## 6. Detector vs extension decision

**Decision: separate new function `find_reread_candidates(trace)` in
`structural.py`, combined into `find_candidates` alongside existing detectors.
Not an extension of `find_repeat_candidates`.**

Code-grounded rationale:
- `find_repeat_candidates` groups by `(agent_or_node_id,
  _normalize_input(input_text))` — signature is "same tool called with same
  normalized args". Path-based grouping has different semantics: "same tool
  acting on same file, args may differ".
- Grafting path-based grouping onto `find_repeat_candidates` would either
  double the group set or fork the loop by `span_kind == tool AND
  agent_or_node_id ∈ READ_TOOLS`. Both bloat the function.
- Separate function keeps `find_repeat_candidates` unchanged bit-for-bit
  (verifies K2/S3 by construction).
- Combination point is `find_candidates` (`structural.py:107-117`) which
  already deduplicates by `(origin, cand)` span_id pair.

Cascade change:
- Cascade must learn to treat reread candidates differently from repeat
  candidates. A `candidate_kind` field on the candidate tuple, or a separate
  code path in `cascade()` for reread candidates, is required. The two new
  gates (state-change, shell-conservative) apply only to reread candidates,
  not to repeat candidates. Concrete design deferred to implementation PR —
  this pre-registration commits only that cascade will branch, not how.

## 7. Test plan (pre-committed)

New tests (target ≥ 6, one per S5 case):
- `tests/test_reread_detector.py::test_same_path_different_args_flagged`
- `tests/test_reread_detector.py::test_same_path_edit_between_not_flagged`
- `tests/test_reread_detector.py::test_same_path_write_between_not_flagged`
- `tests/test_reread_detector.py::test_same_path_bash_between_not_flagged`
- `tests/test_reread_detector.py::test_notebook_pair_uses_notebook_path_field`
- `tests/test_reread_detector.py::test_different_agent_ancestor_filtered`

Regression:
- Full 239-test suite must pass unchanged.
- Frozen-set integration tests must produce bit-identical `waste_span_ids`.

Leakage guard:
- No eval label directory read.
- Path extraction is pure (uses only `input_text`, no filesystem access).

## 8. Roll-out & versioning

- New detector lands in a single PR branching from `main` post-v0.2.0 merge.
- Commit chain (do NOT squash, per `feedback_rule_8`):
  1. `feat(structural): find_reread_candidates for same-path Read pairs`.
  2. `feat(cascade): state-change + shell-conservative gates for reread`.
  3. `test(reread): 6 unit tests covering S5 cases`.
  4. `docs(readme): mention Read re-read waste in v0.3.0 changelog`.
- The pre-registration PR (this document) is separate and must merge first.
- Version bump `0.2.0` → `0.3.0` in the implementation PR (feat-level
  addition, new detector = minor bump).
- Post-merge validation: rerun the Phase 0 M2 script and Phase 1 verify script
  on the same 28 sessions; compare marginal recall (S1, S2) and Bash-blindspot
  behavior against predictions.

## 9. Open items (post pre-registration, before implementation PR)

The following were closed by pre-registration commit; listed here for
traceability:
- **Bash blindspot policy** → resolved: shell-conservative gate (Option A).
- **K4 sample seed** → resolved: `random.seed(42)`.
- **Document location** → resolved: separate file at
  `docs/REREAD_DETECTOR_PREREG.md`.

Still open (do not block pre-registration merge):
- **Non-CC adapters roadmap.** OTel/RB/Toolathlon path extraction requires a
  separate measurement pass. Not v0.3.0 scope.
- **v0.3.1 command-content gate.** Whether to add a Bash-command classifier
  to recover some of the 98 shell-excluded pairs. Depends on v0.3.0
  precision result.

## 10. Measured evidence supporting this pre-registration

`field_test/diagnostics/phase0_m1_normalization_gap.py`:
- Established candidate A (normalization expansion) recall gain = 0 on CC
  trace-commons. De-scoped from v0.3.0.

`field_test/diagnostics/phase0_m2_file_reread.py`:
- 314 no-writer same-path Read pairs (16.5% of 1,908 same-path pairs).
- Current `_normalize_input` matches 103 of 1,908 (5.4%).

`field_test/diagnostics/phase0_m3_failure_retry.py`:
- Abnormal retry has strong recall signal (190/269 = 70.6% of errors get a
  retry) but schema-cause is 2/190 (1.1%). Retry precision unmeasurable
  without cross-checking retry outcomes. Deferred to a separate
  pre-registration; v0.3.0 does not include an abnormal-retry detector.

`field_test/diagnostics/phase1_verify_reread.py`:
- Of the 103 current-matches, 20 are no-writer (real overlap with new
  detector's target) and 83 are writer-between (cascade sha256 already
  handles). Marginal gain = 216 − 20 = **196** under Option A, not the
  earlier 294 (which counted before shell-conservative gate).
- Of 314 no-writer pairs: 216 no-shell, 32 definite-write Bash, 0 git-write,
  12 possible-write, 54 non-modifying Bash.
- git-write count of 0 is a **trace-commons-specific artifact**, not a general
  bound. Developers in this dataset performed git operations outside the
  Claude Code trace (via IDE / terminal directly). Other datasets may show
  non-zero git-write in interval; K5 catches this via manual spot-check.

All four diagnostic scripts remain untracked under `field_test/diagnostics/`
per `feedback_diagnostics_uncommitted`.
