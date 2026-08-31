# Verification Judge: Results

Measurement against the predictions in
[`VERIFICATION_JUDGE_PREREG.md`](VERIFICATION_JUDGE_PREREG.md) §6, which its §8
step 4 requires be published whether it passes or not. Scored 2026-08-31, the
same day the pre-registration merged.

**Headline: all five predictions pass. Precision 0.9286 against a
pre-registered 0.70, on the identical 40 candidates where the structural rule
scored 0.3250.** The interpretation layer is what the deterministic rule was
missing, and the size of the gap is the result.

| # | Prediction | Result |
|---|---|---|
| **P1** | precision ≥ 0.70 | **PASS**, **0.9286** (13/14) |
| **P2** | recall ≥ 0.60 | **PASS**, **1.0000** (13/13) |
| **P3** | beats 0.3250 on this identical set | **PASS**, 0.9286 vs 0.3250 |
| **P4** | 0 verdicts cite absent evidence | **PASS**, 0 of 14 |
| **P5** | parse failures ≤ 2 | **PASS**, 1 |

Model `claude-haiku-4-5`, the frozen default of the existing judge axis. 40
calls, **73 seconds**, **$0.183** total.

## 1. The comparison the document existed for

Same 40 sessions. Same labels, committed before any judge existed. Same gate.

| | precision | recall | findings |
|---|---|---|---|
| structural rule alone | 0.3250 | 1.0000 | 40 |
| **structural + judge** | **0.9286** | **1.0000** | **14** |

The structural rule flagged all 40 and was right about 13. The judge kept 14 and
was right about 13, rejecting 26 of the 27 sessions that had verified by a route
no list contained. Recall did not move: nothing true was lost.

That is the whole argument of the previous kill, confirmed from the other side.
The rule's 18-command list was not too short; the question was not a list
question. `python solution.py`, `node buffer.js`, `python -c "from x import y"`,
`rustc --test`, `node x.test.js` are all checks, and the judge recognised them
without being told any of them.

## 2. The judge found an error in our labels

One disagreement, and it was ours.

`math_problems/afd9b479.jsonl` was hand-labelled **checked** because the
session runs `python3 convex_hull.py`. The judge said not-checked, at
confidence 0.95, with this reasoning: the `Write` failed, so what ran was the
file already on disk, not the agent's change.

Read back from the trace:

```
Write   ->  <tool_use_error>File has not been read yet. Read it first...
Bash    ->  ls /data/agent/.../convex_hull.py    exit:0
Read    ->  (the pre-existing file)
Bash    ->  python3 convex_hull.py               (runs the pre-existing file)
```

**The judge is right about the facts.** The agent's edit never landed, and the
program it ran was not the program it had tried to write.

§5 of the pre-registration said a label found to be wrong is published as a
correction with both figures shown, so:

| reading | precision |
|---|---|
| as labelled (this candidate counts as a false positive) | **0.9286** |
| with the label corrected | **1.0000** |

**The headline stays 0.9286.** The label was committed first and the gate was
met without needing the correction; taking the better number because a judge
argued for it is the move pre-registration exists to prevent. The corrected
figure is recorded, not claimed.

## 3. A defect in the candidate generator, found by that one case

Chasing the disagreement exposed something about the structural rule that its
own kill report did not catch: **it counts edit attempts, not edits.** A `Write`
that returns `<tool_use_error>` changes nothing and is still counted.

Measured over all 522 candidates:

| | |
|---|---|
| candidates with at least one failed edit | **168 (32.2%)** |
| candidates where **every** edit failed | **61 (11.7%)** |

Those 61 sessions changed no code at all. The premise of the finding — "changed
checkable code and never checked it" — is false for them, and roughly one
candidate in eight was in the pool for a reason that does not exist.

This does not change any number above: the judge sees the failed `Write` in the
view and reasons from it, which is how the case surfaced. It is recorded because
the killed rule is still the candidate generator, and a generator that inflates
its pool by 12% with sessions where nothing happened is worth knowing about
before anything is built on top of it.

## 4. P5 passed, and one of the forty was not judged

One response was not JSON: `code_generation/e20743a3.jsonl`. The axis returns
`checked: true` on a parse failure, which is the non-finding, and that session
was labelled `checked`, so it is counted as agreement.

**That agreement is luck, not judgement.** It comes from the failure default
landing on the correct side by accident. Had the row been a labelled positive it
would have been a missed finding, and recall would have been 12/13 = 0.923 —
still inside P2, which is the only reason this does not change the verdict.
Recomputing without that row leaves both metrics unchanged, because it was a
negative.

Failing to the non-finding is the deliberate choice §2 of the implementation
records: an axis whose errors produce findings reports the API's bad day as the
agent's mistake. The cost is exactly this — a silent non-finding — and the run
log names which row it was.

## 5. P4 passed, and our first check of it was wrong

The first P4 check searched each **trace** for the judge's quoted evidence and
found one quote missing: `refactoring/122c6774.jsonl` cited `'ACTION Write'`.

`ACTION Write` is a label **our own renderer writes**. The judge quoted what was
in front of it; the checker looked at a different artifact. Re-checked against
the view actually sent, **0 of 14** cite anything absent.

★ This is the day's own lesson landing on the person who wrote it down: assert
on what was shipped, not on what produced it. The rendered view is what the
judge was shown, and the trace is only its source. Both figures are here rather
than only the passing one.

## 6. What this does and does not establish

**Establishes:** on 40 candidates drawn at random from 522, with labels
committed in advance, a judge reading the session reaches 0.9286 precision at
full recall where a structural rule reached 0.3250. FM-3.2 is answerable by
interpretation on this evidence.

**Does not establish:**

- **That the population precision is 0.93.** These 40 are candidates the
  structural rule proposed. The pair's precision on the other 482 is not
  measured, and §8 step 5 is where a second corpus goes.
- **That recall is 1.0 in general.** The 13 positives on this set are sessions
  that ran nothing at all, which the pre-registration called "the easy half"
  before the run. A session that ran something irrelevant and called it a check
  is the hard case and is not represented here.
- **That it ships.** Whether the pair ships, and whether it ever feeds an
  alert, are separate decisions §8 step 6 keeps separate.
- **Anything about the other thirteen failure modes.** One axis, one mode.

**Cost, for planning rather than as a claim:** $0.183 for 40 sessions on
`claude-haiku-4-5`, mean 42 KB per session. The 522-candidate population is
about 13 times that. Nothing here is priced for a customer.

## 7. What comes next, in the order §8 fixed

Step 5 is a second corpus:
[`mcemri/MAST-Data`](https://huggingface.co/datasets/mcemri/MAST-Data),
CC-BY-4.0, 1,642 traces across 7 multi-agent frameworks, with FM-3.2 marked on
608 of them. **Their labels are not ground truth** — their README says the
annotations come from an LLM judge, not from human labelling — so they stratify
a sample we label ourselves, 20 marked 1 and 20 marked 0, and disagreement with
their judge is reported as its own finding.

That corpus is read as text. Its trajectories are raw per-framework logs, not
structured spans, and 48% of them carry no per-step timestamps at all, which is
why the deterministic route would need seven parsers there and the judge needs
none.
