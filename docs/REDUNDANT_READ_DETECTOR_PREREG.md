# Redundant Read Detector — Pre-registration

**Status.** Pre-registration. Per `feedback_rule_8`, this document is pushed
and PR-opened before any production code change lands. Frozen positions
below are pre-committed; adjusting them after seeing implementation
results is not allowed.

## 0. Relationship to prior work (honesty preface)

`docs/REREAD_DETECTOR_PREREG.md` (v0.3.0) exists and specifies file-reread
detection **integrated into cascade** for Claude Code JSONL traces only.
It gates the existing `find_repeat_candidates` output with (a) no
intervening write on the same path, (b) no Bash/PowerShell in the
interval, (c) sha256 output equality.

That v0.3.0 approach bundles reread waste into the general cascade
`waste_cost` — there is no separable "redundant read" line item, and
cross-adapter support (OpenInference, Toolathlon, RB) is out of its scope.

This prereg specifies a **standalone Redundant Read Detector** that:

1. Emits its own `RedundantReadResult` with per-event tokens and dollars.
2. Contributes a distinct `detector_breakdown["redundant_read"]` entry in
   the `TraceCostSummary` (Cost Attribution Completion prereg §5).
3. Works cross-adapter (Claude Code, OpenInference, Toolathlon).
4. Reuses the existing tool-name taxonomy from `report/_enrich.py`
   (`_IDEMPOTENT_TOOLS`, `_SIDE_EFFECT_TOOLS`, `_BW_SIDE_EFFECT_TOOLS`) to
   avoid a divergent mapping.

The v0.3.0 cascade integration is not removed by this prereg. Both paths
coexist: cascade continues detecting exact-output duplicate tool calls
generally, and this detector adds a specific reread-focused line.

## 1. Detection definition (deterministic)

A **redundant read event** is emitted when all four hold on a trace's
tool spans:

1. **Read-tool signal.** Both spans A and B have
   `span_kind == "tool"` and `agent_or_node_id` in the frozen
   `_READ_TOOLS` set (§2).
2. **Same target.** `target(A) == target(B)` after normalization
   (§3). `None` targets are excluded (cannot verify identity).
3. **Ordered.** `A.start_time < B.start_time` (`A` is origin, `B` is
   the redundant candidate).
4. **Interval clean.** Between `A.end_time` and `B.start_time`, no
   tool span exists such that:
   - `agent_or_node_id` in `_WRITE_TOOLS` targeting the same target, OR
   - `agent_or_node_id` in `_SHELL_TOOLS` (payload-opaque, conservative).

When all four hold, `B` is flagged as redundant with origin `A`.

**Same-AGENT parent gate:** existing SPEC §16 gate — if `A` and `B`
have different nearest-AGENT ancestors, exclude the pair. Reuses the
existing `_nearest_agent_ancestor_id` helper from `structural.py`.

**Output-identity confirmation (optional strengthening):** if
`sha256(A.output_text) == sha256(B.output_text)`, mark the event
`confirmed=True`. Otherwise `confirmed=False` (the state we observed
didn't change, but the outputs differ — could be non-deterministic
formatting or timestamp noise). Both are counted; the flag surfaces to
the report for user judgment.

## 2. Frozen tool-name sets

**_READ_TOOLS** (v1 frozen) — tools whose primary side effect is
returning content, not mutating state:

Reuses `_IDEMPOTENT_TOOLS` from `report/_enrich.py` **filtered to
read-nature entries**. Specifically excluded from _READ_TOOLS even
though they are idempotent:

- `local-claim_done` (declarative marker, not a read)
- `filesystem-create_directory` (state-changing but no-op on
  second call — not a read)

Included from `_IDEMPOTENT_TOOLS` (frozen v1 subset):

