# Monthly submission limit — pre-registration

**Status:** draft, not applied. Written 2026-09-04.
**Scope:** enforcing `plan.max_runs_per_month`, the one plan axis `0017`
deliberately left unenforced.

---

## §0 Why this needs a pre-registration rather than a migration

`0017_plan_limits.sql` created the column and then said, in its own header,
that it would not enforce it:

> 이번에 강제하는 것: 프로젝트 수 · 팀원 수 · 보존일수 기본값.
> **미루는 것: 월 제출량.** 그 지점은 `ingest_run` 이고 지금 실데이터가 흐르는
> 유일한 길이다. 오늘 만든 함수들과 달리 라이브에서 돌고 있어서, 예측을 따로
> 적고 별도 마이그레이션으로 낸다. 섞으면 문제가 났을 때 어느 쪽인지 못 가린다.

Two things have changed since, and both raise the cost of getting it wrong:

1. **It is now the only bound on our own spend.** The verification axis costs
   one Anthropic call per trace, measured at $0.0045 a session
   (`boxdawn-cloud/app.py:682`), and `judge_allowed` gates on plan only — it
   does not count volume. Per-trace cost is bounded (one call,
   `max_tokens=512`, `VIEW_MAX_CHARS = 120_000`); **the monthly total is not
   bounded by anything.**
2. **`enterprise` is `null`**, i.e. unlimited (`0017` §1). Enforcing the
   column as written leaves the top tier structurally unbounded.

---

## §1 🔴 The counting axis is not settled, and the number on screen is the wrong one

`plan_usage` already reports a monthly figure (`0017:122-126`):

```sql
'runs_this_month', jsonb_build_object(
    'used',  (select count(*) from run r join project p on p.id = r.project_id
               where p.org_id = p_org
                 and r.analyzed_at >= date_trunc('month', now())),
    'limit', (select max_runs_per_month from public.plan_limits(p_org)))
```

**That figure must not be the enforcement counter.** `0018_run_upsert.sql`
made `ingest_run` an upsert on `(project_id, trace_id, params_key)`, and its
update clause moves both timestamps:

- `analyzed_at = excluded.analyzed_at` (`0018:153`)
- `received_at = now()` (`0018:152`)

So a run first stored in August and re-submitted in September **moves into
September's count without a row being created**. The existing figure is
therefore *"rows whose latest analysis falls in this month"*, not *"rows
created this month"*.

Why that difference is disqualifying rather than cosmetic: the close rule
re-submits a growing session repeatedly as it grows, and `0018` exists
precisely so that re-submission does not add rows. Enforcing on a counter
that re-submission increments would **penalise the retry path `0018` was
built to enable**, and a single long session could consume a month's quota by
itself.

### 🔴 There are three quantities here, and the live page names the wrong one

Added 2026-09-04 after the web session read its own copy. `/app/plan` labels
this figure **"Uploads this month" / "이번 달 업로드"**. Three different
quantities are in play and no two of them are equal:

| | Quantity | Counted by |
|---|---|---|
| (a) | **Uploads** — submissions accepted | **nothing.** No table records it |
| (b) | Distinct traces whose latest analysis is this month | `plan_usage` today — and this is what the page calls "uploads" |
| (c) | Rows created this month | nothing yet; §1.1 adds it |

Because `run` is unique on `(project_id, trace_id, params_key)`, a user who
uploads the same trace five times in one month sees **"Uploads this month:
1"**. The label is wrong today, independently of enforcement.

**And the migration makes the label worse, not better.** Switching
`plan_usage` to `created_at` moves the figure from (b) to (c), which is
*smaller*:

| | today (`analyzed_at`) | after (`created_at`) |
|---|---|---|
| same trace uploaded 5× in September | 1 | 1 |
| August run re-submitted in September | **September +1** | September +0 |

