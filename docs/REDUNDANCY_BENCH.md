# §24 — RedundancyBench 어댑터 + F1 매핑 사전등록 (2026-07-18, 규칙 8)

**대상 데이터**: RedundancyBench (arXiv:2605.29893, 4open.science/r/RedundancyBench, MIT © 2026 Minyang Hu). tau2-bench 3 도메인 (airline / retail / telecom) 트레이스 200개 + human step-level redundancy 라벨.

**왜 이 벤치인가**:
- Toolathlon (§23) 은 성공/실패만 라벨 — 스텝 단위 검증 불가. 우리 waste 정의의 F1 을 논문 대비 정량 비교 불가.
- RedundancyBench 는 **step-level GT** 를 제공 (4 카테고리: exploratory / duplicated / abnormal / incorrect). 논문 최고 baseline step-level F1 = 24.88% (Window-to-One). 낮은 상한 → 정밀도 우선 게이트가 유의미할 가능성.
- 데이터 재배포 없음(MIT 이지만 `data/` 는 gitignored, 로컬 분석만). 논문 evaluate.py 재현 가능.

**리콘 산출물** (규칙 7 부칙, 같은 커밋 동봉):
- `field_test/diagnostics/recon_redundancybench.py` — 스키마 리콘 (Q1–Q5)

---

## §24.1 — 데이터 / 라이선스

**출처**: `anonymous.4open.science/r/RedundancyBench` (arxiv 익명 리뷰용, MIT).

**로컬 경로** (커밋 금지 — `.gitignore: data/`):
```
data/redundancy_bench/
├── LICENSE                MIT © 2026 Minyang Hu
├── README.md              6970 bytes
├── LLM_judge/
│   ├── judge.py           (LLM inference — 사용 안 함)
│   ├── evaluate.py        (평가 스크립트 — 우리 대조 기준)
│   └── requirements.txt
└── data/domain/
    ├── airline/     annotation.json + final_traces.json
    ├── retail/      annotation.json + final_traces.json
    └── telecom/     annotation.json + final_traces.json
```

**규모** (recon 실측):

| 도메인 | sims (final_traces) | annotated tasks | with_red | assistant tool spans | user tool msgs (제외) |
|---|---:|---:|---:|---:|---:|
| airline | 40 | 40 | 37 | 372 | 0 |
| retail | 48 | 44 (4 extras 무시) | 39 | 409 | 0 |
| telecom | 112 | 112 | 107 | 847 | 1035 |
| **총계** | **200** | **196** | **183** (93.4%) | **1628** | 1035 |

**typed 분포**:
- exploratory: 8 + 85 + 522 = **615**
- duplicated: 2 + 44 + 84 = **130**   ← 우리 sha256 게이트 직접 대응
- abnormal: 4 + 28 + 68 = **100**
- incorrect: 6 + 20 + 12 = **38**

**GT pair 구조**: `redundant_step_idx` 는 모든 도메인에서 (call_idx, result_idx) 인접 쌍. `pair_bad=0` (recon Q2 확장 검증). airline task=1 예: `[6,7,10,11,12,13,8,9,16,17,18,19]` 정렬 시 (6,7)(8,9)(10,11)(12,13)(16,17)(18,19). turn 6=assistant call, 7=tool result 확인.

**예외** (§24.3 에 계산 규약 별도 표기):
- telecom 2 task 에 홀수-길이 GT (총 12 idx 짝없음). 짝없는 idx 는 전부 `role=tool, requestor=user` (사용자 시뮬 디바이스 tool). 우리 어댑터 정책상 span 화 안 함 → 예측 불가능 세트로 사전 분리.

---

## §24.2 — 어댑터 매핑 (recon 확정)

**신규 모듈**: `src/clew/ingest/redundancy_bench.py`

**분기 정책** (`_load_trace_auto` 확장):
- `.jsonl` 이 아님 — RB 는 `final_traces.json` (전체가 하나의 JSON `{tasks: [], simulations: []}`).
- 새 확장 함수 `iter_redundancy_bench_traces(path: Path) -> Iterator[Trace]` 로 파일당 다중 트레이스 반환. `_load_trace_auto` 는 첫 sim 만 반환 (CC/Toolathlon 계약 동일).
- 분기 마커: 최상위 dict 에 `tasks` AND `simulations` 키.

**Span 매핑**:

| Span 필드 | RB 소스 | 근거 |
|---|---|---|
| `trace_id` | `simulation.id` (uuid) | recon Q3 |
| `span_id` | `messages[i].tool_calls[j].id` (예: `call_be9cc486…`) | recon Q3 (조인 키, tool msg 의 `id` 필드와 매칭. `tool_call_id` 아님 — RB 는 flat) |
| `parent_span_id` | synthetic root (`root-<sim.id>`) | Toolathlon 선례 (§23.1) |
| `agent_or_node_id` | `tool_calls[j].name` (RB 는 flat, `function:` nesting 없음) | recon Q3 |
| `span_kind` | `"tool"` | 전부 tool 호출 |
| `input_text` | `json.dumps(tool_calls[j].arguments, sort_keys=True, ensure_ascii=False)` | RB `arguments` 는 dict (str 아님, Toolathlon 과 다름). sort_keys 재직렬화로 sha256 안정 |
| `output_text` | 매칭 tool 메시지의 `content` (str) | recon Q3 (flat string 관찰) |
| `start_time` / `end_time` | synthetic — `base + turn_idx * seconds` | 아래 규약 §24.2.1 |
| `token_count` | `None` | RB 미제공 |
| `model` | trace 최상위 없음. 필요 시 metadata 로 별도 | — |
| `cost_rate` | `None` | — |

**필터**: `requestor='user'` 인 tool_calls / tool msgs 는 **제외**. 이유:
- recon 확정: telecom 만 1035건, airline/retail = 0.
- 사용자가 디바이스 상태를 시뮬레이션하는 툴콜이라 agent 행동 아님.
- 이 세트를 span 화하면 우리 정의 ("agent 반복 호출") 를 위배.

**Trace.metadata 확장** (Span 구조 불변, §22.11 선례):
```python
{
    "source": "redundancy_bench",
    "domain": "airline" | "retail" | "telecom",
    "task_id": simulation["task_id"],
    "sim_id": simulation["id"],
    "reward_info": simulation.get("reward_info"),
    # §24.3 규약 A 실행 위해 필수: span_id → (call_turn_idx, result_turn_idx)
    "rb_span_to_turn_pair": {span_id: [call_idx, result_idx], ...},
    # user-발행 tool 은 별도 기록만 (매칭 계산 시 무시)
    "rb_user_tool_idx": [turn_idx, ...],
}
```

### §24.2.1 — synthetic timestamp 규약

**사실**: RB `messages[i]` 에 `timestamp` 필드 있음 (ISO datetime). 단, 병렬 tool_calls 는 **없음** (recon 확인: parallel_msgs=0 across 3 도메인).

**규약**:
- 원본 timestamp 사용 (있으므로 synthetic 불필요).
- 파싱 실패 시 fallback: `base + turn_idx * 1s` (Toolathlon 선례 축소판).
- 병렬 없으므로 sub_idx 필요 없음.

### §24.2.2 — 조인 검증

- `tool_call_id` 필드 없음 (Toolathlon 과 필드명 다름). 조인 키는 `tool.id`.
- assistant.tool_calls 의 id set == 매칭 tool msg 의 id set (assistant-requestor 만).
- 미매칭 발견 시 명시 raise (§21.4). recon 이미 확인: airline 40/40, retail 검증 예정, telecom 은 assistant-only 로 필터 후 확인.

---

## §24.3 — GT 비교 규약 (결과 보기 전 확정)

**핵심 결정**: 논문 `evaluate.py:evaluate_standard()` 는 step-level F1 을 micro-averaged 로 계산 —
```python
tp = |GT_set ∩ Pred_set|
fp = |Pred_set - GT_set|
fn = |GT_set - Pred_set|
precision = tp/(tp+fp);  recall = tp/(tp+fn);  f1 = 2PR/(P+R)
```
각 task 별 `GT_set` = `set(annotation["redundant_step_idx"])`, `Pred_set` 은 검출기가 낸 turn_idx 집합.

**우리 span_id 의 turn_idx 대응** (recon 확정):
- Span 1개 = tool_call.id 1개 = (assistant_call_turn_idx, tool_result_turn_idx) 쌍.
- 88–91% 케이스 gap=1 (assistant 콜 바로 다음 turn 이 tool 결과). 나머지는 사용자 메시지가 사이에 낀 케이스 (여전히 같은 `tool.id` 로 조인, gap 임의).
- 그러나 GT `redundant_step_idx` 는 **항상 인접 쌍** (pair_bad=0). RB 어노테이터가 assistant call 과 그 result 를 항상 인접 idx 로 라벨.