```
Read, Grep, Glob, LS, NotebookRead,
filesystem-read_file, filesystem-list_directory,
filesystem-list_allowed_directories, filesystem-search_files,
filesystem-get_file_info, filesystem-read_multiple_files,
github-get_file_contents, github-list_commits, github-get_issue,
github-get_commit, github-search_code, github-search_issues,
github-search_repositories, github-list_files, github-list_issues,
github-list_pull_requests, github-get_pull_request,
github-list_branches, github-get_repository,
github-get_pull_request_files, github-get_pull_request_reviews,
github-list_repositories, github-list_organization_repositories,
pdf-tools-read_pdf_pages, pdf-tools-get_pdf_info,
pdf-tools-search_pdf_content, pdf-tools-extract_tables,
pdf-tools-summarize_pdf,
excel-read_data_from_excel, excel-get_workbook_metadata,
excel-list_sheets,
snowflake-read_query,
fetch-fetch_html, fetch-fetch_json, fetch-fetch,
emails-read_email, emails-search_emails, emails-list_emails,
notion-API-post-search, notion-API-get-database,
notion-API-get-page, notion-API-get-block-children,
notion-API-get-users, notion-API-retrieve-database,
notion-API-retrieve-page,
word-read_document, word-get_document_info,
pptx-extract_presentation_text, pptx-get_presentation_info,
pptx-list_slides,
google_sheet-get_sheet_data, google_sheet-list_spreadsheets,
google-cloud-bigquery_list_datasets,
google-cloud-bigquery_get_dataset_info,
google-cloud-bigquery_list_tables,
google-cloud-bigquery_get_table,
k8s-kubectl_get, k8s-kubectl_describe, k8s-kubectl_logs,
canvas-canvas_list_account_users, canvas-canvas_list_courses,
canvas-canvas_list_assignments, canvas-canvas_list_submissions,
canvas-canvas_list_enrollments, canvas-canvas_get_course,
canvas-canvas_get_assignment, canvas-canvas_get_submission,
canvas-canvas_get_user, canvas-canvas_list_quizzes,
yahoo-finance-get_stock_price_by_date,
yahoo-finance-get_historical_stock_prices,
yahoo-finance-get_holder_info, yahoo-finance-get_stock_info,
yahoo-finance-get_dividends, yahoo-finance-get_financials,
yahoo-finance-get_recommendations,
local-web_search, local-search_overlong_tooloutput,
local-view_overlong_tooloutput,
local-view_overlong_tooloutput_navigate,
google_map-maps_geocode, google_map-maps_search_places,
google_map-maps_directions, google_map-maps_reverse_geocode,
playwright_with_chunk-browser_snapshot,
playwright_with_chunk-browser_snapshot_search,
playwright_with_chunk-browser_snapshot_navigate_to_next_span,
playwright_with_chunk-browser_snapshot_navigate_to_span,
playwright_with_chunk-browser_wait_for,
woocommerce-woo_products_list, woocommerce-woo_orders_list,
rail_12306-get-tickets, rail_12306-get-stations,
rail_12306-get-station-info, rail_12306-station-by-code,
rail_12306-station-by-name,
wandb-query_wandb_tool
```

**_WRITE_TOOLS** — reuses `_BW_SIDE_EFFECT_TOOLS` from
`report/_enrich.py` (already covers all known state-changing tools).

**_SHELL_TOOLS** (frozen v1): `{"Bash", "PowerShell",
"terminal-run_command", "local-python-execute"}`. These are excluded
from `_WRITE_TOOLS` because their side effect depends on payload
(command text), and payload-content classification is out of scope.

**User-tool extension (Phase 2 hook):** when `ResolvedTools` from
`clew.yaml` is provided, user-registered idempotent tools with
`kind == "read"` are added to `_READ_TOOLS`; user-registered
side-effect tools are added to `_WRITE_TOOLS`. This mirrors the
existing extension mechanism in `_enrich.py` and does not require any
new user-config field.

## 3. Target extraction (frozen)

Priority per read tool (first match wins):

1. **Path-like key** in parsed `input_text` JSON — first non-empty of
   `{file_path, notebook_path, path, filepath}`. Normalized via
   `os.path.normpath(path).casefold()`.
2. **URL** for fetch tools — first non-empty of `{url, uri, endpoint}`.
   Lowercased, trailing slash stripped.
3. **Query hash** for search/list tools — `sha256(json.dumps(input,
   sort_keys=True))` of the entire parsed input. Deterministic.
4. **Fallback** — `None`. Pair excluded from redundant-read counting.

If `input_text` fails `json.loads`, target is `None` (excluded).

