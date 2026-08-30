"""src/clew/ingest/claude_code.py - Claude Code JSONL transcript -> Trace.

Mapping convention: docs/CC_TRANSCRIPT.md §22 (pre-registered, finalized after PR approval).

Input: `~/.claude/projects/<slug>/<uuid>.jsonl` (JSONL, one line = one JSON).
Output: Boxdawn canonical Trace (synthetic CHAIN root + tool spans only).

v1 scope (§22.3):
  - Only `tool_use` <-> `tool_result` pairs are converted into spans.
  - thinking / assistant text / user text blocks do not produce spans.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

from clew.model import Span, Trace


def _load_jsonl(path: Path) -> list[dict]:
    """JSONL file -> list of dicts. Silent skip on parse failure is forbidden (§21.4)."""
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            s = raw.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{lineno}: JSONL 라인 파싱 실패 ({exc})"
                ) from exc
    if not out:
        raise ValueError(f"{path}: 빈 JSONL 파일")
    return out


# Absence sentinels — this vendor's way of writing "the tool produced no
# output" (CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG §4.3, set S2). Claude Code
# emits these strings itself; they are not synthesised here. They are non-empty,
# so they pass the Span tool-output invariant and then make cascade's sha256
# gate read two no-output calls as duplicates — the exact match that invariant
# exists to prevent. Flagging them lets the detector skip them without holding
# any vendor string of its own.
_ABSENCE_EXACT: frozenset[str] = frozenset({"(Bash completed with no output)"})
_ABSENCE_PREFIXES: tuple[str, ...] = ("No matches found",)


def _is_absence(text: str) -> bool:
    """True when `text` is this vendor's placeholder for absent output."""
    stripped = text.strip()
    return stripped in _ABSENCE_EXACT or stripped.startswith(_ABSENCE_PREFIXES)


def _parse_ts(ts: str) -> datetime:
    """ISO-8601 (Z suffix allowed) -> tz-aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _note_nontext(notes: dict[str, int] | None, btype: str, n_chars: int) -> None:
    """Record one non-text tool_result block: its type and the chars it added."""
    if notes is None:
        return
    notes[btype] = notes.get(btype, 0) + 1
    notes["_chars"] = notes.get("_chars", 0) + n_chars


def _extract_result_text(
    content: object, notes: dict[str, int] | None = None
) -> str:
    """tool_result.content -> string (§22.5 convention).

    - str -> return as-is.
    - list -> render each block and join with '\n':
        * type=='text' -> block['text']
        * all other types -> json.dumps(block, sort_keys=True, ensure_ascii=False)
                            + warnings.warn (signal preservation, §21.4).
    - If empty after rendering, the Span validator raises (at the caller). Harmless here.

    `notes`: when given, counts each serialized non-text block by type and
    accumulates the characters it contributed, so a report can say what the
    measured text is made of.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                warnings.warn(
                    f"tool_result content[{i}]: dict 아님 ({type(block).__name__}) — "
                    f"json.dumps 로 직렬화 (§22.5)",
                    stacklevel=3,
                )
                rendered = json.dumps(block, sort_keys=True, ensure_ascii=False)
                _note_nontext(notes, type(block).__name__, len(rendered))
                parts.append(rendered)
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            else:
                warnings.warn(
                    f"tool_result content[{i}]: 비-text 블록 타입 {btype!r} — "
                    f"json.dumps 로 직렬화 (§22.5, 벤더 포맷 신호)",
                    stacklevel=3,
                )
                rendered = json.dumps(block, sort_keys=True, ensure_ascii=False)
                _note_nontext(notes, str(btype), len(rendered))
                parts.append(rendered)
        return "\n".join(parts)
    raise ValueError(
        f"tool_result.content 지원 타입 아님: {type(content).__name__}"
    )


def _serialize_input(input_obj: object) -> str:
    """tool_use.input -> deterministic JSON string (§22.2 sort_keys)."""
    return json.dumps(input_obj, sort_keys=True, ensure_ascii=False)


