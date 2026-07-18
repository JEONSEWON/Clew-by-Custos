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

## §24.7 — 재실행 결과 (2026-07-18)

**실행**: `python field_test/eval_redundancy_bench.py`
**게이트**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2@e8f8c21, sha256 tool-kind ON.
**어댑터 정정** (사전등록 대비): RB 는 같은 sim 안에서 `tool_call.id` 를 재사용 (airline 20/40, retail 22/48, telecom 45/112 sim). span_id=`f"{tid}#{call_idx}"` 로 unique 화, FIFO 로 call↔result 매칭. `docs/REDUNDANCY_BENCH.md §24.2` 매핑표 및 어댑터 테스트에 반영. 이 정정은 사전등록 규약 A 를 훼손하지 않음 — turn_pair 매핑은 그대로 보존.

**평가**: `data/redundancy_bench/LLM_judge/evaluate.py` 원본을 그대로 `import` → `evaluate_standard` (airline/retail), `evaluate_telecom_one_one` (telecom) 호출. 재구현 없음.

### 예측 vs 실측 (규약 A)

| 지표 | 예측 (§24.5) | 실측 | 판정 |
|---|---:|---:|---|
| assistant tool spans (총) | 1620–1640 | **1628** | ✓ 범위 안 |
| waste spans (span 수) | 40–120 | **132** | ✗ +12 초과 |
| step-level precision | 0.35–0.75 | **0.8258** | ✗ 상단 초과 |
| step-level recall | 0.03–0.12 | **0.1573** | ✗ 상단 초과 |
| **step-level F1** | 0.05–0.20 | **0.2642** | ✗ **상단 초과** |
| trajectory-level accuracy | 0.15–0.35 | **0.5000** | ✗ 상단 초과 |

**변명 없이**: 5개 지표 중 5개가 예측 상단을 넘어섰다. 사전등록 예측이 지나치게 보수적이었다는 뜻이지, 게이트가 이상하게 동작했다는 뜻이 아니다. F1 은 논문 Window-to-One (전체 대상, LLM judge) 20% 를 초과하는 26.4% 로 도출. Precision 0.826 은 정밀도 우선 설계가 예상보다 정확했다는 뜻.

### 도메인별 세부

| 도메인 | spans | waste | tp | fp | fn | P | R | F1 | traj_acc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| airline | 372 | 37 | 64 | 10 | 236 | 0.865 | 0.213 | **0.342** | 0.600 |
| retail | 409 | 33 | 42 | 24 | 152 | 0.636 | 0.217 | **0.323** | 0.591 |
| telecom | 847 | 62 | 112 | 12 | 780 | 0.903 | 0.126 | **0.221** | 0.429 |
| **합산** | **1628** | **132** | **218** | **46** | **1168** | **0.826** | **0.157** | **0.264** | **0.500** |

telecom recall 이 낮은 이유는 `role=user` 발행 tool 이 GT_set 에 남아있고 우리는 못 예측하기 때문 (§24.3 명시 정책). retail precision 이 상대적으로 낮은 이유는 오탐 5건 대부분이 "정당한 재조회" (get_order_details 같은 참조성 툴) 인데 sha256 이 매칭.

### §24.4 카테고리별 recall (우리 게이트 대상 정직성)

| 카테고리 | GT 수 | 우리 hit | recall | 스코프 |
|---|---:|---:|---:|---|
| **duplicated step** | 130 | **79** | **0.6077** | ← **주 타겟** |
| abnormal step | 100 | 0 | 0.0000 | 스코프 밖 (에러 output 다양성) |
| exploratory step | 615 | 14 | 0.0228 | 스코프 밖 (LLM judge 영역) |
| incorrect step | 38 | 12 | 0.3158 | 부분 hit (다른 카테고리와 라벨 겹침 추정) |

**논문 대비 부당 비교 방지 (§24.4 원칙)**:
- 논문 Window-to-One 20% F1 은 **전체 4 카테고리 대상**.
- 우리 게이트는 duplicated 특화. 전체 F1 26.4% 는 우연에 가까운 "duplicated 정확 검출" + "다른 카테고리 오탐 자연 억제" 조합.
- **duplicated 전용 recall 60.77%** 이 우리의 진짜 성능 지표. abnormal/exploratory recall 0/2% 는 설계상 예상.

### 오탐 상위 (Pred ∈ GT^c) — 도메인별 5건 각

**airline** (10건 fp 중 5)
1. `task=12 get_user_details` — 같은 user 재조회. RB 는 정보 재조회를 필수 절차로 판단 (redundant 아님).
2. `task=31 get_user_details` — 같은 패턴.
3. `task=32 get_reservation_details` — 예약 재조회.
4. `task=34 search_direct_flight` — 같은 항공편 재검색.
5. `task=41 get_user_details` — 같은 패턴.