⚠️ **So "re-submission is not counted" is false today and true only after the
migration.** Within one month it already holds (the row exists, so the count
does not move). Across months it does *not* hold — re-submitting an August
run moves its `analyzed_at` into September and the September figure goes up
by one, with no row created.

⇒ Copy that says re-submission does not count **must not ship before the
migration.** It would be accurate for the same-month case and wrong for the
cross-month case, which is the case a growing session at a month boundary
actually hits.

### The column needed does not exist

`run` has `id bigserial`, `analyzed_at`, `received_at` (`0001:99-111`).
`analyzed_at` and `received_at` both move on upsert. **Nothing records row
creation.** So the enforcement counter requires a new immutable column.

**Frozen decision (§1.1):** add `run.created_at timestamptz not null default
now()`, and **do not** include it in the upsert's `do update set`.

**Frozen decision (§1.2):** existing rows are backfilled from `received_at`.
This is knowingly wrong for any row that has been re-submitted — for those,
`received_at` is the last submission, not the first. The error is accepted and
recorded here rather than hidden, on three grounds: it is one-time, it can
only *overcount* the current month (never under-count, so it cannot let
someone past their limit), and no source for the true value exists. The
verify block reports how many rows are affected so the size of the error is
on the record rather than assumed.

---

## §2 What consumes quota

**Frozen:** a submission consumes quota **iff it creates a `run` row.**

`ingest_run` cannot learn this from `xmax` in time — `(xmax = 0)` is only
known after the insert (`0018:175`). So the check reads the unique key first:

```
if a row already exists for (p_project, trace_id, params_key)
   -> update path, no quota check, always allowed
else
   -> new row, apply the limit
```

**Frozen:** the refusal reuses the shape `ingest_run` already returns for its
existing rejection (`0018:101`):

```json
{"stored": false, "reason": "monthly_limit_reached"}
```

Not an exception, and not a silent accept. A silent accept would make the
limit invisible, which is the failure this repo keeps finding; an exception
loses the reason, and the reason is what the CLI has to print.

**Frozen:** `null` limit means unlimited, never zero. Same rule `0017` §1
already states, restated because inverting it is a live-path outage.

### 🔴 §2.1 The rule is per (trace × parameters), not per trace — and a release resets it

Added 2026-09-04, found by multiplying a fact the web session supplied with
the rule above. Neither of us had it alone.

`params_key` is a generated stored column
(`0001:117`):

```
md5(phi::text || ':' || n_window::text || ':' || embed_model || ':' || analyzer_version)
```

**`analyzer_version` is inside it**, and `params_key` is part of the conflict
target `(project_id, trace_id, params_key)`. The four fields that feed it are
in `ingest_run`'s INSERT list and **absent from its `do update set`** —
necessarily, since changing them would change the key being matched on.

⇒ **Re-submitting the same trace after a release does not conflict. It
inserts.** So it creates a row, so by the rule above it consumes quota.

And this is the automatic path, not an operator mistake. `submit` re-sends a
session when it has new content (`submit.py:280`, `_unsent(entry) or
_has_new_content(p, entry)`), and the ledger is keyed on file path with a
`sends` counter. A session that is submitted, grows, and is submitted again
**with a release in between** produces two rows for one trace.

**That is correct behaviour, not a defect.** `params_key` is the
comparability guard (`0001:112`): measurements from two analyzer versions must
not be summed, so two rows is what the schema is for, and the second analysis
is genuinely new work with real cost — new compute, and a second verification
call. Quota consumption is the honest outcome.

**What it changes is the sentence.** `0018`'s "re-submission does not add
rows" holds **only within one analyzer version**. So:

| statement | true when |
|---|---|
| "the same trace uploaded twice is counted once" | same version, same month |
| "re-submission does not count" | after §1.1 lands — **and only within a version** |
| "a re-analysis after an upgrade counts again" | **always, and this one survives the migration** |