def _collect_cc_usage_metadata(
    entries: list[dict],
) -> tuple[dict[str, int], dict[str, dict], int]:
    """Recon §21.2: per-tool_use turn index + prev/next assistant usage.

    Returns (cc_turn_index, cc_usage_pair, cc_total_turns).

    - cc_turn_index[span_id] = 1-based assistant turn number that issued the tool_use.
    - cc_usage_pair[span_id] = {"prev": host_assistant_usage_dict_or_None,
                                 "next": next_assistant_usage_dict_or_None}
    - cc_total_turns = total assistant entries (regardless of usage presence).

    Consumer contract: cost/amplification module reads these; adapter itself
    does not use them. Span construction unchanged.
    """
    assistant_positions: list[int] = [
        i for i, e in enumerate(entries) if e.get("type") == "assistant"
    ]
    total_turns = len(assistant_positions)

    cc_turn_index: dict[str, int] = {}
    cc_usage_pair: dict[str, dict] = {}

    for order, pos in enumerate(assistant_positions):
        turn_1based = order + 1
        entry = entries[pos]
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue

        prev_usage = msg.get("usage")
        next_usage: dict | None = None
        if order + 1 < total_turns:
            nm = entries[assistant_positions[order + 1]].get("message")
            if isinstance(nm, dict):
                nu = nm.get("usage")
                if isinstance(nu, dict):
                    next_usage = nu

        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            tid = block.get("id")
            if not isinstance(tid, str) or not tid:
                continue
            cc_turn_index[tid] = turn_1based
            cc_usage_pair[tid] = {
                "prev": prev_usage if isinstance(prev_usage, dict) else None,
                "next": next_usage,
            }

    return cc_turn_index, cc_usage_pair, total_turns


