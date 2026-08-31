# Shipping the Verification Judge (Pre-registration)

**Status.** Ships the axis measured in
[`VERIFICATION_JUDGE_RESULTS.md`](VERIFICATION_JUDGE_RESULTS.md), whose §8 left
"whether the pair ships" as its own decision. Per `feedback_rule_8` this is
pushed before the wiring. The default in §2, the output rules in §3, the caps
in §4, the predictions in §6 and the stop conditions in §7 are frozen.

---

## 0. What exists and what does not

**Measured.** `structural rule + judge` scores **precision 0.9286, recall
1.0000** on 40 hand-labelled Claude Code sessions, against a pre-registered
0.70. The structural rule alone scored **0.3250** on the identical 40 and was
killed. On a second corpus (AG2 and MetaGPT, 40 traces) the axis separated
MAST's own strata by 45 points. `claude-haiku-4-5`, 40 calls, 73 seconds,
$0.183.

**Not built.** `src/clew/detect/llm_judge/verification_judge.py` holds the
prompt, the verdict parser and the metrics. Nothing calls it: `__main__.py` and
`report/` contain zero references. The axis is a measurement with no surface.

This document is that surface, and nothing else. It adds no detection.

## 1. Why it needs a pre-registration at all

Two reasons, and neither is the detection quality:

1. **It spends the user's money.** The judge calls the Anthropic API with the
   user's `ANTHROPIC_API_KEY`. Every existing detector is free and local. A
   default that quietly bills someone is a different kind of change from a
   default that quietly computes something.
2. **A wrong finding is an accusation.** "You changed code and never checked
   it" is a sentence about the person, not about the trace. 0.9286 was measured
   on 40 sessions from one machine, and one in fourteen was wrong there.

## 2. The default: off, opt-in by flag

**`boxdawn analyze --verification`**, and `CLEW_ENABLE_VERIFICATION=1` for
unattended runs. Off otherwise.

Same shape as `--llm-judge`, which is the existing precedent for a paid,
optional axis, and the same reason: a tool that reads finished traces should
not open a billing relationship the user did not ask for.

**Not chosen: on by default.** It would make the product's accuracy depend on
whether a key is configured, which is the shape
`project_product_structure_3tier` rules out — measurement accuracy is not a
paid tier. Off-by-default keeps the free path and the paid path measuring the
same things, with the paid one seeing an additional axis it was asked to see.

## 3. What the report may say, and what it may not

**Three outcomes, and the third is not optional.**

| verdict | shown as |
|---|---|
| the session verified its work | nothing. No finding. |
| the session did not verify | a finding, naming the edit and the absence |
| the judge could not tell | **"not judged"**, with the reason |

"Could not tell" covers: no API key, the call failed, the response did not
parse, the trace has no editing to judge. **None of these may be rendered as
"not verified".** An axis that reports absence of evidence as evidence of
absence earns the same fate as the rule it replaced.

The finding text states what was observed, not what the person failed to do:
the edit, and that no verification of it appears in the trace. `feedback_
observed_not_confirmed` applies here as it applies to the detectors.

## 4. Caps, stated as numbers

| | |
|---|---|
| calls per analysed trace | **exactly 1** |
| model | `claude-haiku-4-5`, the frozen default of the existing judge axis |
| measured cost | **$0.0046 per session** ($0.183 over 40) |
| measured latency | **1.8 s per session** (73 s over 40) |
| on any failure | the axis reports "not judged" and `analyze` still exits 0 |

One call per trace is the cap that matters. The axis reads a rendered view of
the session and answers once; it does not iterate, retry on a parse failure, or
fan out per edit.

## 5. What is explicitly NOT changed

- **Every deterministic detector**, its thresholds, φ, N, the embedder.
- **Every figure.** WR_char, WR_cost, waste spans, cost attribution. The axis
  adds a report section and contributes to no metric.
- **The default output.** With the flag off, `analyze` produces what it
  produces today.
- **The alert path.** Whether this axis ever feeds an alert is a separate
  decision, as `VERIFICATION_JUDGE_RESULTS.md` §8 says. It does not here.
- **The killed rule.** `unverified_edit` does not ship on its own; it is the
  candidate generator behind the judge and its 0.3250 stands published.

## 6. Predictions

| # | Prediction | What rejects it |
|---|---|---|
| **P1** | run through the CLI, the 40 labelled sessions reproduce **precision 0.9286 and recall 1.0000** exactly | any other figure — the wiring changed the verdict |
| **P2** | with the flag off, the JSON report is **byte-identical** to the current build on the same trace | any difference |
| **P3** | **exactly one** API call per analysed trace, counted at the client | any trace with 0 or 2+ |
| **P4** | with no `ANTHROPIC_API_KEY`, `analyze --verification` **exits 0** and the report says not judged | a non-zero exit, a crash, or the words "not verified" |
| **P5** | parse failures on the 40 stay at **1 or fewer** | 2 or more |

P1 is the one this document exists to protect: the axis has a published
precision and shipping must not silently produce a different one.

## 7. What would make this fail

- **P1 misses**: stop. A shipped axis whose numbers differ from its published
  ones has no measurement behind it.
- **P2 misses**: stop. An opt-in feature that changes the default output is not
  opt-in.
- **P3 misses**: stop. The cost claim in §4 is the basis for the default being
  cheap to turn on.
- **P4 misses**: stop, and this one is not negotiable. Telling a user who has
  no key that they did not verify their work is the failure mode §3 exists to
  prevent.
- **P5 misses**: not a stop; reported, with the failures shown as "not judged".

## 8. Order of work

1. This document, merged, before the wiring. (rule 8)
2. The wiring and the report section, as its own commit, with tests for §3's
   three outcomes and §4's call cap.
3. P1–P5 measured on the 40 labelled sessions and published whether they pass
   or not.
4. Only then is the flag documented in the README, and only with the cost per
   session next to it.