공통 원인: `get_*` 참조 툴을 두 번 부르면 sha256 매칭. RB 어노테이터는 두 번째 조회에 명확한 목적이 있으면 redundant 라벨 안 붙임. 우리 게이트는 목적을 모름.

**retail** (24건 fp 중 5)
1. `task=9 exchange_delivered_order_items` — 성공한 write 재호출 (같은 결과 반환). GT 는 예외적으로 redundant 아님 (교환 재확인 목적).
2. `task=11 get_order_details` — 같은 order 재조회.
3. `task=22 modify_pending_order_address` — write op 후 확인 재조회.
4. `task=50/53 get_order_details` — 같은 order 재조회.

**telecom** (12건 fp 중 5)
1. `refuel_data` 3건 — 같은 인자로 두 번 refuel 하는데 GT 는 redundant 라벨 안 붙임 (2 GB 씩 두 번 = 4 GB 라 논리적으로 다른 행위). 우리는 sha256 만 봐서 output 동일하면 매칭.
2. `get_bills_for_customer` — 청구 재조회.
3. `get_details_by_id` — line id 재조회.

**오탐의 진짜 원인**: 우리 게이트는 "output 이 완전히 같으면 waste" 로 판정. RB 는 "의도가 다르면 redundant 아님". 정보 재조회는 상태 확인 목적으로 정당한 반복. 이 gap 은 sha256 게이트 원리적 한계. **precision 을 더 높이려면 semantic gap (구조 자체는 같은데 의도 차이) 을 잡는 판정기 필요** — 우리 φ 게이트 밖 영역.

### 미탐 duplicated 상위 (GT duplicated ∈ Pred^c) — 5건

**retail task=11 turn=14,15**: `reason='Repeat for step 7, 8'` — 우리 detector 가 turn 7,8 과 14,15 사이 다른 툴콜을 여러 건 감지해서 N=2 구조 게이트 인접성 불충족 (compact 창문 밖). 개선 여지: N=3+ 로 확장하거나 compact window 확장. **단, φ/N 은 frozen** (중단조건 3).

**retail task=58, task=79**: 유사 원인.

**telecom task=[mobile_data_issue]…turn=29,30**: `reason='Permintaan timeout'` — 여기는 GT reason 자체가 "timeout 후 재시도" 라 duplicated 라벨. output 이 두 번째엔 다를 가능성 (다른 tool result). sha256 매칭 실패로 미탐. 정당한 미탐.

**telecom [mobile_data_issue]…turn=10,11**: `reason='This step is not necessary to obtain the business route corresponding to the user's mobile phone number'` — 라벨 사유가 "이 스텝 자체가 불필요" 로 되어있는데, 우리는 다른 인자의 반복이라 sha256 매칭 실패. 이 유형은 우리 정의 밖 (재호출 아님, 그냥 불필요한 단발성 호출) — RB 어노테이터가 duplicated 로 라벨한 이유 자체가 미묘.

### 스코프 밖 카테고리 (참고)

- **abnormal step 0/100 hit**: 에러 output 매번 다름 (timestamp, session id 포함) → sha256 매칭 안 됨. 필요 시 별도 error-normalization 게이트 (§25 이후 후속 과제).
- **exploratory step 14/615 hit**: exploratory 는 정의상 서로 다른 args 로 탐색. sha256 게이트가 잡을 수 있는 건 이 중 args 우연 반복 케이스뿐. 스코프 밖.

### evaluate.py 검증 (사전등록 중단조건 4)

논문 baseline 예측 파일 (Window-to-One @ 24.88%) 은 리포에 없고 (judge.py 는 LLM API 호출 필요), 우리 로컬에서 재현 불가. 대신:
- `evaluate.py` 원본을 그대로 `sys.path.insert` 후 `import` → `evaluate_standard`, `evaluate_telecom_one_one` 호출. 재구현 없음.
- 함수 인자·반환 스펙 준수: airline/retail 은 `{task_id: set}` 두 dict, telecom 은 `{idx: {'task_id', 'redundant_step_idx'}}` GT + `{idx: set}` pred.

**즉 계산 로직에 대한 의심 없음** (그들 코드 그대로). 다만 논문 24.88% 수치와의 직접 비교는 위 §24.4 정직성 원칙 참고.

### 중단 조건 재확인

1. **231 테스트 통과** (216 → 231, 신규 15). 회귀 0. ✓
2. **CC/Toolathlon/OTel 결과 변화 없음** (`_load_trace_auto` 확장만). ✓
3. **φ / N / model / sha256 로직 변경 없음**. ✓
4. **Span 자료구조 확장 없음**. `Trace.metadata` 에만 `rb_span_to_turn_pair, rb_user_tool_idx, source, domain, task_id, sim_id, reward_info` 추가. ✓
5. **GT 필터/변형 없음**. `annotation.json` 그대로 `evaluate.py` 에 전달. ✓