# Schema source: docs/CONTEXT_RESEND_DETECTOR_PREREG.md §3 (frozen contract).
def _extract_llm_calls(
    entries: list[dict],
    *,
    input_cost_table: dict[str, float] | None,
    output_cost_table: dict[str, float] | None,
) -> list[dict[str, object]]:
    """Build the `llm_calls` metadata list from Claude Code JSONL assistant turns.

    Contract: matches the frozen Context Resend Detector prereg §3 schema —
    one entry per unique Anthropic API call (identified by `message.id`),
    ordered by first appearance.

    Grouping (§ specific to this adapter):
      Multiple consecutive JSONL `assistant` entries can share a single
      `message.id` — each entry carries one content block from the same API
      call. We group consecutive same-id entries and treat them as one API
      call (one `input_tokens` charge). Content blocks are concatenated into
      that call's `content` list (Anthropic messages-format shape).

    Input reconstruction:
      For each API call, `input_text` is the JSON-serialized messages list
      accumulated up to (but not including) that call. `user` entries
      contribute in message-order; each grouped assistant call contributes
      its combined content as a single `assistant` message on the next round.
      This matches what the Anthropic API sees as the input to that turn.

    input_tokens:
      Sum of `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`
      from the usage dict. All three are input-side; cache_read is billed
      cheaper but represents tokens actually shipped as input.
    """
    # Pass 1: collapse consecutive same-message.id assistant entries into groups.
    #         Interleave user entries between groups. Non-user/assistant entries
    #         (queue-operation, attachment, file-history-snapshot, ai-title,
    #         last-prompt, summary, ...) are skipped as they carry no
    #         model-input content.
    sequence: list[dict[str, object]] = []
    current_asst: dict[str, object] | None = None

    def _flush_current():
        nonlocal current_asst
        if current_asst is not None:
            sequence.append(current_asst)
            current_asst = None

    for entry in entries:
        etype = entry.get("type")
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")

        if etype == "user":
            _flush_current()
            sequence.append({"role": "user", "content": content})
            continue

        if etype != "assistant":
            continue

        mid = msg.get("id")
        block_content: list[object] = (
            list(content) if isinstance(content, list)
            else [{"type": "text", "text": str(content or "")}]
        )
        if (
            current_asst is not None
            and current_asst.get("message_id") == mid
            and mid is not None
        ):
            # Same API call, next content block — extend content list.
            existing = current_asst["content"]
            assert isinstance(existing, list)
            existing.extend(block_content)
            continue

        _flush_current()
        current_asst = {
            "role": "assistant",
            "content": block_content,
            "message_id": mid,
            "model": msg.get("model"),
            "timestamp": entry.get("timestamp") or "",
            "usage": msg.get("usage") or {},
        }
    _flush_current()

    # Pass 2: for each assistant group, snapshot accumulated messages BEFORE it
    #         as the input_text, then add its own response to accumulated.
    llm_calls: list[dict[str, object]] = []
    accumulated: list[dict[str, object]] = []

    for item in sequence:
        if item["role"] == "user":
            accumulated.append({
                "role": "user",
                "content": item["content"],
            })
            continue

        # assistant group
        usage = item["usage"]
        assert isinstance(usage, dict)
        model = item.get("model")
        # Anthropic Claude Code JSONL usage semantics:
        #   input_tokens              = uncached input only
        #   cache_read_input_tokens   = cache-hit portion
        #   cache_creation_input_tokens = cache-write portion (5m default TTL)
        # Total input = sum of all three. Cost Attribution Completion prereg §4
        # requires the split for tier-accurate cost — expose all three.
        input_tokens_uncached = int(usage.get("input_tokens") or 0)
        input_tokens_cache_read = int(usage.get("cache_read_input_tokens") or 0)
        input_tokens_cache_write = int(
            usage.get("cache_creation_input_tokens") or 0
        )
        input_tokens = (
            input_tokens_uncached
            + input_tokens_cache_read
            + input_tokens_cache_write
        )
        output_tokens = usage.get("output_tokens") or 0

        input_cost_rate: float | None = None
        if input_cost_table and isinstance(model, str) and model in input_cost_table:
            input_cost_rate = float(input_cost_table[model])
        output_cost_rate: float | None = None
        if output_cost_table and isinstance(model, str) and model in output_cost_table:
            output_cost_rate = float(output_cost_table[model])

        # span_id fallback: message.id when present; else a synthetic based on
        # timestamp + sequence index (deterministic within a session).
        span_id = item.get("message_id")
        if not isinstance(span_id, str) or not span_id:
            span_id = f"cc-llm-{len(llm_calls):06d}"

        llm_calls.append({
            "span_id": span_id,
            "input_text": json.dumps(accumulated, ensure_ascii=False, default=str),
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "input_tokens_uncached": input_tokens_uncached,
            "input_tokens_cache_read": input_tokens_cache_read,
            "input_tokens_cache_write": input_tokens_cache_write,
            "input_cost_rate": input_cost_rate,
            "output_cost_rate": output_cost_rate,
            "cost_rate_legacy": None,
            "model": model,
            "start_time": item.get("timestamp") or "",
        })
        accumulated.append({
            "role": "assistant",
            "content": item["content"],
        })

    return llm_calls


def _build_ingest_notes(
    *,
    n_orphan_use_skipped: int,
    no_tool_use_recovery: bool,
    unknown_block_types: dict[str, int],
    nontext_notes: dict[str, int],
) -> dict:
    """What the adapter dropped or rewrote on the way to the Trace.

    Every entry is something the numbers downstream were computed *without*
    (dropped) or *on top of* (rewritten). Empty dict when the file mapped
    cleanly, so a report can stay silent in the ordinary case.
    """
    notes: dict = {}
    if n_orphan_use_skipped:
        notes["orphan_tool_use_skipped"] = n_orphan_use_skipped
    if no_tool_use_recovery:
        notes["no_tool_use_recovery"] = True
    if unknown_block_types:
        notes["unknown_block_types"] = dict(unknown_block_types)
    if nontext_notes:
        counts = {k: v for k, v in nontext_notes.items() if k != "_chars"}
        notes["nontext_result_blocks"] = counts
        notes["nontext_result_chars"] = nontext_notes.get("_chars", 0)
    return notes