⚠️ The third row is the durable qualifier. `created_at` fixes the cross-month
case; **nothing fixes the cross-version case, because it is not broken.** Copy
that says re-submission never counts is false the first time a user upgrades
mid-session, which given a release cadence of 0.5.4 → 0.5.10 inside one week
is not a corner case.

**Frozen:** the limit is not adjusted to compensate. A version boundary
producing a second row is a second measurement that cost us a second call;
charging for it is the accurate behaviour, and hiding it inside a larger quota
would make the number mean something else.

---

## §3 The boundary

**Frozen:** the period is `date_trunc('month', now())` in the database's time
zone, matching `plan_usage` today. **Not** a rolling 30 days, and **not**
KST.

Stated because it is a user-visible cut: an org that exhausts its quota is
refused until the boundary, and "which midnight" is a support question. It is
written here so the answer is the same one the code gives.

**Verified 2026-09-05:** `show timezone` on the production instance returns
`UTC`. The assumption this document refused to make turned out to be the
measurement, so the boundary stands as frozen and no re-decision is needed.

★ In the time zone the support question arrives in, that boundary is **09:00
KST on the 1st**, not KST midnight. A KST user between 00:00 and 09:00 on the
1st is still inside the previous period, and a run they submit then counts
against the month that appears to have ended.

Consequence for copy: **"매월 1일" alone is false for nine hours of that day.**
Any user-facing sentence naming the reset must name the hour with it. That is
the sentence the web session was waiting on before writing the plan page.

---

## §4 `enterprise` — the tier that enforcement does not reach

`0017` seeds `('enterprise', 'Enterprise', null, null, null, 365, 30)`. With
`max_runs_per_month = null`, enforcement is a no-op for that tier, so **our
per-trace spend stays unbounded on the top plan** even after this ships.

**Frozen:** this document does **not** set an enterprise number. That is a
commercial decision, not a technical one. What it does fix is that the gap is
named: **enforcement is not a cost bound until `enterprise` carries a
number**, and any claim that our spend is capped is false while it is `null`.

The marketing session has already moved the deck's enterprise row from
"무제한" to "계약", which is consistent with leaving it `null` here.

---

## §5 Predictions (to be checked by dry-run before anything is applied)

Pre-registered so the dry-run can falsify them. Recorded before the queries
are run.

| | Prediction |
|---|---|
| **P1** | No org is currently over its limit. Enforcement refuses **0** submissions on today's data. |
| **P2** | The single live org is on `pro` (limit 2000) and its current month's runs are **< 200**, i.e. under 10% of the limit. |
| **P3** | The `created_at` backfill affects a minority of rows: fewer than **20%** of `run` rows have `received_at` in a different calendar month from the month they were created. Unfalsifiable per-row (no source), so measured as its upper bound — see the query below. |
| **P4** | Every `run` row gets a non-null `created_at` from the backfill; **0** rows end up null. |

**P1 is the gate.** If enforcement would refuse anything today, this must not
ship as written — a limit that starts by rejecting live traffic is a
regression, not a control, and the number has to be revisited first.

### Dry-run queries

Read-only. To be run before the migration is written.

```sql
-- P1 + P2: who is at or over their limit right now
select o.plan_code,
       p2.max_runs_per_month              as lim,
       count(r.id)                        as used_by_analyzed_at,
       count(r.id) filter (where r.received_at >= date_trunc('month', now()))
                                          as used_by_received_at
from org o
join plan p2   on p2.code = o.plan_code
left join project p on p.org_id = o.id
left join run r     on r.project_id = p.id
                   and r.analyzed_at >= date_trunc('month', now())
group by 1, 2;
```

```sql
-- P3 upper bound: rows whose two timestamps sit in different months.
-- Not the same question as "has been re-submitted" -- it is the largest set
-- the backfill error can live in.
select count(*) as rows_total,
       count(*) filter (
         where date_trunc('month', received_at)
            <> date_trunc('month', analyzed_at)) as months_disagree
from run;
```