**규약 A (pair expansion) — 선택** ✓
- 각 waste span 을 `{call_turn_idx, result_turn_idx}` 두 idx 로 확장해서 `Pred_set` 에 넣는다.
- 예: waste span_id `call_be9cc486…` → `Trace.metadata["rb_span_to_turn_pair"]` 조회 → `[2, 3]` → `Pred_set ∪= {2, 3}`.

**왜 A 인가**:
- GT 는 pair-labeled (재확인: pair_bad=0). GT 와 pred 를 같은 단위(single idx)로 놓기 위해 우리 pred 도 pair 로 확장.
- 규약 B (GT contraction) 는 논문 evaluate.py 를 안 쓰고 우리 게 재정의하는 것 → 논문 24.88% 와 직접 비교 불가. 재현성 손실.
- 규약 C (both) 는 double-reporting 지저분. A 를 primary 로, B 는 부록 표에만 옵션.

**규약 A 세부**:
1. `Pred_set` = ∪ {[call_idx, result_idx] for span_id in waste_span_ids}.
2. `GT_set` = `set(annotation["redundant_step_idx"])` 를 그대로 사용 (필터/변환 없음).
3. `tp = |GT_set ∩ Pred_set|` 등 논문 그대로.
4. 우리 어댑터 skip 세트 (`rb_user_tool_idx` 12 idx, user-발행 tool 결과) 는 `GT_set` 에 남긴다. → 예측 불가로 표시되어 recall 상한 자연 감소. 이걸 별도 조작 (예: GT_set 에서 제거) 하면 dishonest tuning.

**대안 아닌 것**:
- 논문 telecom evaluate 는 "dict-keyed 방식 (dataset 정의상 미묘하게 다름)" (recon Q5 인용). 우리는 3 도메인 모두 airline/retail 규약(evaluate_standard) 로 통일해서 계산 — 논문의 "average" 표와는 이 지점에서 미묘히 다를 수 있음. §24.7 결과 섹션에 명시.

**규약 A 예측**:
- `Pred_set` 크기 = waste_span_count × 2 (병렬 없음 → 각 span 이 정확히 2 idx 로 확장).
- tp / fp / fn 계산 시 idx 단위 (pair 단위 아님).

---

## §24.4 — 카테고리 스코프

**우리 게이트 (구조 N=2 → sha256 tool-kind → compact) 가 잡을 수 있는 것**:

| RB 카테고리 | 라벨 수 | 우리 게이트 hit 예상 | 근거 |
|---|---:|---|---|
| duplicated step | 130 | **주 타겟** | 정의상 (name, args, output) 동일. sha256 게이트 직결. |
| abnormal step (error) | 100 | 부분 hit | 두 번 재시도가 같은 에러 output → sha256 매칭 가능. 다른 에러/새 output 이면 miss. |
| exploratory step | 615 | 낮은 hit | args 다양, output 다양. 우리 게이트가 잡지 못함 (LLM judge 영역). |
| incorrect step | 38 | 매우 낮은 hit | 미션 벗어남 판단 필요, 게이트 밖. |

**중요**: 우리 게이트는 duplicated 특화. exploratory (615, GT 의 66%) 는 원리적으로 못 잡음. → step-level recall 상한은 대략 `(130 + 100 부분) / 883` ≈ 15–25% 근처.

**정밀도 우선 게이트**: 논문 baseline (Window-to-One 20% F1) 대비 우리 precision 이 더 높을 것이라고 예측. recall 은 낮을 것.

---

## §24.5 — 사전등록 예측 (결과 보기 전)

**대상**: 3 도메인 all annotated sims = 196. 어댑터 + 3단 게이트 (구조 N=2 → sha256 → compact) 전량 실행.

**주의**: compact 게이트는 RB metadata 에 `compact_boundaries` 없으므로 no-op (Toolathlon §23 선례와 동일).

### 예측 수치

