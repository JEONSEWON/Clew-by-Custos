# Live Alert Delivery Retry — Results

Answers `LIVE_ALERT_DELIVERY_RETRY_AMENDMENT_PREREG.md`. Measured 2026-09-01,
before the allow-list row exists, per its §7 step 2.

## 0. Verdict

**R1, R2, R4, R5, R6, R7 pass. R3 passes in its client half and stays open in
its server half**, because counting mails needs email mode and nothing is
switched on. Nothing here is a reason not to proceed to §7 step 3.

## 1. What was measured, and against what

Two layers, deliberately:

- **Unit**, with the opener replaced, so the branches can be driven —
  including the ones a live server will not produce on demand (a transport
  failure mid-pass, a malformed `projects.yaml`).
- **Live**, against `jeonsewon--boxdawn-analyzer-web.modal.run`, so the chain
  is measured end to end: ledger → per-project key → POST → the server's answer
  → the flag persisted.

Suite: **977 passed, 1 xfailed, ruff clean** (`PYTHONPATH=src`, 962 before).

## 2. Predictions

| # | Prediction | Result |
|---|---|---|
| **R1** | a failed send is offered again next sweep, `delivered` still false | **PASS** — live: unreachable endpoint → `URLError`, flag false; next pass → delivered true |
| **R2** | `already_recorded` marks delivered and is never offered again | **PASS** — live: `{"ok":true,"recorded":false,"reason":"already_recorded"}` → delivered; the next drain attempted 0 |
| **R3** | two POSTs for one `(session, signal)` produce **one** mail | **client half PASS** — the retry sends byte-identical payloads, so the server sees one key. **Server half OPEN** — mails cannot be counted in shadow; the second POST demonstrably writes no row |
| **R4** | with delivery off, nothing is attempted and nothing is flipped | **PASS** — live: `attempted=0 pending=1 last=disabled`, zero requests |
| **R5** | each finding goes under its own project's key; no key → not sent | **PASS** — `project_keys()` resolves 3 projects; the unkeyed project is `no_project_key`, **not attempted** |
| **R6** | the log line carries `pending=N`, non-zero exactly when undelivered | **PASS** — shipped line: `projects=3 live=2 recorded=0 capped=0 sent=0 pending=0 findings=0 2.0s` |
| **R7** | `live.py` still does not import `live_send` | **PASS** — and the guard was widened; see §4 |

## 3. The live pass, verbatim

```
project_keys(): ['detector', 'shop', 'web']  (3 with a key)

delivery OFF            DrainResult(attempted=0, delivered=0, pending=1, last_reason='disabled')
delivery ON, first      DrainResult(attempted=1, delivered=1, pending=0, last_reason='')
again                   DrainResult(attempted=0, delivered=0, pending=0, last_reason='')
project with no key     DrainResult(attempted=0, delivered=0, pending=1, last_reason='no_project_key')
unreachable endpoint    DrainResult(attempted=1, delivered=0, pending=1, last_reason='URLError')
then the real one       DrainResult(attempted=1, delivered=1, pending=0, last_reason='')
```

A temporary ledger, never `~/.clew/live_findings.json`. The row it wrote is
`alert_event` with `params_key = 180dbc21b859c6807bc67b1e2c7575cc`
(session `probe-retry-drain-20260901.jsonl`), `delivery_mode = shadow`. That row
and `params_key = 'probe-retry-dryrun-20260901-0001'` are probes and must be
excluded from any finding or label count.

## 4. Eleven mutations, each caught

One change at a time, the named test required to go red, the file restored
after. This is the part that says the guards are guards.

| Mutation | Caught by |
|---|---|
| a finding is marked delivered whether or not it landed | `test_a_failed_send_is_offered_again` |
| `already_recorded` is treated as a failure | `test_already_recorded_counts_as_delivered` |
| the flag is not checked, so shadow sends | `test_with_delivery_off_nothing_is_attempted` |
| every finding goes under one key | `test_each_finding_goes_under_its_own_projects_key` |
| a project with no key falls back to the global credential | `test_a_finding_whose_project_has_no_key_is_not_sent` |
| the ledger is not written, so what landed is forgotten | `test_a_partial_pass_keeps_what_landed` |
| an unreadable `projects.yaml` loses the pass | `test_an_unreadable_projects_file_loses_nothing` |
| the cycle hook is never called | `test_watch_runs_the_cycle_hook_after_writing_the_ledger` |
| the hook runs **before** the ledger is written | same test |
| the log line drops the backlog | `test_the_log_line_carries_the_backlog` |
| the log line always carries a reason | `test_a_quiet_run_says_pending_zero_and_no_reason` |

★ The existing no-send guard would **not** have caught a regression here. It
collects top-level module names from `live.py`'s AST, so
`from clew.live_send import drain` registers as `clew` and passes. A second
assertion now requires the string `live_send` to be absent from that file.

## 5. What §0.2 of the amendment was worth

`read_key()` returned `None` on this machine and `send_finding` returned
`no_key`. Had the allow-list row gone in first, as §8 of the original
pre-registration sequenced it, the experiment would have produced **sixty days
of `no_key`** and a results document concluding that live findings cannot be
validated on one machine's traffic — a conclusion about a missing file.

The same shape as the grant incident the day before: a green deploy, a clean
migration, a verify block answering "the functions are there", and a role that
could not call them. **Both were found by making the real call.**

## 6. What is still off

| | |
|---|---|
| `live_alert_allowlist` | **0 rows** — the server sends for no project |
| `alert_rule` for `live_repeat` | **absent** |
| registered task arguments | `-m clew watch --once --auto` — **no `--send`** |

Three independent closures, and §7 step 3 opens them in that order. R3's server
half is measured on the first delivered finding after that.

## 7. Carried

- **R3's mail count.** One finding, one mail, and a retry of the same finding
  producing none. Needs email mode.
- **`mark_live_delivered`** is granted and unexercised: nothing has been
  delivered for it to mark.
- The retry has **no upper bound**. A permanently undeliverable finding is
  attempted once a minute for ever. That is the choice §3 argues for, and the
  log line is what makes it visible. If sixty days of `pending=1 last=http_401`
  ever appears, the answer is to fix the cause, not to add a counter.
