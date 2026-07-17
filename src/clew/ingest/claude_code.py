"""src/clew/ingest/claude_code.py — Claude Code JSONL transcript → Trace.

매핑 규약: docs/CC_TRANSCRIPT.md §22 (사전등록, PR 승인 후 확정).

입력: `~/.claude/projects/<slug>/<uuid>.jsonl` (JSONL, 한 줄 = 한 JSON).
출력: Clew 정규 Trace (synthetic CHAIN root + tool 스팬만).

v1 범위 (§22.3):
  - `tool_use` ↔ `tool_result` 쌍만 스팬으로 변환.
  - thinking / assistant text / user text 블록은 스팬 안 만듦.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path

from clew.model import Span, Trace


def _load_jsonl(path: Path) -> list[dict]:
    """JSONL 파일 → dict 리스트. 파싱 실패 시 조용히 skip 금지 (§21.4)."""
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


def _parse_ts(ts: str) -> datetime:
    """ISO-8601 (Z suffix 허용) → tz-aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _extract_result_text(content: object) -> str:
    """tool_result.content → 문자열 (§22.5 규약).

    - str 이면 그대로.
    - list 면 블록별 렌더 후 '\n' 결합:
        * type=='text' → block['text']
        * 그 외 모든 타입 → json.dumps(block, sort_keys=True, ensure_ascii=False)
                            + warnings.warn (신호 보존, §21.4).
    - 렌더 후에도 빈 문자열이면 Span validator 가 raise (호출측에서). 여기선 무해.
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
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
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
                parts.append(json.dumps(block, sort_keys=True, ensure_ascii=False))
        return "\n".join(parts)
    raise ValueError(
        f"tool_result.content 지원 타입 아님: {type(content).__name__}"
    )


def _serialize_input(input_obj: object) -> str:
    """tool_use.input → 결정론 JSON 문자열 (§22.2 sort_keys)."""
    return json.dumps(input_obj, sort_keys=True, ensure_ascii=False)


def ingest_claude_code_jsonl(path: Path) -> Trace:
    """Claude Code JSONL transcript → Trace (§22.1 매핑 규약).

    Raises:
        ValueError: 파싱/조인 실패, output_text 빈 스팬, sessionId 부재 등.
    """
    entries = _load_jsonl(path)

    # sessionId 추출 (모든 라인이 동일 sessionId 를 갖는다고 가정)
    session_id: str | None = None
    for e in entries:
        sid = e.get("sessionId")
        if sid:
            session_id = sid
            break
    if session_id is None:
        raise ValueError(f"{path}: sessionId 필드가 없음 (Claude Code JSONL 아님?)")

    # 1차 스캔: tool_use / tool_result 수집
    tool_uses: dict[str, tuple[dict, str]] = {}
    tool_results: dict[str, tuple[dict, str]] = {}
    unknown_block_types: dict[str, int] = {}

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
                    # §22.3: 스팬 안 만듦
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

    if not tool_uses:
        raise ValueError(f"{path}: tool_use 블록이 하나도 없음")

    # 조인 검사 (§22.4 중단 조건 2)
    orphan_use = sorted(set(tool_uses) - set(tool_results))
    orphan_result = sorted(set(tool_results) - set(tool_uses))
    if orphan_use or orphan_result:
        raise ValueError(
            f"조인 실패 — orphan tool_use={len(orphan_use)}건 "
            f"(첫 5개: {orphan_use[:5]}), "
            f"orphan tool_result={len(orphan_result)}건 "
            f"(첫 5개: {orphan_result[:5]})"
        )

    # Span 생성
    root_span_id = f"root-{session_id}"
    tool_spans: list[Span] = []
    for tid, (use_block, use_ts) in tool_uses.items():
        result_block, result_ts = tool_results[tid]
        input_text = _serialize_input(use_block.get("input", {}))
        output_text = _extract_result_text(result_block.get("content"))
        start = _parse_ts(use_ts)
        end = _parse_ts(result_ts)
        # end < start (시계 역전) 방지 — Span validator 가 잡지만 명시적으로 클램프 없이 raise
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
                token_count=None,
                model=None,
                cost_rate=None,
            )
        )

    # Synthetic CHAIN root (otel_json.py:278 선례)
    root_start = min(s.start_time for s in tool_spans)
    root_end = max(s.end_time for s in tool_spans)
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

    return Trace(
        trace_id=session_id,
        spans=[root_span] + tool_spans,
        metadata={"source": "claude_code_jsonl", "path": str(path.name)},
    )