Symlink resolution, mount-point normalization, and case-sensitive
filesystems are out of scope for v1 (§8).

## 4. Cost quantification

The waste from a redundant read is estimated as the cost the LLM will
pay to re-consume the tool output in a subsequent turn:

```
waste_tokens = tiktoken_len(B.output_text)  # or char/4 fallback
waste_cost   = waste_tokens × next_turn_input_rate
```

**next_turn_input_rate resolution:**

- Locate the next LLM call after `B.end_time` in
  `trace.metadata["llm_calls"]`.
- Use tier-aware pricing per Cost Attribution Completion prereg §4:
  - If tier-split fields available, use effective per-token rate
    (weighted average across uncached / cache_read / cache_write).
  - Else, use pricing.py base_input rate for the resolved model.
- If no next LLM call exists (redundant read at end of trace), use the
  most-recent LLM call's rate (retrospective attribution).
- If no LLM calls in trace, use pricing.py default model rate.

**Determinism:** all inputs (tokenizer output, provider rates,
model resolution) are deterministic; the same trace produces the same
`RedundantReadResult` bit-for-bit.

**`cost_accuracy_flag`:** `"accurate"` iff every event's rate resolution
used tier-aware or explicit input_cost_rate; `"estimated"` otherwise.

## 5. Detector interface

New file: `src/clew/detect/redundant_read.py`.

```python
CostAccuracy = Literal["accurate", "estimated"]

@dataclass
class RedundantReadEvent:
    read_span_id: str
    origin_read_span_id: str
    tool_name: str
    target: str
    waste_tokens: int
    waste_cost: float
    confirmed: bool  # True iff sha256(output_a) == sha256(output_b)

@dataclass
class RedundantReadResult:
    trace_id: str
    events: list[RedundantReadEvent] = field(default_factory=list)
    total_waste_tokens: int = 0
    total_waste_cost: float = 0.0
    cost_accuracy_flag: CostAccuracy = "accurate"

def find_redundant_reads(
    trace: Trace,
    *,
    tools: "ResolvedTools | None" = None,
) -> RedundantReadResult: ...
```

**No label imports.** The detector does not read the eval or dev set
directory (matches the leakage-guard convention of `detect/__init__.py`).

## 6. Report integration

**`TraceCostSummary.detector_breakdown`** gains a
`"redundant_read"` entry when this detector runs and reports non-zero
waste. Zero-waste result contributes `0.0` (present, honest).

**Markdown:** `report/markdown.py::render_markdown` gains an optional
`redundant_read: RedundantReadResult | None = None` parameter. When
populated with events:

- The top-of-report Cost summary section shows the new breakdown line.
- A new `## Redundant reads` section renders below the Context resend
  section, listing up to 5 top offenders by `waste_cost`.
- Backward compat: `redundant_read=None` produces identical output to
  pre-integration.

**JSON:** `report/json_report.py::render_json` gains the same optional
parameter. Emits a `"redundant_read"` block matching
`RedundantReadResult` shape. Absent (as `None`) when detector wasn't
run.

**CLI (`__main__.py`):** invokes `find_redundant_reads(trace)` after
`find_context_resend(trace)` and passes the result to both renderers.

## 7. Test plan

### 7.1 Unit tests (`tests/detect/test_redundant_read.py`, new file)

1. `test_two_reads_same_file_no_writes_flagged` — two `Read` calls on
   same path, no intervening write → one event, `confirmed=True`.
2. `test_intervening_write_same_path_skips` — `Read → Write(same path) →
   Read` → zero events (state changed).
3. `test_intervening_write_different_path_no_skip` — `Read(A) →
   Write(B) → Read(A)` → one event.
4. `test_bash_between_conservative_skip` — `Read → Bash → Read` → zero
   events regardless of Bash command content.
5. `test_read_via_fetch_url_normalization` — `fetch-fetch_json(url=X/)`
   and `fetch-fetch_json(url=X)` → one event (trailing slash stripped).
6. `test_search_tool_target_via_query_hash` — two `Grep` calls with
   identical query args → one event.
7. `test_different_agent_parents_excluded` — SPEC §16 gate;
   two-agent traces where reads have different AGENT ancestors → zero
   events.
