# HANDOFF — Clew/Custos handoff to the next owner

**Rule 7 applies**: this document is derived from SPEC. It is not written alongside it.

- Fact sources: `field_test/SWECHAT_SPEC.md` §19, §19.1, §19.2, §19.3 and `docs/CC_TRANSCRIPT.md` §21, §22.
- Every number carries its source section. No new numbers were minted here.
- If this document conflicts with SPEC, SPEC is authoritative.

---

## 1. Current state (2026-07-17)

### Branch / commit state
- Active branch: `feat/cc-adapter` (in sync with origin).
- Latest merge: PR #12 (`6ea7adc`, main). The entire CC adapter round was handed off `feat/cc-adapter → main`.
- Last commit (this round): `92a2a14` — §22.7 first-run diagnosis fold-back.

### T1 achieved
- **T1 = "Pass a Claude Code session JSONL through the pipeline"** — achieved. Source: `docs/CC_TRANSCRIPT.md` §22.6.
- On target session `f96aee88-…`, `python -m clew analyze <path>.jsonl` completed without error (total_spans 181, 0 join failures, 0 Pydantic validation failures). Source: `docs/CC_TRANSCRIPT.md` §22.6.
- First-run result: 3 waste — Edit cos=1.0000, Write 0.9959, Bash 0.6577. Source: `docs/CC_TRANSCRIPT.md` §22.6 table.
- **All 3 are false positives.** Source: `docs/CC_TRANSCRIPT.md` §22.7 summary table.

### Adapter mapping (frozen §22.1)
- `span_id = tool_use.id` (1:1 join, `docs/CC_TRANSCRIPT.md` §21.3 Q6: 180/180 unique).
- `input_text = json.dumps(tool_use.input, sort_keys=True, ensure_ascii=False)` (§22.2).
- `output_text` — str passes through, list concatenates text blocks, other types get `json.dumps + warn` (§22.5 addendum, 2026-07-17).
- v1 spanifies only `tool_use ↔ tool_result` pairs. thinking/text blocks do not become spans (§22.3).

### Rule application state
- **Rule 7 (fold-back)**: `docs/CC_TRANSCRIPT.md` §21 (transcript recon), §22.7 (diagnosis) — after external raw is checked, immediately reflected into SPEC.
- **Rule 8 first application**: `field_test/SWECHAT_SPEC.md` §19.2 (v4 classifier pre-registration, commit `82d905d` push → result commit `04bd49d` ordering established). Source: SPEC §19.2 "Rule 8 commit chain" table.
- CC adapter round (`feat/cc-adapter`) also applied Rule 8 in practical form: §22 pre-register (`bbd9c9e`) → code (`e6dc770`) → result (`b7ed00c`) → fold-back (`92a2a14`).

---

## 2. What can be said · what cannot be said (honesty boundary)

