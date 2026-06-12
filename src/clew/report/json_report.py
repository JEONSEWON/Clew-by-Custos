"""src/clew/report/json_report.py — 기계용 JSON 리포트 렌더러."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from clew.detect.cascade import CascadeResult
from clew.model import Trace
from clew.report._model import WasteDetail

_PHI = 0.514345
_N = 2
_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

_SNIPPET_LEN = 80


def render_json(
    trace: Trace,
    cr: CascadeResult,
    details: list[WasteDetail],
    *,
    no_snippets: bool = False,
    snippet_len: int = _SNIPPET_LEN,
) -> str:
    """CascadeResult + WasteDetail 목록 → JSON 문자열 (indent=2).

    스니펫: output_text[:snippet_len] 기본 (no_snippets=True면 키 자체 제외).
    리포트 머리에 동결 파라미터(φ, N, 모델) 포함.
    """
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    waste_details_list = []
    for wd in details:
        wt = wd.waste_tokens
        wc = wd.waste_cost
        entry: dict = {
            "origin_node": wd.origin.agent_or_node_id,
            "repeat_node": wd.candidate.agent_or_node_id,
            "cosine": round(wd.cosine, 6),
            "tokens_wasted": wt if wt is not None else "unknown",
            "cost_wasted": round(wc, 8) if wc is not None else "unknown",
        }
        if not no_snippets:
            entry["snippet"] = wd.candidate.output_text[:snippet_len]
        waste_details_list.append(entry)

    total_tok = cr.waste_tokens if cr.waste_tokens > 0 else None
    total_cost = cr.waste_cost if cr.waste_cost > 0.0 else None

    report: dict = {
        "trace_id": trace.trace_id,
        "analyzed": now,
        "detector_params": {
            "phi": _PHI,
            "n": _N,
            "model": _MODEL,
        },
        "wasteful": cr.wasteful,
        "waste_span_count": len(cr.waste_span_ids),
        "total_tokens_wasted": total_tok if total_tok is not None else "unknown",
        "total_cost_wasted": round(total_cost, 8) if total_cost is not None else "unknown",
        "waste_details": waste_details_list,
        "note": (
            "Detection thresholds were calibrated on synthetic traces; "
            "real-trace calibration is in progress. Borderline matches "
            "(cosine near 0.51) deserve human review."
        ),
    }

    return json.dumps(report, ensure_ascii=False, indent=2)
