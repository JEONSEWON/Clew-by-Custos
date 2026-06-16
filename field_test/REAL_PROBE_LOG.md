# REAL_PROBE_LOG.md — Real-Trace Probe Results (SPEC §11)

Date: 2026-06-16T06:25:03Z
Frozen params: PHI=0.514345, N=2, MODEL=paraphrase-multilingual-MiniLM-L12-v2
Topic: 'quantum computing basics'

---

## Per-Trace Results

### clean
- note: E1: FP=0 기대
- detected: N
- expected: N
- status: PASS
- waste_span_ids: []
- waste_tokens: 0
- waste_cost: 0.000000

#### E3 Non-Waste Span Cosines
| Span A | Span B | cosine | ≥ φ? |
|--------|--------|--------|------|
| researcher | summarizer | 0.8259 | Y |
| researcher | critic | 0.6497 | Y |
| researcher | LangGraph | 0.6497 | Y |
| summarizer | critic | 0.7350 | Y |
| summarizer | LangGraph | 0.7350 | Y |
| critic | LangGraph | 1.0000 | Y |

- count: 6
- min: 0.6497
- median: 0.7350
- max: 1.0000
- above φ (0.514345): 6/6

### repeat_node
- note: E2: llm repeat 탐지 기대 (입력 게이트 없음)
- detected: Y
- expected: Y
- status: PASS
- waste_span_ids: ['0f6dc5c36ee7de58']
- waste_tokens: 0
- waste_cost: 0.000000

#### E3 Non-Waste Span Cosines
| Span A | Span B | cosine | ≥ φ? |
|--------|--------|--------|------|
| researcher | summarizer | 0.8643 | Y |
| researcher | critic | 0.7129 | Y |
| researcher | LangGraph | 1.0000 | Y |
| summarizer | critic | 0.7408 | Y |
| summarizer | LangGraph | 0.8643 | Y |
| critic | LangGraph | 0.7129 | Y |

- count: 6
- min: 0.7129
- median: 0.8026
- max: 1.0000
- above φ (0.514345): 6/6

### requery_known
- note: E2: tool 입력 게이트 경로 탐지 기대 (동일 입력)
- detected: Y
- expected: Y
- status: PASS
- waste_span_ids: ['dd5c632bb2a776a5']
- waste_tokens: 0
- waste_cost: 0.000000

#### E3 Non-Waste Span Cosines
| Span A | Span B | cosine | ≥ φ? |
|--------|--------|--------|------|
| fake_search | searcher | 1.0000 | Y |
| fake_search | summarizer | 0.8722 | Y |
| fake_search | critic | 0.6320 | Y |
| fake_search | LangGraph | 0.6320 | Y |
| searcher | summarizer | 0.8722 | Y |
| searcher | critic | 0.6320 | Y |
| searcher | LangGraph | 0.6320 | Y |
| summarizer | critic | 0.6957 | Y |
| summarizer | LangGraph | 0.6957 | Y |
| critic | LangGraph | 1.0000 | Y |

- count: 10
- min: 0.6320
- median: 0.6957
- max: 1.0000
- above φ (0.514345): 10/10

### requery_clean
- note: E2 음성 대조: tool 입력 게이트가 다른 입력 거절 → 미탐지 기대
- detected: N
- expected: N
- status: PASS
- waste_span_ids: []
- waste_tokens: 0
- waste_cost: 0.000000

#### E3 Non-Waste Span Cosines
| Span A | Span B | cosine | ≥ φ? |
|--------|--------|--------|------|
| fake_search | fake_search | 0.9606 | Y |
| fake_search | searcher | 0.9606 | Y |
| fake_search | summarizer | 0.8100 | Y |
| fake_search | critic | 0.5899 | Y |
| fake_search | LangGraph | 0.5899 | Y |
| fake_search | searcher | 1.0000 | Y |
| fake_search | summarizer | 0.8643 | Y |
| fake_search | critic | 0.6238 | Y |
| fake_search | LangGraph | 0.6238 | Y |
| searcher | summarizer | 0.8643 | Y |
| searcher | critic | 0.6238 | Y |
| searcher | LangGraph | 0.6238 | Y |
| summarizer | critic | 0.6810 | Y |
| summarizer | LangGraph | 0.6810 | Y |
| critic | LangGraph | 1.0000 | Y |

