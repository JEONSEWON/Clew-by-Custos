# Labelling rubric — live alert confirmed pairs

Committed **before any label is assigned**, per
[`LIVE_FAILURE_ALERT_LABELLING_AMENDMENT_PREREG.md`](../LIVE_FAILURE_ALERT_LABELLING_AMENDMENT_PREREG.md)
§7 step 3. The sample and its seed are frozen in
`field_test/diagnostics/_live_alert_label_sample.json`.

---

## 1. What is being judged

One **confirmed pair**: the same tool called twice with the same normalized
input, whose outputs were byte-identical. The detector has already established
all of that. The label answers only:

> **Was the second call wasted work?**

`true` = wasted. That is the finding, and precision counts these.

## 2. What makes it wasted

The second call **told the agent nothing the first call had not already told
it**, and the agent had no reason to expect otherwise.

## 3. What makes it not wasted, even though the outputs matched

These are the cases the label exists to separate, and every one of them appears
in the pool:

**a. Something happened in between that could have changed the answer.**
Re-reading a file after editing it is a check, not a repeat, even when the edit
turned out to be a no-op and the bytes came back the same. The agent could not
know that in advance.

**b. The call is a state assertion, not a question.** `Stop-Process` on a port
that may or may not be listening returns `stopped` whether or not anything was
running. Called twice at minute 220 and minute 336, it is idempotent
housekeeping, not a repeated lookup. The identical output is the *point* of the
command, not evidence of waste.

**c. Time passed and the thing being read is expected to change.** Polling a
log, a build status, or a running server. Getting the same answer twice is the
information.

**d. A different agent or a different subtask made the call.** The second
caller did not have the first one's result.

## 4. How to decide

Read the input, the output, and the tool indices. Then ask, in order:

1. **Could anything between the two calls have changed the answer?** If yes →
   `false`. This covers (a) and (c).
2. **Is the command asserting a state rather than asking a question?** If yes →
   `false`. This covers (b).
3. **Otherwise** → `true`.

If a pair cannot be decided from what the trace shows, label it `null` and say
why. **A `null` is dropped from precision and counted in the results**; it is
not silently resolved either way. Guessing to fill the sample is how a
labelling exercise measures the labeller.

## 5. What the label is not

- **Not a judgement about the agent's competence.** A defensible re-read is
  `false` even if a smarter agent would have cached.
- **Not about cost.** A 29 KB duplicate and a 7-byte duplicate are labelled the
  same way. Cost is reported separately.
- **Not about whether an alert should fire.** That is what precision decides,
  and pre-deciding it here would make the measurement circular.

## 6. Order

Labels for all 30 are written and committed in one commit. Precision is
computed in a later commit. The two are separated so the commit graph shows the
labels could not have been adjusted after seeing the number — the same route
`unverified_edit` used, where the rule died at 0.3250 against labels that had
been committed first.
