# Clew Waste Report

- **trace_id**: `57382523a98d1796e13a81280f544d16`
- **analyzed**: 2026-06-12T05:41:15Z
- **detector params**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2

## Result: WASTE DETECTED

- **wasted spans**: 1
- **estimated wasted tokens**: unknown
- **estimated wasted cost**: unknown

## Wasted Span Details

| origin_node | repeat_node | cosine | tokens (wasted) | cost (wasted) |
|-------------|-------------|--------|-----------------|---------------|
| researcher | researcher | 0.9274 | unknown | unknown |

## Snippets

**1. researcher** (repeat)
> AI 멀티에이전트 시스템의 낭비 원인 요약: (1) 중복 조회 — 이미 가진 데이터를 반복해서 가져온다. (2) 결과 재작성 — 이전 에이전트 

---
_Note: detection thresholds were calibrated on synthetic traces; real-trace calibration is in progress. Borderline matches (cosine near 0.51) deserve human review._