"""Per-waste-pair enrichment (report-side; cascade/detect unchanged).

Extracts:
- file_path (or command) from candidate.input_text
- origin/candidate turn from trace.metadata["cc_turn_index"]
- pattern_label: "requery" when tool + input matches; else "repeat"
- modified_in_between: any Write/Edit-family span between origin and candidate
  targeting the same file_path (False when file_path unavailable — see uncertain flag)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from clew.detect.structural import find_candidates
from clew.model import Span, Trace
from clew.report._model import WasteDetail

if TYPE_CHECKING:
    from clew.config import ResolvedTools

_EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_FILE_KEYS = ("file_path", "path", "filename", "notebook_path")

# ─────────────────────────────── Category classification ─────────────────────
# Report-side waste labels. Detection is unchanged; this only annotates what
# structural + cascade already picked. See field_test/diagnostics/phase3_classify_waste.py
# for the empirical basis (Toolathlon 8,042 pairs). Categories:
#   error_repeat  — output matches an error pattern
#   side_effect   — a known state-changing tool re-executed
#   idempotent    — a known read-only/declarative/idempotent tool re-executed
#   unclassified  — tool name not in either mapping. Includes Bash/PowerShell,
#                   local-python-execute, terminal-run_command, and
#                   bigquery_run_query: their effect depends on the payload
#                   (command / code / SQL text), never inferred from the name.

_ERROR_RE = re.compile(
    r"(?ix)"
    r"(?:^|[^A-Za-z])error(?:\s|:|\b)|"
    r"error\s+running\s+tool|"
    r"missing\s+required\s+parameter|"
    r"cannot\s+specify\s+both|"
    r"no\s+such\s+file\s+or\s+directory|"
    r"traceback\s*\(most\s+recent|"
    r"exception\s*:|"
    r"^failed\b|"
    r"permission\s+denied|"
    r"\"is_error\"\s*:\s*true|"
    r"\"error\"\s*:\s*true|"
    r"timed?\s*out|"
    r"http\s*[45]\d\d|"
    r"invalid[_ ]request|"
    r"not\s+found\b|"
    r"unauthorized|"
    r"resource\s+not\s+found"
)

_IDEMPOTENT_TOOLS = frozenset({
    # Claude Code (verified read-only)
    "Read", "Grep", "Glob", "LS",
    # Toolathlon — declarative
    "local-claim_done",
    # filesystem-create_directory: state-changing tool, but the second call makes
    # no actual change (directory already exists) — sample [17] hit this 110×.
    "filesystem-create_directory",
    # Toolathlon — filesystem reads
    "filesystem-read_file", "filesystem-list_directory", "filesystem-list_allowed_directories",
    "filesystem-search_files", "filesystem-get_file_info", "filesystem-read_multiple_files",
    # github reads
    "github-get_file_contents", "github-list_commits", "github-get_issue", "github-get_commit",
    "github-search_code", "github-search_issues", "github-search_repositories",
    "github-list_files", "github-list_issues", "github-list_pull_requests",
    "github-get_pull_request", "github-list_branches", "github-get_repository",
    "github-get_pull_request_files", "github-get_pull_request_reviews",
    "github-list_repositories", "github-list_organization_repositories",
    # pdf reads
    "pdf-tools-read_pdf_pages", "pdf-tools-get_pdf_info", "pdf-tools-search_pdf_content",
    "pdf-tools-extract_tables", "pdf-tools-summarize_pdf",
    # excel reads
    "excel-read_data_from_excel", "excel-get_workbook_metadata", "excel-list_sheets",
    # SQL reads
    "snowflake-read_query",
    # BigQuery reads (bigquery_run_query intentionally omitted — SQL can INSERT/UPDATE/DDL)
    "google-cloud-bigquery_list_datasets",
    "google-cloud-bigquery_get_dataset_info", "google-cloud-bigquery_list_tables",
    "google-cloud-bigquery_get_table",
    # google sheets reads
    "google_sheet-get_sheet_data", "google_sheet-list_spreadsheets",
    # k8s reads
    "k8s-kubectl_get", "k8s-kubectl_describe", "k8s-kubectl_logs",
    # yahoo finance (all reads)
    "yahoo-finance-get_stock_price_by_date", "yahoo-finance-get_historical_stock_prices",
    "yahoo-finance-get_holder_info", "yahoo-finance-get_stock_info",
    "yahoo-finance-get_dividends", "yahoo-finance-get_financials",
    "yahoo-finance-get_recommendations",
    # canvas lists / gets
    "canvas-canvas_list_account_users", "canvas-canvas_list_quizzes", "canvas-canvas_list_courses",
    "canvas-canvas_list_assignments", "canvas-canvas_list_submissions",
    "canvas-canvas_list_enrollments", "canvas-canvas_get_course", "canvas-canvas_get_assignment",
    "canvas-canvas_get_submission", "canvas-canvas_get_user",
    # local reads / search
    "local-web_search", "local-search_overlong_tooloutput", "local-view_overlong_tooloutput",
    "local-view_overlong_tooloutput_navigate",
    # fetch
    "fetch-fetch_html", "fetch-fetch_json", "fetch-fetch",
    # emails reads
    "emails-read_email", "emails-search_emails", "emails-list_emails",
    # maps reads
    "google_map-maps_geocode", "google_map-maps_search_places", "google_map-maps_directions",
    "google_map-maps_reverse_geocode",
    # playwright reads (snapshot / query)
    "playwright_with_chunk-browser_snapshot",
    "playwright_with_chunk-browser_snapshot_search",
    "playwright_with_chunk-browser_snapshot_navigate_to_next_span",
    "playwright_with_chunk-browser_snapshot_navigate_to_span",
    "playwright_with_chunk-browser_wait_for",
    # notion reads
    "notion-API-post-search", "notion-API-get-database", "notion-API-get-page",
    "notion-API-get-block-children", "notion-API-get-users",
    "notion-API-retrieve-database", "notion-API-retrieve-page",
    # wandb
    "wandb-query_wandb_tool",
    # woocommerce reads
    "woocommerce-woo_products_list", "woocommerce-woo_orders_list",
    # rail reads
    "rail_12306-get-tickets", "rail_12306-get-stations", "rail_12306-get-station-info",
    "rail_12306-station-by-code", "rail_12306-station-by-name",
    # pptx reads
    "pptx-extract_presentation_text", "pptx-get_presentation_info", "pptx-list_slides",
    # word reads
    "word-read_document", "word-get_document_info",
})

_SIDE_EFFECT_TOOLS = frozenset({
    # Claude Code (verified state-changing)
    "Write", "Edit", "MultiEdit", "NotebookEdit",
    # Toolathlon — filesystem writes/moves/edits (create_directory belongs to idempotent above)
    "filesystem-write_file", "filesystem-edit_file", "filesystem-move_file",
    "filesystem-copy_file", "filesystem-delete_file",
    # github state changes
    "github-create_or_update_file", "github-delete_file", "github-create_issue",
    "github-create_pull_request", "github-update_issue", "github-create_repository",
    "github-add_labels", "github-create_comment", "github-merge_pull_request",
    "github-update_pull_request", "github-create_branch", "github-close_issue",
    "github-add_issue_comment", "github-push_files", "github-fork_repository",
    # emails send
    "emails-send_email", "emails-send", "emails-reply", "emails-forward",
    # SQL write
    "snowflake-write_query",
    # excel writes
    "excel-write_data_to_excel", "excel-add_sheet", "excel-format_cells",
    "excel-delete_sheet", "excel-rename_sheet",
    # word writes
    "word-create_document", "word-add_paragraph", "word-format_text",
    "word-add_heading", "word-add_table", "word-save_document",
    # sheets writes
    "google_sheet-update_cells", "google_sheet-append_values", "google_sheet-clear_range",
    "google_sheet-create_spreadsheet", "google_sheet-add_sheet",
    "google-cloud-logging_write_log",
    # forms
    "google_forms-create_form", "google_forms-add_question",
    # notion writes
    "notion-API-post-page", "notion-API-patch-page", "notion-API-patch-block-children",
    "notion-API-post-database", "notion-API-post-page-property",
    "notion-API-delete-block", "notion-API-post-database-query",
    # woocommerce writes
    "woocommerce-woo_products_update", "woocommerce-woo_products_create",
    "woocommerce-woo_orders_update", "woocommerce-woo_orders_create",
    # canvas state changes
    "canvas-canvas_enroll_user", "canvas-canvas_unenroll_user",
    "canvas-canvas_create_course", "canvas-canvas_update_course", "canvas-canvas_delete_course",
    "canvas-canvas_create_announcement", "canvas-canvas_create_conversation",
    "canvas-canvas_upload_file_from_path", "canvas-canvas_upload_file",
    "canvas-canvas_create_assignment", "canvas-canvas_update_assignment",
    "canvas-canvas_create_quiz", "canvas-canvas_update_quiz",
    "canvas-canvas_create_module", "canvas-canvas_create_page",
    # k8s state changes
    "k8s-kubectl_create", "k8s-kubectl_apply", "k8s-kubectl_delete",
    "k8s-kubectl_replace", "k8s-kubectl_patch", "k8s-kubectl_scale",
    # playwright interactions (state changes)
    "playwright_with_chunk-browser_click", "playwright_with_chunk-browser_type",
    "playwright_with_chunk-browser_navigate", "playwright_with_chunk-browser_press_key",
    "playwright_with_chunk-browser_close", "playwright_with_chunk-browser_scroll",
    "playwright_with_chunk-browser_hover", "playwright_with_chunk-browser_select_option",
    "playwright_with_chunk-browser_fill", "playwright_with_chunk-browser_upload_file",
    "playwright_with_chunk-browser_drag", "playwright_with_chunk-browser_tab_new",
    "playwright_with_chunk-browser_tab_close",
    # rail booking
    "rail_12306-buy-tickets", "rail_12306-book-tickets", "rail_12306-cancel-tickets",
    # pptx writes
    "pptx-open_presentation", "pptx-save_presentation", "pptx-add_slide",
    "pptx-update_slide", "pptx-delete_slide",
})

# ─────────────────────────────── between_window (report-only) ───────────────
# Report-side sub-classification of `idempotent` pairs. Detection unchanged.
# See `field_test/diagnostics/greyzone_expansion_PREREG.md` §1 for the frozen
# rule (Rule V2) and enum definitions.
#
# NOTE — two side-effect sets coexist by design; do NOT unify them:
#   - `_SIDE_EFFECT_TOOLS` above answers: "is THIS call itself a side effect?"
#     Payload-dependent tools (Bash, PowerShell, local-python-execute,
#     terminal-run_command, snowflake-write_query, ...) cannot be classified
#     by name — they stay in the `unclassified` category.
#   - `_BW_SIDE_EFFECT_TOOLS` below answers: "was there anything BETWEEN the
#     two calls that could have changed state?" Payload-dependent tools MIGHT
#     have changed state, so they must be counted conservatively.
# Narrowing `_BW_SIDE_EFFECT_TOOLS` would misroute the payload_dependent
# bucket (405 pairs on Toolathlon) into no_side_effect, breaking §4.1 counts.
# Source of truth: `field_test/diagnostics/greyzone_b_writesplit.py`
# `_SIDE_EFFECT_TOOLS`, plus CC additions per PREREG §1.6.

_BW_DECLARATIVE_TOOLS = frozenset({
    "local-claim_done",
    "filesystem-create_directory",
    # CC: no declarative-marker tool exists (PREREG §1.6 → CC_DECLARATIVE = ∅)
})

_BW_SIDE_EFFECT_TOOLS = frozenset({
    # Toolathlon — mirrors greyzone_b_writesplit.py _SIDE_EFFECT_TOOLS.
    # Includes payload-dependent tools (terminal-run_command, local-python-execute,
    # snowflake-write_query, google-cloud-logging_write_log) — see NOTE above.
    "filesystem-write_file", "filesystem-edit_file", "filesystem-move_file",
    "filesystem-copy_file", "filesystem-delete_file",
    "github-create_or_update_file", "github-delete_file", "github-create_issue",
    "github-create_pull_request", "github-update_issue", "github-create_repository",
    "github-add_labels", "github-create_comment", "github-merge_pull_request",
    "github-update_pull_request", "github-create_branch", "github-close_issue",
    "github-add_issue_comment", "github-push_files", "github-fork_repository",
    "emails-send_email", "emails-send", "emails-reply", "emails-forward",
    "snowflake-write_query",
    "excel-write_data_to_excel", "excel-add_sheet", "excel-format_cells",
    "excel-delete_sheet", "excel-rename_sheet",
    "word-create_document", "word-add_paragraph", "word-format_text",
    "word-add_heading", "word-add_table", "word-save_document",
    "google_sheet-update_cells", "google_sheet-append_values", "google_sheet-clear_range",
    "google_sheet-create_spreadsheet", "google_sheet-add_sheet",
    "google-cloud-logging_write_log",
    "google_forms-create_form", "google_forms-add_question",
    "notion-API-post-page", "notion-API-patch-page", "notion-API-patch-block-children",
    "notion-API-post-database", "notion-API-post-page-property",
    "notion-API-delete-block", "notion-API-post-database-query",
    "woocommerce-woo_products_update", "woocommerce-woo_products_create",
    "woocommerce-woo_orders_update", "woocommerce-woo_orders_create",
    "canvas-canvas_enroll_user", "canvas-canvas_unenroll_user",
    "canvas-canvas_create_course", "canvas-canvas_update_course", "canvas-canvas_delete_course",
    "canvas-canvas_create_announcement", "canvas-canvas_create_conversation",
    "canvas-canvas_upload_file_from_path", "canvas-canvas_upload_file",
    "canvas-canvas_create_assignment", "canvas-canvas_update_assignment",
    "canvas-canvas_create_quiz", "canvas-canvas_update_quiz",
    "canvas-canvas_create_module", "canvas-canvas_create_page",
    "k8s-kubectl_create", "k8s-kubectl_apply", "k8s-kubectl_delete",
    "k8s-kubectl_replace", "k8s-kubectl_patch", "k8s-kubectl_scale",
    "terminal-run_command", "local-python-execute",
    "playwright_with_chunk-browser_click", "playwright_with_chunk-browser_type",
    "playwright_with_chunk-browser_navigate", "playwright_with_chunk-browser_press_key",
    "playwright_with_chunk-browser_close", "playwright_with_chunk-browser_scroll",
    "playwright_with_chunk-browser_hover", "playwright_with_chunk-browser_select_option",
    "playwright_with_chunk-browser_fill", "playwright_with_chunk-browser_upload_file",
    "playwright_with_chunk-browser_drag", "playwright_with_chunk-browser_tab_new",
    "playwright_with_chunk-browser_tab_close",
    "rail_12306-buy-tickets", "rail_12306-book-tickets", "rail_12306-cancel-tickets",
    "pptx-open_presentation", "pptx-save_presentation", "pptx-add_slide",
    "pptx-update_slide", "pptx-delete_slide",
    # CC (PREREG §1.6): Bash/PowerShell live in both sets — payload-dependent
    # AND state-changing. Mirror of Toolathlon's local-python-execute pattern.
    "Edit", "Write", "MultiEdit", "NotebookEdit",
    "Bash", "PowerShell",
})

_BW_BLACKBOX_TOOLS = frozenset({
    # Toolathlon
    "local-python-execute",
    "terminal-run_command",
    "snowflake-write_query",
    "google-cloud-logging_write_log",
    # CC (PREREG §1.6): Bash/PowerShell also in _BW_SIDE_EFFECT_TOOLS above.
    "Bash", "PowerShell",
})

_BW_CONTEXT_LIMIT = 20  # PREREG §1.2 high_volume threshold


def _classify_between_window(
    trace: Trace,
    origin: Span,
    cand: Span,
    tools: "ResolvedTools | None" = None,
) -> str:
    """PREREG §1.3 Rule V2 priority. Only called when category == 'idempotent'.

    Scan window: `origin.end_time < s.start_time < cand.start_time`
    (matches diagnostics `spans_between` exactly — the source of the frozen
    §4.1 counts). Tool spans only.

    `tools` (optional): user-tool resolution from clew.yaml. When None, uses
    built-in frozensets exactly — §3 gate preserves parity.
    """
    bw_decl = _BW_DECLARATIVE_TOOLS if tools is None else tools.bw_declarative
    bw_side = _BW_SIDE_EFFECT_TOOLS if tools is None else tools.bw_side_effect
    bw_bb = _BW_BLACKBOX_TOOLS if tools is None else tools.bw_blackbox

    if cand.agent_or_node_id in bw_decl:
        return "declarative"
    between_tools = [
        s for s in trace.spans
        if s.span_kind == "tool"
        and s.span_id not in (origin.span_id, cand.span_id)
        and origin.end_time < s.start_time < cand.start_time
    ]
    if not any(s.agent_or_node_id in bw_side for s in between_tools):
        return "no_side_effect"
    if len(between_tools) >= _BW_CONTEXT_LIMIT:
        return "high_volume"
    if any(s.agent_or_node_id in bw_bb for s in between_tools):
        return "payload_dependent"
    return "targeted_writes"


def _output_head(text: str, limit: int = 400) -> str:
    """Head of tool output. If JSON-wrapped, unwrap first `text` field (Toolathlon shape)."""
    s = (text or "")[:limit + 200]
    m = re.search(r'"text"\s*:\s*"([^"\\]{0,600}(?:\\.[^"\\]{0,600}){0,5})"', s)
    if m:
        return m.group(1)[:limit]
    return s[:limit]


def _classify_category(cand: Span, tools: "ResolvedTools | None" = None) -> str:
    """Report-side label. Order: error → idempotent → side-effect → unclassified.

    Tool-name based only — never infer effect from name substrings (e.g. "put"
    in "tooloutput" is not a write). Unknown tools and payload-dependent tools
    (Bash, PowerShell, local-python-execute, terminal-run_command,
    bigquery_run_query) stay unclassified.

    `tools` (optional): user-tool resolution from clew.yaml. When None, uses
    built-in frozensets exactly — §3 gate preserves parity.
    """
    if _ERROR_RE.search(_output_head(cand.output_text)):
        return "error_repeat"
    idem = _IDEMPOTENT_TOOLS if tools is None else tools.idempotent
    side = _SIDE_EFFECT_TOOLS if tools is None else tools.side_effect
    name = cand.agent_or_node_id
    if name in idem:
        return "idempotent"
    if name in side:
        return "side_effect"
    return "unclassified"


@dataclass
class EnrichedDetail:
    detail: WasteDetail
    file_path: str | None
    command: str | None
    origin_turn: int | None
    candidate_turn: int | None
    total_turns: int | None
    pattern_label: str
    modified_in_between: bool
    state_change_uncertain: bool  # True when file_path unavailable (e.g. Bash)
    input_summary: str  # fallback display when neither file_path nor command
    category: str  # error_repeat | side_effect | idempotent | unclassified
    between_window: str | None  # PREREG §1.3; set iff category == "idempotent"


@dataclass
class EnrichmentResult:
    """enrich(...) return: kept EnrichedDetails + count skipped due to tool-error gate."""
    enriched: list[EnrichedDetail]
    n_skipped_error: int


def coverage_stats(
    trace: Trace,
    enriched: list["EnrichedDetail"],
    tools: "ResolvedTools | None" = None,
) -> dict:
    """Tool mapping coverage stats for a single trace.

    Definitions (frozen, docs/COVERAGE_TRANSPARENCY_PREREG.md §1.1):
      recognized  = tool name in (_BW_SIDE_EFFECT_TOOLS
                                  ∪ _BW_DECLARATIVE_TOOLS
                                  ∪ _IDEMPOTENT_TOOLS)
      unrecognized = tool name NOT in any of those three lists

    Both counts are over `unique tool NAMES` in the trace's tool-kind spans.

    pairs_with_unrecognized_in_between counts idempotent pairs where at least
    one strictly-between tool-kind span has an unrecognized name.

    unrecognized_tool_names (docs/COVERAGE_BANNER_AMEND_PREREG.md §3.1 / §4):
    full list of unrecognized names sorted by span-occurrence desc,
    alphabetic tie-break (deterministic). Empty list if none.

    When `tools` is not None (clew.yaml loaded), the returned dict also carries
    three provenance counts summing to `recognized_tools`:
      built_in_count, user_count, user_overriding_built_in_count.
    When `tools` is None, those keys are absent — §3 gate preserves parity.
    """
    if tools is None:
        idem = _IDEMPOTENT_TOOLS
        bw_side = _BW_SIDE_EFFECT_TOOLS
        bw_decl = _BW_DECLARATIVE_TOOLS
    else:
        idem = tools.idempotent
        bw_side = tools.bw_side_effect
        bw_decl = tools.bw_declarative

    tool_names = {s.agent_or_node_id for s in trace.spans if s.span_kind == "tool"}
    recognized = {
        t for t in tool_names
        if t in bw_side or t in bw_decl or t in idem
    }
    unrecognized = tool_names - recognized

    unrec_counts: dict[str, int] = {}
    for s in trace.spans:
        if s.span_kind == "tool" and s.agent_or_node_id in unrecognized:
            unrec_counts[s.agent_or_node_id] = unrec_counts.get(s.agent_or_node_id, 0) + 1
    unrecognized_tool_names = sorted(
        unrec_counts.keys(), key=lambda n: (-unrec_counts[n], n)
    )

    idem_total = 0
    pairs_affected = 0
    for ed in enriched:
        if ed.category != "idempotent":
            continue
        idem_total += 1
        o = ed.detail.origin
        c = ed.detail.candidate
        # strict window; matches the rule used elsewhere in this module.
        for s in trace.spans:
            if s.span_kind != "tool":
                continue
            if not (o.end_time <= s.start_time < c.start_time):
                continue
            if s.agent_or_node_id in unrecognized:
                pairs_affected += 1
                break

    stats: dict[str, Any] = {
        "unique_tools_in_trace": len(tool_names),
        "recognized_tools": len(recognized),
        "coverage_ratio": (len(recognized) / len(tool_names)) if tool_names else 1.0,
        "idempotent_pairs_total": idem_total,
        "pairs_with_unrecognized_in_between": pairs_affected,
        "unrecognized_tool_names": unrecognized_tool_names,
    }

    if tools is not None and tools.has_user_tools:
        # §2.5 banner extension: 3-count provenance breakdown for recognized tools.
        # user-overriding-built-in beats plain user (same name).
        override = recognized & tools.override_names
        user_only = (recognized & tools.user_names) - override
        built_in = recognized - tools.user_names
        stats["built_in_count"] = len(built_in)
        stats["user_count"] = len(user_only)
        stats["user_overriding_built_in_count"] = len(override)
        assert (
            stats["built_in_count"]
            + stats["user_count"]
            + stats["user_overriding_built_in_count"]
            == stats["recognized_tools"]
        ), "banner 3-count sum must equal recognized_tools"

    return stats


def _parse_input(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _file_path_of(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    for k in _FILE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _command_of(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    v = obj.get("command")
    return v if isinstance(v, str) and v else None


def _classify_pattern(origin: Span, cand: Span) -> str:
    if origin.span_kind == "tool" and cand.span_kind == "tool":
        if origin.input_text.strip().casefold() == cand.input_text.strip().casefold():
            return "requery"
    if origin.span_kind == "llm" and cand.span_kind == "llm":
        return "pingpong"
    return "repeat"


def _has_intervening_edit(trace: Trace, origin: Span, cand: Span, file_path: str) -> bool:
    for s in trace.spans:
        if s.span_kind != "tool":
            continue
        if s.agent_or_node_id not in _EDIT_TOOLS:
            continue
        if not (origin.start_time < s.start_time < cand.start_time):
            continue
        fp = _file_path_of(_parse_input(s.input_text))
        if fp == file_path:
            return True
    return False


# ─────────────────────────────── ID bridge (report-only) ────────────────────
# Separate axis from cascade waste. Same-input side-effect pairs are scanned
# for entity-ID identity in the two responses. Independent of sha256 gate:
# the pair may be excluded from waste (different responses because different
# entities were created), yet counted here.
#
# Mapping frozen per docs/ID_BRIDGE_PRODUCTION_PREREG.md §1.1 — 26 tools.
# Extractor kinds mirror field_test/diagnostics/id_bridge_scan.py:
#   "path"       — dot-separated JSON key traversal (integers index arrays)
#   "array_path" — same as path; distinct label for readability
#   "regex_url"  — regex applied to the full response body

_ID_BRIDGE_MAPPING: dict[str, tuple[str, str]] = {
    # notion
    "notion-API-post-page":                 ("path",       "id"),
    "notion-API-patch-page":                ("path",       "id"),
    "notion-API-patch-block-children":      ("array_path", "results.0.id"),
    # google
    "google_sheet-create_spreadsheet":      ("path",       "spreadsheetId"),
    "google_forms-create_form":             ("path",       "formId"),
    # github (commit sha)
    "github-create_or_update_file":         ("path",       "commit.sha"),
    "github-delete_file":                   ("path",       "commit.sha"),
    "github-create_branch":                 ("path",       "object.sha"),
    "github-push_files":                    ("path",       "object.sha"),
    "github-merge_pull_request":            ("path",       "sha"),
    "github-add_issue_comment":             ("path",       "id"),
    # github (URL tail)
    "github-create_pull_request":           ("regex_url",  r"/pull/(\d+)"),
    "github-update_issue":                  ("regex_url",  r"/issues/(\d+)"),
    # canvas
    "canvas-canvas_create_course":          ("path",       "id"),
    "canvas-canvas_create_announcement":    ("path",       "id"),
    "canvas-canvas_create_assignment":      ("path",       "id"),
    "canvas-canvas_create_quiz":            ("path",       "id"),
    "canvas-canvas_create_conversation":    ("array_path", "0.id"),
    "canvas-canvas_upload_file_from_path":  ("path",       "id"),
    "canvas-canvas_enroll_user":            ("path",       "id"),
    "canvas-canvas_update_course":          ("path",       "id"),
    "canvas-canvas_update_assignment":      ("path",       "id"),
    "canvas-canvas_update_quiz":            ("path",       "id"),
    # woocommerce
    "woocommerce-woo_products_create":      ("path",       "id"),
    "woocommerce-woo_products_update":      ("path",       "id"),
    "woocommerce-woo_orders_update":        ("path",       "id"),
}


def _unwrap_id_bridge_output(text: str) -> str:
    """Toolathlon envelope unwrap. `{"type":"text","text":"<body>","...":...}`
    is unwrapped once; anything else is returned as-is."""
    if not text:
        return ""
    try:
        outer = json.loads(text)
        if isinstance(outer, dict) and "text" in outer and isinstance(outer["text"], str):
            return outer["text"]
    except Exception:
        pass
    return text


def _dig_id_bridge(obj: Any, path_parts: list[str]) -> Any:
    cur: Any = obj
    for p in path_parts:
        if isinstance(cur, list):
            try:
                cur = cur[int(p)]
            except (ValueError, IndexError, TypeError):
                return None
        elif isinstance(cur, dict):
            if p not in cur:
                return None
            cur = cur[p]
        else:
            return None
    return cur


def extract_entity_id(
    tool: str,
    output_text: str,
    user_entity_id_map: dict[str, str] | None = None,
) -> str | None:
    """Return extracted ID string, or None if the tool is not in either mapping
    or the specific path fails on this response. Deterministic; no LLM.

    Precedence: built-in `_ID_BRIDGE_MAPPING` first, then user-registered
    `user_entity_id_map` (Phase 2). Built-in overlap is prevented at config
    load time (see clew.config.user_tools.resolve_user_tools), so this
    fallback is unambiguous when reached.
    """
    if tool in _ID_BRIDGE_MAPPING:
        kind, spec = _ID_BRIDGE_MAPPING[tool]
    elif user_entity_id_map is not None and tool in user_entity_id_map:
        # User-registered dot-path only (grammar enforced at load time).
        kind, spec = "path", user_entity_id_map[tool]
    else:
        return None
    body = _unwrap_id_bridge_output(output_text)
    if not body:
        return None
    if kind == "regex_url":
        m = re.search(spec, body)
        return m.group(1) if m else None
    try:
        parsed = json.loads(body)
    except Exception:
        return None
    val = _dig_id_bridge(parsed, spec.split("."))
    if val is None:
        return None
    if isinstance(val, (int, float, str)):
        s = str(val).strip()
        if not s or s.lower() in ("null", "none"):
            return None
        return s
    return None


@dataclass
class IdBridgeCandidate:
    origin_span_id: str
    candidate_span_id: str
    tool: str
    verdict: str  # "differ" | "same" | "no_id"
    origin_id: str | None
    candidate_id: str | None
    source: str = "built-in"  # "built-in" | "user"  (Phase 2)


def scan_id_bridge_candidates(
    trace: Trace,
    tools: "ResolvedTools | None" = None,
) -> list[IdBridgeCandidate]:
    """Same-input side-effect pair scan. Independent of cascade.

    Pool = find_candidates(trace, 2) filtered to cand.span_kind == "tool"
    and cand.agent_or_node_id in the side_effect set. For each pair, extract
    IDs from origin and candidate outputs and classify three ways.

    Phase 2: when `tools` is provided, the side_effect set is the user-extended
    frozenset, and each candidate's `source` is set to "built-in" if the tool
    has a built-in ID mapping, else "user". Extraction uses both mappings.

    Does NOT feed waste_span_ids. Does NOT feed between_window_counts.
    Purely additive report layer.
    """
    side_effect_pool = _SIDE_EFFECT_TOOLS if tools is None else tools.side_effect
    user_map = tools.user_entity_id_map if tools is not None else None

    out: list[IdBridgeCandidate] = []
    for origin, cand in find_candidates(trace, 2):
        if cand.span_kind != "tool":
            continue
        tool = cand.agent_or_node_id
        if tool not in side_effect_pool:
            continue
        # Pool = every side_effect tool (matches built-in behavior for tools
        # without an ID mapping — they land as `no_id`). `source` is "user"
        # only when the tool is user-registered AND not in the built-in map;
        # built-in overlap is prevented at config-load time.
        if tool in _ID_BRIDGE_MAPPING:
            source = "built-in"
        elif user_map is not None and tool in user_map:
            source = "user"
        else:
            source = "built-in"  # no ID mapping either side → still built-in bucket
        # Fallback: raw_output_text preserves the pre-preprocess payload for
        # tool spans on the langgraph path (openinference_output_text_fix_PREREG.md §2.2).
        # On CC/Toolathlon/RB paths preprocess is not called so raw is None;
        # in that case output_text is already the untouched adapter output.
        o_id = extract_entity_id(
            tool, origin.raw_output_text or origin.output_text, user_map,
        )
        c_id = extract_entity_id(
            tool, cand.raw_output_text or cand.output_text, user_map,
        )
        if o_id is None or c_id is None:
            verdict = "no_id"
        elif o_id == c_id:
            verdict = "same"
        else:
            verdict = "differ"
        out.append(IdBridgeCandidate(
            origin_span_id=origin.span_id,
            candidate_span_id=cand.span_id,
            tool=tool,
            verdict=verdict,
            origin_id=o_id,
            candidate_id=c_id,
            source=source,
        ))
    return out


def compute_user_extraction_ratios(
    candidates: list[IdBridgeCandidate],
) -> dict[str, tuple[int, int]]:
    """Per-user-tool (failed_extractions, total_extractions).

    An extraction is counted per side of each candidate pair (2 per pair).
    A side is "failed" when extract_entity_id returned None (verdict piece).

    Only tools with `source == "user"` are included.
    """
    stats: dict[str, list[int]] = {}
    for c in candidates:
        if c.source != "user":
            continue
        acc = stats.setdefault(c.tool, [0, 0])
        # Total: 2 extractions per pair (origin + candidate).
        acc[1] += 2
        acc[0] += int(c.origin_id is None) + int(c.candidate_id is None)
    return {tool: (f, t) for tool, (f, t) in stats.items()}


# User-facing messages must NOT reference local docs/*.md paths — pip-install
# users have no docs/ tree. Same constant lives in clew/config/user_tools.py
# as _GITHUB_BASE; consolidation to a shared module (e.g. `clew/_urls.py`) is
# a candidate for a separate refactor commit — this file duplicates locally
# for now to keep the scope of the friction-#7-regression fix minimal.
_GITHUB_BASE = "https://github.com/JEONSEWON/Clew-by-Custos/blob/main"
_FRAMEWORK_EXPANSION_URL = (
    f"{_GITHUB_BASE}/docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md"
)


_ENVELOPE_PREFIX_HINT = (
    "  hint: if your OpenInference instrumentor wraps the return in an "
    "envelope, the path needs the envelope prefix — e.g. LlamaIndex serializes "
    "returns as `{\"blocks\":[...], \"raw_output\":<orig>, ...}`, so a "
    "`ticket.id` path needs to be written as `raw_output.ticket.id`. "
    f"Full context: {_FRAMEWORK_EXPANSION_URL}"
)


def format_extraction_ratios(ratios: dict[str, tuple[int, int]]) -> str | None:
    """Q5 confirmed format. Returns a multi-line string or None (all-success).

    When any tool reports failures, an envelope-prefix hint line is appended
    after the per-tool lines (Tier 1 finding: entity_id path varies by
    OpenInference instrumentor).
    """
    lines: list[str] = []
    for tool, (failed, total) in sorted(ratios.items()):
        if failed == 0:
            continue  # No line — noise reduction.
        if failed == total:
            label = "path likely misconfigured"
        else:
            label = "partial — response variance"
        lines.append(f"  {tool}: {failed}/{total} extractions failed  ({label})")
    if not lines:
        return None
    lines.append(_ENVELOPE_PREFIX_HINT)
    return "clew: entity_id extraction ratios\n" + "\n".join(lines)


def enrich(
    trace: Trace,
    details: list[WasteDetail],
    tools: "ResolvedTools | None" = None,
) -> EnrichmentResult:
    """Enrich WasteDetails; skip pairs whose origin or candidate is an error-response span.

    §29.2 tool-error gate: `trace.metadata["error_span_ids"]` (populated by the CC adapter
    from Anthropic `is_error: true` structural flag) marks tool_result spans that failed.
    Cosine similarity between two "File has not been read yet" outputs is not waste — it's
    tool infrastructure repeatedly emitting the same error. Skips are counted, not silent.

    `tools` (optional): user-tool resolution from clew.yaml. When None, uses
    built-in frozensets exactly — §3 gate preserves parity.
    """
    turn_index: dict[str, int] = trace.metadata.get("cc_turn_index") or {}
    total_turns: int | None = trace.metadata.get("cc_total_turns")
    error_ids: set[str] = set(trace.metadata.get("error_span_ids") or [])
    out: list[EnrichedDetail] = []
    n_skipped_error = 0
    for wd in details:
        o, c = wd.origin, wd.candidate
        if o.span_id in error_ids or c.span_id in error_ids:
            n_skipped_error += 1
            continue
        parsed = _parse_input(c.input_text)
        fp = _file_path_of(parsed)
        cmd = _command_of(parsed)
        pattern = _classify_pattern(o, c)
        modified = _has_intervening_edit(trace, o, c, fp) if fp else False
        uncertain = fp is None  # cannot verify state change without a file target
        summary = fp or cmd or (c.input_text[:60] + ("…" if len(c.input_text) > 60 else ""))
        category = _classify_category(c, tools)
        between_window = (
            _classify_between_window(trace, o, c, tools)
            if category == "idempotent"
            else None
        )
        out.append(EnrichedDetail(
            detail=wd,
            file_path=fp,
            command=cmd,
            origin_turn=turn_index.get(o.span_id),
            candidate_turn=turn_index.get(c.span_id),
            total_turns=total_turns if isinstance(total_turns, int) else None,
            pattern_label=pattern,
            modified_in_between=modified,
            state_change_uncertain=uncertain,
            input_summary=summary,
            category=category,
            between_window=between_window,
        ))
    return EnrichmentResult(enriched=out, n_skipped_error=n_skipped_error)
