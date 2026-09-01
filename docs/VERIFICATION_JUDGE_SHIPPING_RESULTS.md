# Shipping the Verification Judge: Results

Measurement against the predictions in
[`VERIFICATION_JUDGE_SHIPPING_PREREG.md`](VERIFICATION_JUDGE_SHIPPING_PREREG.md)
§6, which its §7 requires be published whether it passes or not. Measured
2026-09-01, the same day the pre-registration merged.

**Headline: P1 reproduces exactly — 0.9286 and 1.0000 through the function the
CLI calls, not through the judge directly. P3, P4 and P5 pass. P2 is rejected
on the word "byte-identical": the flag-off report gains one key,
`"verification": {"enabled": false}`, and nothing else.**

| # | Prediction | Result |
|---|---|---|
| **P1** | the 40 labelled sessions reproduce precision 0.9286 and recall 1.0000 exactly | **PASS** · `0.9286` / `1.0000`, equal to the published figures to machine precision |
| **P2** | flag off → JSON byte-identical to the current build | **REJECTED as written** · one key added, every other key equal · see §2 |
| **P3** | exactly one API call per analysed trace | **PASS** · 40 calls for 40 traces |
| **P4** | no `ANTHROPIC_API_KEY` → exit 0 and "not judged" | **PASS** · exit 0, and the reason names the missing key |
| **P5** | parse failures ≤ 1 on the 40 | **PASS** · 1, and it is the same session as before |

Model `claude-haiku-4-5`. 40 calls, **90 seconds**, **$0.1815** — $0.0045 per
session against the $0.0046 the prereg quoted.

## 1. P1: the wiring did not change the answer

The measurement runs `find_verification_failure`, the function `analyze` calls,
over the same 40 sessions and the same committed labels. Not
`VerificationJudge.judge_checked` directly: a wiring that produces a different
number from the one it published has no measurement behind it, and testing the
judge again would not have found that out.

```
precision 0.9286   recall 1.0000   calls 40   not_judged 1   $0.1815   90 s
```

Equal to `VERIFICATION_JUDGE_RESULTS.md` at every digit either document prints.

## 2. P2: rejected on a word, and the word was mine

With the flag off, the JSON gains exactly one key:

```json
"verification": {"enabled": false}
```

Every other key is equal. (The `analyzed` timestamp differs by one second
between the two runs, which is the clock, not the change.)

P2 said **byte-identical**, and one added key is not byte-identical. It is
reported as a miss.

What the prediction was protecting is intact: **an opt-in feature must not
change the default output.** No figure moved, no section appeared in the
markdown, no cost or waste-rate block differs. What it gained is a key that
says the axis was off, which is the same thing the report would otherwise say
by silence — and silence is what a consumer cannot distinguish from an older
build that had no axis at all.

That is an argument for the key, and it is being made **after** seeing the
result, so it does not get to convert the miss into a pass. The prediction
should have said "no existing key changes"; it did not, and the band is not
adjusted afterwards.

## 3. P4: the one that was not negotiable

§7 calls a P4 miss non-negotiable, because telling somebody who has no API key
that they did not verify their work is the failure this axis exists to avoid.

```
$ boxdawn analyze <session> --verification      # no ANTHROPIC_API_KEY

## Verification

- **not judged** — the judge could not start (boxdawn: LLM judge requires
  ANTHROPIC_API_KEY env var (or explicit api_key argument).).
  This is not a finding. It says the axis could not answer, which is a
  different thing from answering no.

exit 0
```

### 3.1 The first run of this check found a real defect

The first attempt printed the right outcome for the wrong reason:

```
- **not judged** — the judge could not start (AnthropicJudge.__init__()
  missing 1 required positional argument: 'model').
```

`VerificationJudge` takes its model explicitly and the call omitted it. Every
run would have been "not judged", forever, and **the test suite could not see
it**: the tests inject a stub judge, so the real constructor was never called.
Seventeen tests passed against a code path that could not work.

It was caught by running the shipped command on a real session. The lesson is
the one this project keeps relearning — a guard that has never failed is a
guard nobody has read — and here the guard was fine while the thing it guarded
was unreachable.

## 4. P5: one parse failure, and it is the same one

One of the 40 does not parse: `code_generation/e20743a3.jsonl`. It is the same
session that failed to parse in the single-axis run on 2026-08-31.

**It surfaces differently now, and that is the point of the shipping work.**
Before, a parse failure became `checked=True` — a non-finding, indistinguishable
from a session that verified its work. Now it is `not judged`, with a reason.
The session is not counted as passing and not counted as failing.

## 5. What is not claimed

- **No new precision.** 0.9286 is the figure from 2026-08-31, reproduced. This
  measurement adds a path, not a corpus, and it is still 40 sessions from one
  generated corpus.
- **Nothing about the other five axes** from the six-question probe. That was a
  cost experiment; none of those axes is wired, labelled, or gated.
- **No stored figure moved.** The axis enters no cost total, no waste rate, no
  `waste_span_count`, and no database column. The JSON's cost and waste-rate
  blocks are equal with the flag on and off.
- **Not on by default**, and the flag is not documented in the README until
  §8 step 4, with the per-session cost beside it.
- **The alert path is untouched.** Whether this axis ever feeds a notification
  is a separate decision, as `VERIFICATION_JUDGE_RESULTS.md` §8 says.