- count: 15
- min: 0.5899
- median: 0.6810
- max: 1.0000
- above φ (0.514345): 15/15

### pingpong
- note: E2: pingpong A→B→A→B 탐지 기대
- detected: Y
- expected: Y
- status: PASS
- waste_span_ids: ['becdf68f69ed93cb', '35656fcda822aa1d']
- waste_tokens: 0
- waste_cost: 0.000000

#### E3 Non-Waste Span Cosines
| Span A | Span B | cosine | ≥ φ? |
|--------|--------|--------|------|
| researcher | critic | 0.6592 | Y |
| researcher | LangGraph | 0.6986 | Y |
| critic | LangGraph | 0.9470 | Y |

- count: 3
- min: 0.6592
- median: 0.6986
- max: 0.9470
- above φ (0.514345): 3/3

---

## Expectation Summary

### E1 (clean → FP=0)
- detected=N, expected=N → PASS

### E2 (waste scenarios + negative control)
- repeat_node: detected=Y, expected=Y → PASS
- requery_known: detected=Y, expected=Y → PASS
- requery_clean: detected=N, expected=N → PASS
- pingpong: detected=Y, expected=Y → PASS

### E3 (non-waste cosine distribution vs finding3 0.48–0.57 cluster)
See per-trace tables above.
Finding3 predicts non-waste cosines cluster 0.48–0.57.
φ=0.514345 is untouched regardless of distribution outcome.

---

## API Call Count
- clean: 3 LLM calls
- repeat_node: 4 LLM calls (researcher×2 + summarizer + critic)
- requery_known: 2 LLM + 2 tool calls (searcher×2 same input + summarizer + critic)
- requery_clean: 2 LLM + 2 tool calls (searcher×2 diff input + summarizer + critic)
- pingpong: 4 LLM calls (researcher×2 + critic×2)
- Total: 15 LLM calls + 4 deterministic tool calls

---

## E3 발견 기록 (2026-06-16, 2차 실행)

### 결과 요약

5종 전체 E1/E2 PASS. clean·requery_clean FP=0 확인.

단 FP=0은 구조 레이어(find_repeat_candidates)가 후보를 만들지 않은 결과이며,
의미 레이어(φ 게이트)가 분리해낸 것이 아니다.

### E3 비낭비 코사인 실측 분포

| 시나리오 | above-φ (0.514345) | min | median | max |
|----------|-------------------|-----|--------|-----|
| clean | 6/6 (100%) | 0.6497 | 0.7350 | 1.0000 |
| repeat_node | 6/6 (100%) | 0.7129 | 0.8026 | 1.0000 |
| requery_known | 10/10 (100%) | 0.6320 | 0.6957 | 1.0000 |
| requery_clean | 15/15 (100%) | 0.5899 | 0.6810 | 1.0000 |
| pingpong | 3/3 (100%) | 0.6592 | 0.6986 | 0.9470 |

### 해석

finding3('비낭비 코사인이 0.48~0.57에 군집')는 재현되지 않음.
실측 비낭비 코사인은 min 0.59~0.71, 대부분 0.65 이상에 분포한다.
같은 토픽('quantum computing basics') 출력들이 어휘를 공유해
베이스라인 유사도 자체가 높은 것이 원인.

φ-transfer 문제가 finding3 예측보다 강하게 확인됨:
의미 레이어(절대 코사인 ≥ φ)는 실측에서 낭비/비낭비 분리력을 잃는다.

단 n=1 토픽·5트레이스 관찰이므로 확정 아님.
다른 토픽·도메인·언어 트레이스에서 달라질 수 있다.

### 금지 재확인

φ를 사후에 올리는 것은 해법이 아니다(데이터 보고 오버핏).
의미 레이어 재설계는 실제 트레이스 3~5건 분포 확보 후
별도 사전등록 실험에서만 진행한다.