8. `test_confirmed_flag_when_outputs_differ` — same input, different
   output → event emitted, `confirmed=False`.
9. `test_cost_uses_next_llm_call_rate` — redundant read followed by
   LLM call → `waste_cost` derived from that call's tier-aware rate.
10. `test_deterministic_repeat_run` — running detector twice on same
    trace produces byte-identical result (repr comparison).

### 7.2 Report integration tests (`tests/report/test_redundant_read_report_integration.py`, new file)

1. `test_markdown_backward_compat_when_redundant_read_omitted` — param
   omitted → no new content in output.
2. `test_json_backward_compat_when_redundant_read_omitted` — same for
   JSON.
3. `test_render_markdown_includes_section_with_events` — populated
   result → `## Redundant reads` section present, top offenders listed.
4. `test_render_json_includes_redundant_read_block` — JSON has
   `redundant_read` key with expected shape.
5. `test_cost_summary_breakdown_includes_redundant_read` — populated
   result → `detector_breakdown["redundant_read"]` present in JSON
   `cost_summary`.

### 7.3 Existing test suite must remain green.

New optional parameters default to `None`. No behavior change for
callers that don't pass `redundant_read`.

## 8. Explicitly out of scope for v1

- **Symlink / mount-point resolution.** Two paths that resolve to the
  same file via symlink are treated as different targets.
- **External file modification.** Developer's IDE / CI / cron editing
  files between reads is invisible from the trace; detector cannot
  distinguish "state genuinely unchanged" from "state changed but we
  can't see it".
- **Cross-trace redundancy.** Only in-trace pairs. A session that reads
  the same file across multiple sessions is not detected.
- **Semantic reads.** LLM `describe_file` or "read via chain-of-thought"
  patterns are ignored. Only tools in `_READ_TOOLS`.
- **Auto-remediation.** Detection only. Auto-caching / prevention is
  Phase 2 (SDK) scope.
- **Cost attribution to specific downstream turns.** `waste_cost` is
  computed from the immediate next LLM call's rate, not aggregated
  across all future turns (that is amplification territory —
  `cost/amplification.py`).

## 9. Go/No-go on corpus measurement

After implementation, the detector runs on the 28 Claude Code sessions
(same corpus as Cost Attribution measurement). The pre-committed
decision rule (frozen, matches Context Resend prereg §7 shape):

- **`redundant_read_cost / total_llm_input_cost ≥ 0.10`** on the
  aggregate corpus → detector becomes a **hero-tier report line**
  (surface prominently). Ship in next minor release.
- **`< 0.05`** → **secondary line** (present but not featured). Continue
  shipping but the marketing story stays with context resend + provable
  duplicate.
- **`0.05–0.10`** → **MIXED.** Ships as line item; hero framing decided
  case-by-case per pitch venue.

**Threshold rationale:** context resend was set at 20% (structural
dominance). Redundant reads are a subset of coding-agent work; the SWE-
Pruner arxiv paper reports 76.1% of coding tokens spent on read ops,
but redundant subset unknown. 10% is a defensible hero threshold given
that context.

Random sampling not applicable — all 28 sessions used. Bootstrap CI
computed with `n_boot=1000, seed=42` following the same pattern.

## 10. Backout plan

Additive change. If the detector produces bad results or breaks tests,
revert in one commit — no data migration or schema break to unwind.

## 11. Commit chain (per feedback_rule_8)

1. **This prereg** (`docs/REDUNDANT_READ_DETECTOR_PREREG.md`) — pushed,
   PR opened, URL returned to user. **Stop.**
2. On approval: implementation (`redundant_read.py` + report
   integration + tests). Single commit.
3. Corpus measurement + Go/No-go update in
   `field_test/diagnostics/` (uncommitted). Verification step; not a
   commit.

No squash, no rebase.

## 12. Explicit non-commitments

- No claim that redundant reads will exceed any threshold in the
  measurement — that is the question the measurement answers.
- No claim about how competitor tools (Braintrust, DeepEval, etc.)
  handle this pattern.
- No claim about the Bash-conservative gate's precision — inherited
  from REREAD_DETECTOR_PREREG v0.3.0 §1 with same behavior.