| 지표 | 예측 | 근거 |
|---|---:|---|
| assistant tool spans (총) | 1620 – 1640 | recon 실측 1628 (assistant-only). ±10 은 파싱/build 예외 여유. |
| repeat 후보 (구조 게이트 N=2) | 200 – 400 | Toolathlon 108 traces → 177 후보 (5–15%). RB 196 traces × ~1.5% (좀 더 다양한 tool) = 20–50, 그러나 duplicated 130 label 이 이미 재호출 최소 65 pair 시사. 넉넉히 200–400. |
| sha256 게이트 통과 | 40 – 120 | 후보의 20–30% (Toolathlon 32/177 = 18%). |
| **waste 최종 (span 수)** | **40 – 120** | compact 게이트 no-op → sha256 통과와 동일. |
| `Pred_set` 크기 (idx 단위, pair 확장) | 80 – 240 | span 수 × 2 |

### F1 예측 (규약 A 기준)

| 지표 | 예측 범위 | 근거 |
|---|---:|---|
| step-level precision | 0.35 – 0.75 | sha256 게이트가 duplicated (130 pairs) 를 정확히 타격. exploratory 로 오탐 가능성 존재 (재호출 but 정당한 탐색). |
| step-level recall | 0.03 – 0.12 | GT 683 pair 중 duplicated 65 pair 가 이론 상한. abnormal 절반 hit 가정 (25 pair). 실제 hit 30–60 pair → recall 60/683 ≈ 8.8% peak. |
| **step-level F1 (overall)** | **0.05 – 0.20** | 위 곱계산. 논문 Window-to-One 20% F1 대비 낮거나 근접. 절대적으로 precision-recall trade 극단. |

### Trajectory-level 예측

| 지표 | 예측 범위 | 근거 |
|---|---:|---|
| waste-포함 sim 수 | 25 – 60 | Toolathlon 14/108 = 13% → RB 196 × 13% = 25. 최대 30%. |
| both_red 정확 | 22 – 55 | 대부분 with_red=183 트레이스 안에 들 것 (오탐 배제 시). |
| both_non_red | 8 – 13 | 우리 무예측 사이에 non-red 13 개 존재. |
| trajectory-level accuracy | 0.15 – 0.35 | baseline (모두 has_red 예측 시 = 93.4%). 우리는 정밀도 우선이라 baseline 은 못 이김. |

### 판정 기준

**성공 정의**:
- 규약 A F1 이 0.05 이상 (paper 최저 baseline One-to-One 8% 근처 or 초과).
- Precision > 0.35 (Duplicated 특화 게이트로서 primary claim).

**부분 성공**:
- F1 0.03–0.05, precision > 0.4 → precision-oriented gate 로 유효, 논문 recall-oriented baseline 과 상호보완.

**실패**:
- F1 < 0.03 or precision < 0.2 → 어댑터/게이트 재검토. sha256 게이트가 duplicated 를 못 잡는 원인 분석 필요.

### 중단 조건 (§23.5 선례)

1. 기존 216 테스트 회귀 → 멈춤.
2. CC / Toolathlon / OTel / OpenInference 결과 변화 → 멈춤. RB 분기는 독립이어야 함.
3. φ / N / model / sha256 로직 변경 필요 → 즉시 멈춤 (§22.10 규정 재확인).
4. Span 자료구조 확장 필요 → 즉시 멈춤 (Trace.metadata 만 확장 허용).
5. GT `redundant_step_idx` 를 필터 / 변형해서 유리하게 만드는 유혹 → **절대 금지**. §24.3 규약 A 그대로 실행.

---

## §24.6 — 규칙 8 커밋 체인 (사전등록 시각 증명)

이 문서 (§24.1–§24.5) + `field_test/diagnostics/recon_redundancybench.py` = **사전등록 커밋**.
- push → 서버 timestamp 찍힘 → 규칙 8 성립.
- 어댑터 구현 코드 (`src/clew/ingest/redundancy_bench.py` + 테스트 + 평가 스크립트) 는 **push 확인 후** 별도 커밋.
- 결과 (§24.7) 는 실행 후 추가 커밋.
- PR / 머지 는 feat/cc-adapter 배치 (별도 요청).

**커밋 예정 파일**:
- `docs/REDUNDANCY_BENCH.md` (이 문서, 신규)
- `field_test/diagnostics/recon_redundancybench.py` (신규, Q1–Q5 recon)

**커밋 금지 파일**:
- `data/redundancy_bench/**` — `.gitignore: data/` 로 이미 배제.

---

## §24.7 — 재실행 결과 (실행 후 채움)

_사전등록 시점: 미작성. 어댑터 구현 후 이 섹션에 실측 채운다. 예측과 대조._