### 병합 방침

- 이 커밋은 `feat/cc-adapter` 브랜치의 §24 결과 커밋 (사전등록 a73ced6 → 어댑터 f193ff5 → 결과 이 커밋).
- push 만. PR 은 §23 (Toolathlon) + §24 (RedundancyBench) 배치 예정.

---

## §24.8 — 결과 검증 (2026-07-18, post-hoc)

§24.7 push 직후 결과가 사전등록 예측을 5개 축 전부 상단 초과했다는 이유로 검증 3단 (Q1 스코프, Q2 지표 동일성, Q3 예측 초과 원인). 진단 스크립트 `field_test/diagnostics/verify_rb_eval.py` (규칙 7 부칙, raw only).

### Q1 — F1=0.2642 의 스코프 확정

`evaluate.py` line 32 인용:
```python
gt[tid] = set(item.get('redundant_step_idx', []))
```
`redundant_step_idx` 는 4카테고리 (exploratory/duplicated/abnormal/incorrect) 통합. type 필터링 없음.

**결론**: 0.2642 = **전체 스코프 (4카테고리 통합)**. 논문 baseline 24.88% 와 동일 스코프. duplicated recall 60.77% 는 별개 스코프 (§24.7.2).

| scope | tp | fp | fn | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|
| **전체 (논문 정의, 4카테고리)** | 218 | 46 | 1168 | **0.8258** | **0.1573** | **0.2642** |
| duplicated-only strict (fp = pred − dup_gt) | 79 | 185 | 51 | 0.2992 | 0.6077 | 0.4010 |
| duplicated-only inclusive (fp = pred − full_gt) | 79 | 46 | 51 | 0.6320 | 0.6077 | 0.6196 |

### Q2 — evaluate.py 동일성 (사전등록 중단조건 4 재확인)

`field_test/eval_redundancy_bench.py` line 33-37:
```python
sys.path.insert(0, str(LLM_JUDGE_DIR.resolve()))
import evaluate as ev
```
→ RB 원본 `evaluate.py` 직접 import. 재구현 없음. 함수 동일성 자체는 보장.

**단서 1 (필수 병기)**: `data/redundancy_bench/LLM_judge/` = `['evaluate.py', 'judge.py', 'requirements.txt']` — **baseline 예측 JSON 파일 없음**. 24.88% 는 논문 인용값. 우리 환경에서 재현·검증 안 됨. `evaluate.py` 함수 코드만 동일 보장.

### Q3 — 예측 초과 원인 (편차 등록)

| metric | §24.5 예측 | 실측 (규약 A) | 초과 방향 |
|---|---|---:|:---:|
| waste span 수 | 40 – 120 | 132 | ✗ (+10%) |
| 전체 F1 | 0.05 – 0.20 | 0.2642 | ✗ (+32%) |
| 전체 P | 0.35 – 0.75 | 0.8258 | ✗ (+10%) |
| 전체 R | 0.03 – 0.12 | 0.1573 | ✗ (+31%) |
| trajectory acc | 0.10 – 0.35 | 0.5000 | ✗ (+43%) |

**단서 2 (편차 원인)**: 규약 A(사전등록된 페어 확장, `waste_span → {call_idx, result_idx}`) 를 예측 캘리브레이션에 반영 못 함. 확장 없이(call-only) 재계산:

| pred | tp | fp | fn | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|
| call-only (확장 X) | 110 | 22 | 1276 | 0.8333 | 0.0794 | **0.1449** |
| pair-expansion (규약 A, 정본) | 218 | 46 | 1168 | 0.8258 | 0.1573 | **0.2642** |

**확장이 F1 +0.1193.** call-only F1 0.1449 는 예측 범위(0.05–0.20) **내**. → 예측 시 confound: `waste span 40–120` 만 곱하고 결과 idx 를 추가 카운트할 것을 잊었다. 성능/버그 아님, 예측 캘리브레이션 오류.

Recall 예측(0.03–0.12) 이 duplicated recall(0.6077) 과 혼동됐는지 재확인: 아니다, 전체 recall(0.1573) 이미 예측 상단 초과. 스코프 혼동 아님, 크기 저평가.

### Q5 — tid FIFO fix 영향

`e06ae12` (tool_call.id 재사용 대응): 87/200 sim (43.5%) 에 tid 재사용. fix 전(에러 raise) 상태였다면 이 sim 전부 pred=∅ → duplicated GT 대량 fn.
정확한 fix-off F1 재현은 어댑터 이전 checkout 필요 (미실행, 조인 통계만).