### Can be said
- **False-positive elimination rate 87.0%** (file-level 15,787 → range-level 2,053). Source: `field_test/SWECHAT_SPEC.md` §19.1 rerun-verification section + honesty boundary.
- **Prediction hits**: (a) §19.1 false-positive-elimination-rate drop prediction hit (91.7% → 87.0%, range-level ×2.066 > file-level ×1.320). (b) §19.2 v4'' prediction hit (v4'' = 955 ∈ [950, 1000]). Source: SPEC §19.1 "prediction hit" · §19.2 result "prediction hit".
- **Vendor gold set 71 = true-positive lower bound**. 71 / 2,053 = 3.458% (v1' full denominator). Source: SPEC §19 "vendor gold set". **This is not precision.**
- **T1 fact**: CC JSONL → Trace pipeline passes. Source: `docs/CC_TRANSCRIPT.md` §22.6 · §22.7 honesty boundary.
- **The absence of plaintext thinking is a vendor structural limit, not a dataset-pipeline loss.** Confirmed via source recon. Source: `docs/CC_TRANSCRIPT.md` §21.1 (496/496 zero as of 2026-07).
- **tool_use ↔ tool_result 1:1 join** (from source). SWE-chat's 1:N (max_dup=5) is a pipeline artifact. Source: `docs/CC_TRANSCRIPT.md` §21.3, §21.5 (cross reference).
- **§21.4 vendor format switch (2026-03-28)** confirmed via source transcript. Source: `docs/CC_TRANSCRIPT.md` §21.4.

### Cannot be said (do not cite)
- **Do not cite "91.7%" alone** — based on contaminated EDIT judgment. Must pair with 87.0%. Source: SPEC §19 "key findings" footnote.
- **Do not describe "87.0% is a differentiator vs. read-once"** — the two tools go through different paths for the same goal (measurement vs. avoidance). 87.0% is only valid as methodological grounding "vs. naive file-level matching". Source: SPEC §19.1 honesty boundary clause (2026-07-17 fold-back), §19.3 "do not cite".
- **Do not cite "42% first-Read failure observed"**. The original 41.66% was a compound of two bugs (regex misclassification 15.66% + window-any). Observed recalculation (v4'' × prev-tcid × `[→\t]`): error 7.31% ~ unknown-included 22.72%. **The principle (first-attempt success is essential to the judgment) holds; the magnitude collapses.** Source: SPEC §19.2 observation 6.
- **Do not describe v1' 3.381% / v4' 1.413% / v4'' 1.573% as "upper bound" or "minimum"**. Source: SPEC §19.1 · §19.2 honesty boundary.
- **Do not cite "waste found in 22.42% of sessions" alone**. Source: SPEC §19.1 honesty boundary.
- **Do not describe "Claude Code already prevents re-reads via vendor cache"** — 29 of v3' 1,272 (2.28%). Source: SPEC §19 "vendor cache response correction".
- **Do not cite "clew analyze detected N waste on CC session"** — first run 3/3 false-positive. Until defects 1~4 are fixed, detection numbers are meaningless. Source: `docs/CC_TRANSCRIPT.md` §22.7 honesty boundary.
- **Do not cite "13 → 4 = 69.2%" from §22.7 observation** — n=25, single session. **Record only the fact of direction reproduction.** Source: `docs/CC_TRANSCRIPT.md` §22.7 observation.
- **Do not cite §21.2 token usage 5-pair hypothesis (`prev.cache_read + prev.cache_creation = next.cache_read`)** — 5-pair observation. Before full-set verification, discipline 5 (unverified causation). Source: `docs/CC_TRANSCRIPT.md` §21.2.
- **When describing externally that "§19 / §19.1 was pre-registered", pair with the clause "commit order is proven but external timestamp is post-result".** §19.1 deviation 3. From the next round onward (§19.2, CC adapter) Rule 8 is applied.
- **Must pair unknown 15.409% clause**: when citing v4'' = 955, add "the classifier could not confirm 15.4% of v3'". Source: SPEC §19.2 "negative-result definition triggered".

### Retracted narratives (correcting the previous handoff)
- **Finding ② "'First-attempt success' is essential to the waste judgment — 42% observed"** — retract the 42% citation. Keep only the principle. Source: SPEC §19.2 observation 6.
- **Finding ① "91.7%"** — corrected to 87.0%. "Vs. read-once" framing removed. Source: SPEC §19.1 honesty boundary + §19.3 do-not-cite.
- **v4** — the latest classifier is v4'' (2026-07-17, prev-tcid + `[→\t]` + unknown category). Source: SPEC §19.2 result.

---

## 3. Next work — §22.8 pre-registration targets

**§22.8 has not been written yet.** Defects 1~4 have been diagnosed, but the fixes are pre-registration targets.

### Defects to be resolved (all sourced from `docs/CC_TRANSCRIPT.md` §22.7)
1. **Defect 1 — origin pinning** (`src/clew/detect/structural.py:64,68`): pins `origin = occurrences[0]`. Even if occurrences[i] vs occurrences[j] (i,j ≥ 1) are identical, they both drop out if they differ from origin. Observed evidence: 4 fully-identical Read `(file_path, offset, limit)` re-invocations existed, but 0 repeat candidates. **§19 compares all pairs. The product and the analysis use different algorithms.**
2. **Defect 2 — pingpong input gate missing** (`structural.py:85-88, 99`): compares only `agent_or_node_id`. All 3 waste came from pingpong, 3/3 false-positive. Same family as SPEC §19.1 `EDIT_TOOLS unknown_hit`, §19.2 `all_success` (label/comment vs. logic mismatch).
3. **Defect 3 — Edit/Write output_text is a template** (`src/clew/detect/cascade.py:36`): Edit distinct 5/31 (16%), Write prefix `"File created successfully at: <path>"`. **φ compares output_text, so cos is always high on top of a template.** The structural gate is the sole defense. Defects 1·2 pierce that defense.
4. **Defect 4 — Bash `description` hides command re-invocations**: in the full input serialization (§22.1), a new description is appended on every call, so 9 command-only identical re-invocations are lost. **One direct cause of repeat 0.** SPEC §20 was designed to look only at the command string. Here they diverge.

### Pre-registration constraints (when writing §22.8)
- **φ = 0.514345 is frozen.** Do not solve defect 3 by adjusting φ. Source: `docs/CC_TRANSCRIPT.md` §22.7 unresolved.
- Rule 8 procedure: pre-register commit → push + open PR (external timestamp fixed) → run → result commit. Merge must be a merge commit. Source: SPEC prohibition rule 8 addendum.
- Do not modify prediction · stop-condition · definition after the result. Source: SPEC prohibition rules 1~6 + §19.2 "prohibitions".

### Judgment point (defect 3 unresolved, `docs/CC_TRANSCRIPT.md` §22.7)
- For Edit/Write, **input looks like signal, output like noise** (re-applying the same file + same new_string = waste).
- This lies on both the §22 mapping and the cascade design. §22.8 pre-registration target.

---

## 4. Clean findings

**Cite only in the corrected form.**

1. **Methodological gain of the precise target definition: file-level 15,787 → range-level 2,053, 87.0% false-positive elimination.**
   - Source: SPEC §19.1 rerun-verification section.
   - Clause: only valid as methodological grounding "vs. naive file-level matching". Not a differentiator vs. read-once.
   - Prediction grounding: range-level growth rate ×2.066 > file-level ×1.320 (SPEC §19.1 prediction hit).

2. **Whether the first Read failed is essential to the waste judgment (principle retained, magnitude collapsed).**
   - Source: SPEC §19.2 observation 6 + observation 5 (gap correlation).
   - v4'' × prev-tcid × `[→\t]`: error 93/1,272 = 7.31%, unknown 196 = 15.41%.
   - The window method exaggerated this signal (99% at gap≥100). prev-tcid direct join is the correct axis.
   - **Do not cite "42%".**

3. **Vendor gold set true-positive lower bound 71 = 3.458%.**
   - Source: SPEC §19 "vendor gold set".
   - `tool_call_id` join method (no adjacency fallback; progress row 49% is structurally unsuitable).
   - **Not precision. True-positive lower bound.**

4. **v4'' classifier prediction 950~1000, observed 955.**
   - Source: SPEC §19.2 result "prediction hit".
   - Pre-registered 3-cell (858/812/1,006/424/516) reproducibility hit.
   - Clause: must pair unknown 15.4%.

5. **Self-reproduction of the read-target redefinition (direction only).**
   - Source: `docs/CC_TRANSCRIPT.md` §22.7 observation.
   - The SWE-chat 87.0% thesis reproduces in direction on CC's own session. **Do not cite the value, n=25.**
   - The first case where a thesis measured on other people's data reproduced on our own.

6. **T1 pipeline pass (technical achievement).**
   - Source: `docs/CC_TRANSCRIPT.md` §22.6.
   - CC JSONL adapter + tool_use↔tool_result 1:1 join + sort_keys serialization + list-content convention (§22.5) works on a real session.
   - **Waste-detection performance is separate.**

---

## 5. Disciplines 1~8

### Disciplines 1~6 (base, see SPEC prohibition clauses)
- (1) No post-hoc modification of pool definition.
- (2) No post-hoc tuning of target normalization rules.
- (3) **Confirm raw.** Applies even to background-fact statements. Field names · term meanings must be confirmed against code before entering the honesty boundary. Source: SPEC §19.1 deviation 5 + §19.3 deviation.
- (4) Do not cherry-pick waste-heavy sessions.
- (5) Do not cite unverified causation (§21.2 5-pair hypothesis is a target).
- (6) Do not modify the control-group definition because the value went down.

### Rule 7 — fold-back
- **Findings are immediately reflected into SPEC.** Script docstrings · print · chat logs are not records.
- **Handoffs are derived from SPEC.** Not written alongside — this document is the example.
- Addendum: folding back does not permit deleting the code that produced the conclusion. The reproduction path must remain.
  - Put one-off diagnostic scripts under `field_test/diagnostics/` with a header listing the SPEC section they reproduce. Example: `field_test/diagnostics/diag_cc_first_run.py` (§22.6/§22.7 reproduction).
- Source: SPEC prohibition rule 7 + `docs/CC_TRANSCRIPT.md` §22.7 fold-back execution.

### Rule 8 — push pre-registration first
- **A local commit only proves order, not time.** `GIT_COMMITTER_DATE` is manipulable.
- **The push event (GitHub server side) is the only external timestamp.**
- **PR open time = timestamp.** No need to wait for merge.
- **Merge method**: must be merge commit. squash/rebase rewrites SHAs, leaving cited hashes dangling → destroys the pre-registration argument.
- Source: SPEC prohibition rule 8 + addendum (main branch protection).

### Rule 8 application history
| Round | Pre-registration commit (push time fixed) | Result commits |
|---|---|---|
| §19.2 v4'' | `82d905d` | `04bd49d`, `f502002` |
| CC adapter (§22) | `bbd9c9e` | `e6dc770`, `b7ed00c`, `92a2a14` |

---

## 6. Backlog

### §22.8 targets (next pre-registration)
- Defect 1 (origin pinning) fix.
- Defect 2 (pingpong input gate) fix.
- Defect 3 (Edit/Write output_text template) fix — needs a mapping-vs-cascade design decision. φ tuning not allowed.
- Defect 4 (Bash description hiding) fix.
- Source: `docs/CC_TRANSCRIPT.md` §22.7.

### Verification backlog
- **§21.2 5-pair hypothesis full-set verification** — tool_result text → next assistant `cache_creation_input_tokens` attribution. If verification succeeds, token values can be attached to waste judgments. Source: `docs/CC_TRANSCRIPT.md` §21.2 backlog.
- **§21.3 multi-session 1:1 join confirmation** — currently on 1 session. Source: `docs/CC_TRANSCRIPT.md` §21.3 implication.
- **§22.6 multi-session repeat=0 reproducibility check** — whether it is this session's property or a general phenomenon. Source: `docs/CC_TRANSCRIPT.md` §22.6 implication.
- **§22.6 Edit cos=1.0000 in-session check** — without exposing transcripts. Source: `docs/CC_TRANSCRIPT.md` §22.6 implication.

### Unresolved observations (do not conclude from unverified hypotheses)
- **Observation 2 — First-Read failure retry ratio drop** (v3 41.66% → v3' 29.87%, absolute count 317 → 380 increased). Not explained by the structural-consequence mechanism. Source: SPEC §19.1 unresolved observation.
- **Observation 3' — v1'/v4' candidate-population character change**. Newly promoted median gap 189 vs. retained 9. Cannot judge whether long-gap re-reads are the same character of waste as short-gap. Source: SPEC §19.1 unresolved observation.
- **Observation 4 — `os.path.normpath` OS dependency**. On Windows/Linux reruns, CSV literal representation differs. If relative/absolute matching depends on separators, results may diverge — unverified. Source: SPEC §19.1 unresolved observation.
- **Observation 5 — Causation of prev=success × gap correlation**. Correlation is observed; the causation (first failure → immediate retry, first success → long gap) is unverified. Source: SPEC §19.2 observation 5.
- **§19.3-1 — mtime blind spot**. The read-once prevention coverage cannot be observed (no mtime data). No current method for quantitative comparison against read-once from the Clew waste-candidate CSV. Source: SPEC §19.3.

### Separate SPEC targets
- **Bash investigation** (239,553 cases / Grep 56,593 cases). Vendor-side prevention unverified area. Separate SPEC after §19 primary is fixed. Source: SPEC "next investigation direction".

### E unmatched residual (§19.2 result)
- `File does not exist ...` category pre-registration omitted. Handle in the next revision round respecting Rule 8. **No string/category additions in this round.**
- `File content ... exceeds maximum allowed tokens ...` string (deviation 7 family). Next round.
- 68 cases of `\d+[→\t]` prefixed by `<system-reminder>` (anchor bypass) — classified as unknown (as pre-registered).
- Source: SPEC §19.2 observations 1·2·3.

---

## SPEC conflict report

**No conflict found.** All numbers · statements in this document are derived from SPEC (§19-§19.3, `docs/CC_TRANSCRIPT.md` §21-§22.7). SPEC is authoritative. If this document appears to conflict with SPEC, follow SPEC and correct this document.