---

## §5.1 Dry-run results — 2026-09-04, all four predictions hold

Run against production before anything was applied. Recorded here rather than
in a separate file so the prediction and its outcome cannot drift apart.

```
plan_code | lim  | used_by_analyzed_at | used_by_received_at
pro       | 2000 | 24                  | 24

rows_total | months_disagree
105        | 0
```

| | Prediction | Measured | |
|---|---|---|---|
| **P1** | 0 submissions refused | `24 / 2000` → **0** | **pass — gate open** |
| **P2** | `pro`, under 200 | `pro`, **24** (1.2% of limit) | pass |
| **P3** | under 20% disagree | **0 / 105 = 0%** | pass |
| **P4** | 0 rows end up null | follows from P3 | pass |

### ★ P3 came in stronger than predicted, which changes §1.2

`months_disagree = 0` means **no stored row has `received_at` and
`analyzed_at` in different calendar months.** The backfill in §1.2 was
registered as a knowingly-wrong value that could only overcount; on today's
data it is **exact on the monthly axis for all 105 rows**, which is the only
axis the limit uses.

§1.2 is **not** relaxed on that basis. The error is zero *for the rows that
exist now*, and the migration may be applied later than today. The verify
block still reports the affected count, and if it is non-zero at apply time
the §1.2 reasoning is what covers it. What changes is the expectation, not
the guard.

### Two facts worth carrying forward

- **The whole production `run` table is 105 rows.** Any figure derived from
  it is derived from 105 rows, and a percentage of 105 is not a stable
  percentage. Cite the count, not the ratio.
- **The two time axes agree this month** (24 = 24). So the label defect in §1
  is not currently *also* a numeric defect — the mislabelled figure happens to
  equal the number of rows created this month. That coincidence is what makes
  the label safe to fix before the counter, and it will not survive the first
  cross-month re-submission.

---

## §6 🔴 Ordering — the copy goes before the switch

`/app/plan` is live and currently says, in the user's own language, that the
number is **not** enforced ("지금은 그 수를 넘겨도 업로드가 막히지 않습니다").
Enforcing first makes that page false, and a page that is false about a limit
is worse than a page with no limit on it.

This is the same shape as the judge switch and `/privacy`, where the web
session's rule was adopted after a key was deployed ahead of the copy and the
page lied for about an hour. The rule is the same here:

> **Do not enforce until the web session has confirmed the new `/app/plan`
> copy is live.** This is trigger 6 in the release notification contract, and
> it is notified in advance rather than at release.

Web first is harmless: the page can describe a limit before the limit bites,
and the copy is the only thing a user can act on.

**Frozen order:**

1. Dry-run §5, check P1–P4
2. Notify the web session (trigger 6) with the frozen answers from §1–§4
3. Web fixes the **label** first — the figure is (b), not (a), and is wrong
   today regardless of this document. This copy must not yet claim that
   re-submission is uncounted; that is only true after step 5.
4. Web ships the **enforcement** copy on top of the corrected label, confirms
   live. Writing it on the old label puts a true sentence on a false axis.
5. Migration: `run.created_at`, backfill, `ingest_run` check, `plan_usage`
   switched to the new column
6. Web may then state that re-submission does not count — it becomes true at
   step 5 and not before
7. Verify block reports refusals-that-would-have-happened as 0 (P1)

---

## §7 What this does not do

- **Does not bound our spend.** §4: `enterprise` is `null`. Enforcement caps
  the tiers that already have numbers and nothing else.
- **Does not cap per-org cost, only volume.** A trace's analysis cost varies
  (compute) though the judge call is one per trace. Volume is a proxy, chosen
  because it is the axis the plan table already carries.
- **Does not touch `--llm-judge`.** The server does not run it
  (`app.py` has no such flag), so it contributes nothing to our spend today.
- **Does not change what the analyzer measures.** Storage-side only; no
  detector, no threshold, no report field.