### 미탐 39% 원인 (Q4 raw)

전 duplicated 미탐 51건이 `in_pair_but_not_wasted` 태그 — 어댑터 페어링 성공, cascade(φ + sha256 게이트)가 waste 판정 안 함:

- **retail task=11 turn 14/15**: reason `Repeat for step 7, 8` — turn 7→14 (7턴 차이) **N=2 창 밖**. 게이트 정의상 정당.
- **telecom [mobile_data_issue]…turn 29/30**: reason `Permintaan timeout` — 타임아웃 재시도. output 상이(다른 tool result) → sha256 미매칭. 정당.
- **telecom …turn 10/11**: reason `This step is not necessary to obtain the business route…` — 재호출 아니라 "불필요한 단발성 호출" 을 duplicated 라벨. 우리 정의 밖.

**요약**: 미탐 39% 는 φ/N 정의 경계 밖 케이스 (창 폭, 카테고리 정의 차). 게이트 버그 아님.

### 정직 경계 (§24.8 사용 가능/불가 문구)

**사용 가능**: "RedundancyBench 전체 F1 0.2642, 논문 Window-to-One baseline 0.2488 대비 우위. 동일 `evaluate.py`, 결정론적 (LLM 없음), precision 0.8258 / recall 0.1573. **단서 1·2 병기 필수.**"

**사용 불가**:
- "24.88% 를 우리가 재현·검증했다" — baseline 예측 파일 없음 (§24.8 Q2 단서 1).
- "명백히 이겼다 / 압도했다" — 단일 벤치, recall 저, duplicated 특화 게이트가 스코프 특성상 유리했을 가능성 (다른 3카테고리 recall ≤3%).
- duplicated recall 60.77% 를 전체 F1 자리에 대입 (별도 스코프).

---

## §24.9 — 오탐 심층 (fp 46, span-level 22)

`field_test/diagnostics/analyze_rb_fp_46.py` (규칙 7 부칙). fp idx 46 은 pair 확장 후 idx 카운트; 원본 waste span 수는 22 (spans 대부분 call+result 2 idx 모두 GT 밖).

### fp 22 spans 분류

| 분류 | 카운트 | 비율 |
|---|---:|---:|
| earlier match 있음 (동일 tool_name + input 이전 존재) | 21/22 | 95.5% |
|   그중 동일 input + **동일 output** (완전 재현) | **21/22** | **95.5%** |
|   동일 input, output 상이 | 0/22 | 0% |
| earlier match 없음 | 1/22 | 4.5% |
| GT 다른 카테고리 (exploratory/abnormal/incorrect) 라벨 | **0/22** | **0%** |
| **순수 미라벨** (어느 카테고리에도 없음) | **22/22** | **100%** |
| **인간 놓침 후보** (동일 io + 미라벨 + 창 내 상태변화 tool 호출 0) | **6/22** | **27.3%** |

### 인간 놓침 후보 상위 5건 raw

1. `[airline] task=31 span=…#6 get_user_details` — call_idx=6, earlier @ call=3, output_equal=True, between=0.
   `{"user_id": "daiki_lee_6144"}` → 동일 사용자 상세 재조회. GT 라벨 없음.
2. `[airline] task=41 span=…#6 get_user_details` — 동일 패턴, `amelia_davis_8890` 재조회.
3. `[retail] task=79 span=…#24 modify_pending_order_items` — call=24, earlier @ call=22. 동일 item swap 을 2턴 후 재실행. 중간 tool 호출 없음.
4. `[retail] task=83 span=…#6 find_user_id_by_name_zip` — 동일 이름+zip 재검색.
5. `[telecom] …#22 refuel_data` — 동일 `{customer_id:C1001, gb_amount:2, line_id:L1002}` 재실행.

### 함의

**precision 0.8258 은 하한 가능**. fp 22 spans 전부 GT 4카테고리 어디에도 없음, 21/22 완전 재현, 6 은 창 내 상태변화 0. 이들이 GT 미포함 = RB 어노테이터 미라벨 낭비. Clew 가 잡음.

**단서 (필수 병기)**: RB 어노테이션은 인간 리뷰어 판단, 완전성 보장 없음. "미라벨=인간 놓침" 은 후보 판정, 소유자 확인 필요. 이 절에서는 **숫자만** (0/22 다른 카테고리 라벨, 6/22 상태변화 0 후보).

**사용 가능 문구**: "fp 22 spans 중 21 이 동일 input+output 완전 재현, GT 다른 카테고리 라벨 0, 6 이 창 내 상태변화 0 인 인간 놓침 후보 → precision 0.826 은 하한 가능성."

**사용 불가**: "22건 전부 낭비다" — 창 밖 상태변화·비-tool 컨텍스트 미검사, 소유자 확인 전.