def ingest_claude_code_jsonl(
    path: Path,
    *,
    input_cost_table: dict[str, float] | None = None,
    output_cost_table: dict[str, float] | None = None,
) -> Trace:
    """Claude Code JSONL transcript -> Trace (§22.1 mapping convention).

    `input_cost_table` / `output_cost_table` (Context Resend Detector prereg
    §4): per-model $/token rates for input and output sides. When provided,
    each `llm_calls` entry carries accurate per-side rates; the detector's
    `cost_accuracy_flag` will be `"accurate"`. When omitted (the default),
    rates stay None and the detector falls back to legacy behavior.

    Raises:
        ValueError: parse/join failure, empty output_text span, missing sessionId, etc.
    """
    entries = _load_jsonl(path)

    # Extract sessionId (assume all lines share the same sessionId)
    session_id: str | None = None
    for e in entries:
        sid = e.get("sessionId")
        if sid:
            session_id = sid
            break
    if session_id is None:
        raise ValueError(f"{path}: sessionId 필드가 없음 (Claude Code JSONL 아님?)")

    # Collect compact boundary timestamps (§22.11.2).
    # The two marker fields are exactly what classify_21_positives.py:_window_compact_flag actually looks at:
    #   - entry["compactMetadata"] is not None   (type=='system' line)
    #   - entry["isCompactSummary"] is True      (type=='user' line)
    # Both markers carry entry["timestamp"] (confirmed via 2026-07-18 real JSONL).
    compact_boundaries: list[datetime] = []
    for entry in entries:
        ts = entry.get("timestamp")
        if not ts:
            continue
        if entry.get("compactMetadata") is not None or entry.get("isCompactSummary") is True:
            compact_boundaries.append(_parse_ts(ts))

    # First pass: collect tool_use / tool_result
    tool_uses: dict[str, tuple[dict, str]] = {}
    tool_results: dict[str, tuple[dict, str]] = {}
    unknown_block_types: dict[str, int] = {}
    # §29.2 tool-error gate: Anthropic tool_result carries structural is_error=True
    # on tool crashes (e.g. "File has not been read yet"). Adapter collects tids only;
    # cascade/frozen path unchanged. Report/cost layers consume this list to skip
    # error-response spans from waste/amplification with explicit counts.
    error_span_ids: list[str] = []

    for entry in entries:
        etype = entry.get("type")
        msg = entry.get("message")
        ts = entry.get("timestamp")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if not ts:
            continue

        if etype == "assistant":
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    tid = block.get("id")
                    if not tid:
                        raise ValueError(
                            f"tool_use 블록에 id 없음 (uuid={entry.get('uuid')})"
                        )
                    if tid in tool_uses:
                        raise ValueError(f"중복 tool_use.id: {tid!r}")
                    tool_uses[tid] = (block, ts)
                elif btype in ("thinking", "text"):
                    # §22.3: do not create a span
                    continue
                else:
                    unknown_block_types[str(btype)] = (
                        unknown_block_types.get(str(btype), 0) + 1
                    )

        elif etype == "user":
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_result":
                    tid = block.get("tool_use_id")
                    if not tid:
                        raise ValueError(
                            f"tool_result 블록에 tool_use_id 없음 (uuid={entry.get('uuid')})"
                        )
                    if tid in tool_results:
                        raise ValueError(f"중복 tool_result for {tid!r}")
                    tool_results[tid] = (block, ts)
                    if block.get("is_error") is True:
                        error_span_ids.append(tid)
                elif btype == "text":
                    continue
                else:
                    unknown_block_types[str(btype)] = (
                        unknown_block_types.get(str(btype), 0) + 1
                    )

    if unknown_block_types:
        warnings.warn(
            f"{path.name}: 알 수 없는 assistant/user content 블록 타입 "
            f"{dict(unknown_block_types)} — 스팬 생성에서 제외",
            stacklevel=2,
        )

    # Join check (§22.4 abort condition 2 — amended by §29.1):
    #   orphan tool_result   → still raise (unknown-cause data corruption).
    #   orphan tool_use only → skip those tool_uses + warn (session-abort recovery).
    orphan_use = sorted(set(tool_uses) - set(tool_results))
    orphan_result = sorted(set(tool_results) - set(tool_uses))
    if orphan_result:
        raise ValueError(
            f"조인 실패 — orphan tool_use={len(orphan_use)}건 "
            f"(첫 5개: {orphan_use[:5]}), "
            f"orphan tool_result={len(orphan_result)}건 "
            f"(첫 5개: {orphan_result[:5]})"
        )
    n_orphan_use_skipped = len(orphan_use)
    if orphan_use:
        warnings.warn(
            f"{path.name}: orphan tool_use {len(orphan_use)}건 skip "
            f"(§29.1 session-abort recovery, 첫 5개: {orphan_use[:5]})",
            stacklevel=2,
        )
        for tid in orphan_use:
            tool_uses.pop(tid, None)

    # Create spans
    nontext_notes: dict[str, int] = {}
    root_span_id = f"root-{session_id}"
    tool_spans: list[Span] = []
    for tid, (use_block, use_ts) in tool_uses.items():
        result_block, result_ts = tool_results[tid]
        input_text = _serialize_input(use_block.get("input", {}))
        output_text = _extract_result_text(result_block.get("content"), nontext_notes)
        start = _parse_ts(use_ts)
        end = _parse_ts(result_ts)
        # Prevent end < start (clock inversion) - the Span validator catches this, but raises explicitly without clamping
        tool_spans.append(
            Span(
                trace_id=session_id,
                span_id=tid,
                parent_span_id=root_span_id,
                agent_or_node_id=use_block.get("name") or "anonymous",
                span_kind="tool",
                start_time=start,
                end_time=end,
                input_text=input_text,
                output_text=output_text,
                output_is_absent=_is_absence(output_text),
                token_count=None,
                model=None,
                cost_rate=None,
            )
        )

    # Root timing: prefer tool_span range; else fall back to entry timestamps (§29.1 no-tool-use recovery).
    no_tool_use_recovery = not tool_spans
    if tool_spans:
        root_start = min(s.start_time for s in tool_spans)
        root_end = max(s.end_time for s in tool_spans)
    else:
        warnings.warn(
            f"{path.name}: no tool spans (0 paired tool_use/tool_result) — "
            f"returning root-only Trace (§29.1 no-tool-use recovery)",
            stacklevel=2,
        )
        entry_ts = [_parse_ts(e["timestamp"]) for e in entries if e.get("timestamp")]
        if not entry_ts:
            raise ValueError(f"{path}: no timestamps found in entries")
        root_start = min(entry_ts)
        root_end = max(entry_ts)
    root_span = Span(
        trace_id=session_id,
        span_id=root_span_id,
        parent_span_id=None,
        agent_or_node_id="[claude-code-session-root]",
        span_kind="chain",
        start_time=root_start,
        end_time=root_end,
        input_text="",
        output_text="[claude-code session root]",
    )

    cc_turn_index, cc_usage_pair, cc_total_turns = _collect_cc_usage_metadata(entries)

    # Context Resend Detector prereg §3: build llm_calls metadata from
    # assistant turns. This adapter previously produced tool-only spans and
    # left llm_calls empty; the extraction below is orthogonal to span
    # construction and does not modify tool spans.
    llm_calls = _extract_llm_calls(
        entries,
        input_cost_table=input_cost_table,
        output_cost_table=output_cost_table,
    )

    return Trace(
        trace_id=session_id,
        spans=[root_span] + tool_spans,
        metadata={
            "source": "claude_code_jsonl",
            "path": str(path.name),
            "compact_boundaries": compact_boundaries,
            "cc_turn_index": cc_turn_index,
            "cc_usage_pair": cc_usage_pair,
            "cc_total_turns": cc_total_turns,
            "error_span_ids": error_span_ids,
            "llm_calls": llm_calls,
            "ingest_notes": _build_ingest_notes(
                n_orphan_use_skipped=n_orphan_use_skipped,
                no_tool_use_recovery=no_tool_use_recovery,
                unknown_block_types=unknown_block_types,
                nontext_notes=nontext_notes,
            ),
        },
    )
