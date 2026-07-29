# high_volume 결정론 확장 사전등록 — 리포트 그룹핑 재구조화 (증거 강도 순)

**작성 시각 (UTC)**: 2026-07-29T00:00:00Z
**HEAD 해시**: `f56718d` (origin/main, PR #42 `feat/targeted-writes-split` merge 후)
**선행 merge 필수**: PR #42 (targeted_writes 3-tier 확장) — 이미 origin/main 반영. 로컬 fast-forward 필요.
**작성**: 구현 **전**
**저자**: 클로드 (사전등록자) / 사용자 (승인자)

---

## 선행 근거

- **(b-1) `no_side_effect`** : 30/30 TRUE, 95% 양측 Clopper-Pearson 하한 88.43%
- **(b-2-2) `payload_dependent`** : 30/30 TRUE, 95% 양측 Clopper-Pearson 하한 88.43%
- **(b-2-1) `targeted_writes`** : 28/30 TRUE, 95% 양측 Clopper-Pearson 하한 77.93% (b21 확장 완료)
- **(b-2-3) `high_volume` (본 확장 근거)** : **29/30 TRUE, 95% 양측 Clopper-Pearson 하한 82.78%**
  - FALSE 1건: `[11] survey.tex` — F1 (같은 파일에 내용 동일 쓰기 3회, 세션 sha 종류 1개). (b-2-1) 사전등록 §b F1과 동일 규칙 준용.
  - UNCLEAR 0건, VOL (volume_limited) **0건** (사이 도구 최대 96개 관측, 도구별 요약 렌더로 판정 가능)
  - S 비율 100% (S1=29 + S2=1, 분모 30), UNCLEAR 비율 0%
  - **DETERMINISTIC-EXTENSIBLE 판정** (사전등록 §b.1 임계: UNCLEAR ≤ 6 AND S ≥ 70%)

**증거 문서 (커밋 안 함, `field_test/diagnostics/` 하위)**: `greyzone_b23_feasibility_PREREG.md`, `greyzone_b23_feasibility_RESULTS.md`, `greyzone_b23_sample30_seed55.py/.json/_view.md`, `b23_revert_check.py`, `b23_unnamed_six.py`. 본 사전등록 §선행 근거에 요약 인라인.

### 증거 강도 순위 (본 확장의 순서 근거)

| 층 (변경 후) | 표본 | 95% 양측 CP 하한 | 대상 층 |
|---|---:|---:|---|
| indicated (no_side_effect + payload_dependent) | 30/30 | 88.43% | 최강 |
| high_volume | 29/30 | **82.78%** | 신규 자체 층 (본 확장) |
| writes to other targets (targeted_writes) | 28/30 | 77.93% | 기존 층 |

**함의**: high_volume(82.78%)이 targeted_writes(77.93%)보다 증거가 강함. b21 확장 후 리포트 구조에서 high_volume이 "not established"에 남아있는 배치는 증거 강도와 역전. 본 확장으로 순서 재정렬.

**용어 (본 사전등록 전체 관통)**: "top-level tiers" = 상위 그룹 개수, "aggregate lines" = markdown 집계 블록에 실제로 출력되는 하위 라인 개수. **본 확장 후 top-level tiers = 3** (indicated / high_volume / writes to other targets), **aggregate lines = 4** (indicated 하위 2개 라인 + high_volume 1개 + writes to other targets 1개). "3-tier"로 축약할 때는 top-level 3개를 지칭.

---

## §0 — 절대 불가침

이 확장은 **리포트 표시 레이어의 세분화 + 순서 재정렬**. **탐지·분류·카운트 무변**.

### §0.1 무변 파일
- `src/clew/detect/cascade.py`, `structural.py`, `semantic.py` — 무변
- `src/clew/report/_enrich.py` — 무변 (`_classify_between_window`, `_BW_DECLARATIVE_TOOLS`, `_BW_SIDE_EFFECT_TOOLS`, `_BW_BLACKBOX_TOOLS`, `_BW_CONTEXT_LIMIT` 모두 무변)
- `src/clew/report/json_report.py` — 무변 (JSON 스키마·enum 값 유지)

### §0.2 무변 값
- 5개 `between_window` enum 값 (`declarative` / `no_side_effect` / `payload_dependent` / `targeted_writes` / `high_volume`) — 무변
- Rule V2 우선순위 — 무변. **Rule V3 신설 안 함.**
- Toolathlon 5개 카운트 (**1,226 / 888 / 405 / 248 / 1,024** = 3,791) — 무변
- `waste_span_ids` bit-identical (PRE origin/main `f56718d` = POST sha256 확인) — 무변
- JSON `between_window_counts` 최상위 필드 값 · JSON `waste_details[].between_window` 필드 스키마 — 무변
- 프리즌 파라미터 (φ, N, embedding model) — 무변

### §0.3 변하는 것 (오직 리포트 표시 계층)
- 리포트에서 `high_volume`을 "not established"에서 자체 중간 층으로 분리
- 층 순서를 증거 강도 순으로 재정렬 (indicated → high_volume → writes to other targets)
- per-pair `between_window: high_volume` 라인 문면 갱신 (`_BW_OBS_HIGH_VOLUME` 신규 상수)
- README §"Idempotent sub-classification" 서브섹션 재구조화 + high_volume 검증 결과 추가
- 기존 `_POSSIBLE_CAUSES` · `_CATEGORY_NOTE` · 기타 문면 무변

### §0.4 Rule V3 신설 안 하는 이유 (기록)

(b-2-3) RESULTS §8에서 draft한 Rule V3 (`PROPAGATION_POSSIBLE` 분기)는 도구 간 의미 매핑 (예: `canvas_create_course` ↔ `canvas_list_courses`가 파생 관계라는 지식)이 필요해 결정론 확장 비용이 큼.

선례: (b-2-1) 확장에서도 대상 비교 규칙을 신설하지 않았다. 28/30 표본 검증 + 리포트 그룹핑 재구조화만으로 확장했음 (b21 확장 사전등록 §1). 본 확장도 동일 구조: 29/30 표본 검증 + 리포트 그룹핑만.

**Rule V2 (기존 enum 계산) 그대로 두고, 리포트 표시 계층에서만 층 분리 + 순서 재정렬.** 같은 결과를 그룹핑만으로 얻을 수 있다.

### §0.5 한계 — "not established" 그룹 제거의 숨은 위험

**"not established" 그룹 제거로 모든 idempotent pair가 증거 층에 배정된다.** 이때 미매핑 도구 위험이 리포트에서 보이지 않게 된다.

**Rule V2 2단계 (`_enrich.py` `_classify_between_window`)**: 사이에 `_BW_SIDE_EFFECT_TOOLS`가 0개면 `no_side_effect`로 분류한다. 새 어댑터의 도구가 매핑에 없으면 **실제로 상태를 변경하는 도구여도 "쓰기 없음"으로 읽혀 가장 강한 증거 층 (indicated, 88.43% 하한)에 배정된다**.

- 이는 본 확장이 도입한 결함이 아니라 **Rule V2의 기존 속성**이다.
- 본 확장 전에는 "not established" 그룹이 존재해서 매핑 커버리지 문제를 리포트에서 간접적으로 노출할 수 있었으나, 본 확장 후에는 모든 pair가 검증된 층에 들어가 **가시성이 낮아진다**.
- 현재 검증은 **Claude Code + Toolathlon 한정**. 두 어댑터의 `_BW_SIDE_EFFECT_TOOLS` 커버리지가 알려진 범위 안에서만 결과가 유효.
- **어댑터 확장 시 (Cursor, Continue, 기타) `_BW_SIDE_EFFECT_TOOLS` 매핑 커버리지를 먼저 확인해야 한다.** 확인 없이 확장하면 새 어댑터의 미매핑 쓰기 도구가 `no_side_effect` 층으로 잘못 들어가고, 하한 88.43%가 잘못 적용된다.

**미해결로 남기는 이유**: 매핑 커버리지 자동 감지는 별도 추적 항목 (Rule V2 개선 방향). 본 확장 범위 밖. 여기서는 **한계로 명시적 기록**만 남긴다.

**향후 조치 후보 (본 확장 범위 밖)**:
- 리포트 헤더나 서브섹션 어딘가에 "이 결과는 어댑터 X의 매핑 커버리지에 의존" 메타 라인 추가 (별도 사전등록).
- 새 어댑터 추가 시 `_BW_SIDE_EFFECT_TOOLS` 커버리지 실측 필수화 (테스트 게이트).

**Stage 0 실측 (2026-07-29, 사후 추가).** 위 한계가 현재 데이터셋에서 이미 발생 중임을 실측으로 확인:

- **Toolathlon 매핑 커버리지**: 138 / 523 unique 도구 = **26.4%**
  - (1) `_BW_SIDE_EFFECT_TOOLS`: 62개
  - (2) `_BW_DECLARATIVE_TOOLS ∪ _IDEMPOTENT_TOOLS`: 76개
  - (3) 어느 목록에도 없음 (미매핑): **385개** ← 위험 집합
- **리포트-표시 idempotent pair 중 사이에 (3) 미매핑 도구가 있는 비율:**

  | tier | pairs | with unrecognized in interval | share |
  |---|---:|---:|---:|
  | `declarative` | 1,226 | 428 | 34.9% |
  | `no_side_effect` | 888 | 189 | **21.3%** |
  | `payload_dependent` | 405 | 138 | **34.1%** |
  | `targeted_writes` | 248 | 95 | **38.3%** |
  | **`high_volume`** | **1,024** | **526** | **51.4%** ← 노출 최대 |
  | 총 idempotent | 3,791 | 1,376 | 36.30% |

  ★ 방금 승격시킨 `high_volume` 층이 매핑 커버리지 의존도 최대. 구조적 이유: 사이 도구 ≥ 20 조건이 미매핑 도구 포함 확률을 자연스럽게 높임.

- **표본 실측** (Stage 0 §3):
  - (b-1) seed 47 표본 30건 중 **7건 (23.3%)** 사이에 (3) 미매핑 도구 노출 — 모집단 21.3%와 근사 (편향 없음)
  - (b-2-2) seed 51 표본 30건 중 **12건 (40.0%)** 사이에 (3) 미매핑 도구 노출 — 모집단 34.1%와 근사

  손 라벨링이 편향 없이 모집단 반영 — 표본 신뢰도 확인.

- **판정 원리 재확인**: (b-2-1) 사전등록 §a — *"동기는 트레이스에서 관측 불가하며 판정 질문의 대상이 아니다 … 결과 (쓰기 대상 vs 재조회 대상, sha256 상태) 로 판정한다."*

**함의**:
- **판정 결과 (88.43% / 88.43% / 77.93% / 82.78% 하한) 유효.** 재검증 불필요. 판정 원리가 결과 기반이라 sha256 identity가 TRUE 라벨을 생산했고, 매핑 커버리지와는 독립.
- **좁아지는 것은 enum 라벨의 의미**: `no_side_effect` 등이 뜻하는 바가 broad ("실제로 상태 변경이 없었다")에서 narrow ("**매핑된 도구** 중 상태 변경이 없었다")로 축소.
- 이 축소는 리포트·README에서 사용자가 인지할 수 있어야 하므로 [`docs/COVERAGE_TRANSPARENCY_PREREG.md`](COVERAGE_TRANSPARENCY_PREREG.md)에서 배너·About 섹션으로 노출.

---

## §1 — 변경 내용

### §1.1 그룹핑 재구조화 (top-level tiers 3개 / aggregate lines 4개, 증거 강도 순)

**기존 (b21 확장 후, origin/main `f56718d`):**
```
indicated (2,519): declarative + no_side_effect + payload_dependent
writes to other targets (248): targeted_writes
not established (1,024): high_volume
```

**변경 (증거 강도 순, 본 확장 후):**
```
indicated (2,519, 30/30, 88.43% lower bound):
  - by tool identity: declarative (1,226)
  - by interval scan: no_side_effect (888) + payload_dependent (405)
high_volume (1,024, 29/30, 82.78% lower bound):  ← 자체 층으로 승격
  - state-changing tool present AND ≥ 20 tool spans between
writes to other targets (248, 28/30, 77.93% lower bound):
  - targeted_writes
```

TOTAL 3,791 무변. "not established" 그룹 empty → 헤더 자체 제거.

### §1.2 per-pair 문면 (신규 상수)

`src/clew/report/markdown.py`에 추가:

```python
_BW_OBS_HIGH_VOLUME = (
    "State-changing tools were invoked in a long tool interval "
    "(≥ 20 tool spans between the two calls); this reread's output "
    "is unchanged from the first call."
)
```

**설계 근거**:
- (b-2-3) 판정에서 대상 매칭 규칙은 재도입하지 않는다 (b21 확장에서 이미 안 씀 — 양방향 오류 판명). sha256 동일성 (재조회 출력) 근거로 표현.
- "long tool interval (≥ 20 tool spans)" — high_volume enum 정의를 그대로 문면화. semantic 판단 없음.
- 통계값 (29/30, 82.78%) per-pair 반복 금지 — 집계 블록·README에만.
- 외부 파일 참조 없음 (`docs/*.md` 링크 미부착).

**기존 4분기 → 4분기 (문면만 재배치):**
- `declarative` → `_BW_OBS_DECLARATIVE` (무변)
- `no_side_effect`, `payload_dependent` → `_BW_OBS_NO_CHANGE` (무변)
- `targeted_writes` → `_BW_OBS_TARGETED_WRITES` (무변)
- **`high_volume` → `_BW_OBS_HIGH_VOLUME` (신규 · 위)** (기존엔 `_BW_OBS_NOT_ESTABLISHED`)

`_BW_OBS_NOT_ESTABLISHED` 상수는 **파일에서 제거**. 더는 어느 enum도 이 상수를 참조하지 않음.

### §1.3 markdown 집계 블록 재구조화 (증거 강도 순)

**기존:**
```
- idempotent N — X no state change, W writes to other targets, Z not established
  - indicated, by tool identity: declarative D
  - indicated, by interval scan: no_side_effect NS; payload_dependent PD
  - writes to other targets: targeted_writes TW
    - Validated on Toolathlon: 28/30 hand-labeled TRUE (95% two-sided Clopper-Pearson lower ≈ 77.93%). Two write-then-revert observed.
  - not established: high_volume HV
```

**변경 (증거 강도 순, high_volume 자체 층):**
```
- idempotent N — X no state change, Y high volume, W writes to other targets
  - indicated, by tool identity: declarative D
  - indicated, by interval scan: no_side_effect NS; payload_dependent PD
  - high_volume: HV
    - Validated on Toolathlon: 29/30 hand-labeled TRUE (95% two-sided Clopper-Pearson lower ≈ 82.78%). One same-target repeated write observed.
  - writes to other targets: targeted_writes TW
    - Validated on Toolathlon: 28/30 hand-labeled TRUE (95% two-sided Clopper-Pearson lower ≈ 77.93%). Two write-then-revert observed.
```

카운트 계산 (신규):
```python
no_change_indicated = bw_counts["declarative"] + bw_counts["no_side_effect"] + bw_counts["payload_dependent"]  # 무변
high_volume_count  = bw_counts["high_volume"]         # 신규: 자체 층
writes_other_targets = bw_counts["targeted_writes"]   # 무변
# not_established 변수 제거 (그룹 자체 없음)
```

**★ 순서 재정렬 근거**: 층은 증거 강도 하한 순 (88.43% → 82.78% → 77.93%). 리포트를 읽는 사람이 "덜 검증된 것부터 더 검증된 것" 오해하지 않도록.

**★ 통계 라인 조건부 렌더링**: `high_volume` 라인의 하위 `Validated on Toolathlon:` 는 `high_volume > 0`일 때만. `targeted_writes` 라인의 하위 통계도 `targeted_writes > 0`일 때만 (기존 그대로). waste-0 세션에서 무의미한 통계 라인 방지.

**★ 통계 라인의 "Validated on Toolathlon:" prefix 이유**: 사용자가 자기 트레이스로 CLI를 돌렸을 때 "29/30이 내 데이터 통계인가?"로 오해하지 않게 검증 출처를 명시. 통계 값 자체는 (b-2-3) hand-labeled 사전등록 (`greyzone_b23_feasibility_PREREG.md`) · 결과 (`greyzone_b23_feasibility_RESULTS.md`) 근거.

### §1.4 JSON 리포트 — 무변

`between_window_counts` 최상위 필드 5개 enum 값 그대로.
`waste_details[].between_window` 필드 그대로.

**리포트 그룹핑은 markdown 표시 계층에서만 재구조화**. JSON 스키마 무변, 하위호환 유지.

### §1.5 §3.2 금지 문면 (동결 유지)

기존 §3.2 금지 문면 목록 (`confirmed waste`, `verified waste`, `proven waste`, `waste confirmed`, `waste verified`, `guaranteed waste`, `definite waste`) 유지. 신규 `_BW_OBS_HIGH_VOLUME` 문면에 금지어 없음 (사전 검증 완료 — "long tool interval", "state-changing", "unchanged" 만 사용).

### §1.6 README 서브섹션 업데이트

**기존 §"Idempotent sub-classification" 그룹핑 헤더 (origin/main):**
- `**Grouped as "no state change indicated" in the report:**` — 3개 (declarative, no_side_effect, payload_dependent)
- `**Grouped as "writes to other targets" in the report:**` — 1개 (targeted_writes)
- `**Grouped as "not established" in the report:**` — 1개 (high_volume)

**변경:**
- `**Grouped as "no state change indicated" in the report:**` — 3개 (무변)
- `**Grouped as "high_volume" in the report:**` (신규 헤더 · 신규 위치, "writes to other targets" 앞) — 1개 (high_volume 문면 확장)
- `**Grouped as "writes to other targets" in the report:**` — 1개 (targeted_writes, 무변)
- `**Grouped as "not established" in the report:**` (제거) — 없음

**high_volume 문면 (기존):**
```
- **`high_volume`** — a state-changing tool is present AND ≥ 20 tool spans lie between the calls. Long context makes trace-only judgment unreliable. Not hand-verified.
```

**high_volume 문면 (변경):**
```
- **`high_volume`** — a state-changing tool is present AND ≥ 20 tool spans lie between the calls. **Hand-labeled sample: 29/30 TRUE** (95% two-sided Clopper-Pearson lower bound ≈ 82.78%). One case was a same-target repeated write with unchanged content (a `.tex` file rewritten three times with the same sha256). Grouped separately from `targeted_writes` (28/30, 77.93% lower bound) — its evidence is stronger, so it renders in a higher tier. See [`docs/GREYZONE_B23_EXTENSION_PREREG.md`](docs/GREYZONE_B23_EXTENSION_PREREG.md).
```

**"Report shows the three tiers ..." 문장 (기존, origin/main):**
> Report shows the three tiers on separate lines; the tool does not render a final waste verdict.

**변경:**
> Report shows three top-level tiers rendered as four aggregate lines (indicated is split into "by tool identity" and "by interval scan" sub-lines), ordered by evidence strength (`indicated` 88.43% → `high_volume` 82.78% → `writes to other targets` 77.93%); the tool does not render a final waste verdict.

**Aggregate 라인 무변** (5개 카운트 그대로):
```
Aggregate on Toolathlon (3,791 idempotent pairs):
`declarative 1,226` / `no_side_effect 888` / `payload_dependent 405` / `targeted_writes 248` / `high_volume 1,024`.
```

**"Honest scope for Claude Code users" 문장** — 기존:
> **Honest scope for Claude Code users:** on 28 real Claude Code sessions only **16 pairs land in `idempotent`, and 56% of those fall into `high_volume`** (long intervals between rereads push them past the ≥ 20 threshold). In practice this sub-classification's yield concentrates on multi-tool environments (Toolathlon-like); a single Claude Code session usually leaves most idempotent pairs in the "not established" group. Threshold-20 revisit reserved for a separate pre-registration.

**변경 (마지막 문장 수정 — "not established" 그룹 제거 반영):**
> **Honest scope for Claude Code users:** on 28 real Claude Code sessions only **16 pairs land in `idempotent`, and 56% of those fall into `high_volume`** (long intervals between rereads push them past the ≥ 20 threshold). In practice this sub-classification's yield concentrates on multi-tool environments (Toolathlon-like); a single Claude Code session usually leaves most idempotent pairs in the `high_volume` tier. The 82.78% lower bound applies to the Toolathlon 30-pair hand-labeled sample, not to Claude Code sessions — cross-population inference is a separate measurement. Threshold-20 revisit reserved for a separate pre-registration.

### §1.7 README 예시 output 갱신

**기존 (origin/main line 22-25, b21 확장 이전 형식이 잔존):**
```
- idempotent 1 — 0 with no state change indicated, 1 not established
  - by tool identity: declarative 0
  - by interval scan: no_side_effect 0; payload_dependent 0
  - not established: targeted_writes 1; high_volume 0
- between_window: `targeted_writes` — State change potential not established from the trace alone; see full context.
```

**변경 (본 확장 후 실 세션 재렌더로 갱신):**
- 09d9abe9 세션 재렌더 후 실제 출력 그대로 삽입
- 예상 출력:
```
- idempotent 1 — 0 with no state change indicated, 0 high volume, 1 with writes to other targets
  - indicated, by tool identity: declarative 0
  - indicated, by interval scan: no_side_effect 0; payload_dependent 0
  - writes to other targets: targeted_writes 1
    - Validated on Toolathlon: 28/30 hand-labeled TRUE (95% two-sided Clopper-Pearson lower ≈ 77.93%). Two write-then-revert observed.
- between_window: `targeted_writes` — State-changing tools were invoked in the interval, targeting other resources; this reread's output is unchanged from the first call.
```
(예시 세션은 targeted_writes 1건뿐이므로 high_volume 라인은 0으로 표시. 실제 렌더 결과 그대로 기록.)

---

## §2 — 검증 기준

### §2.1 필수 검증 (모두 통과해야 릴리스)

1. **waste_span_ids bit-identical** — PRE (origin/main `f56718d`) vs POST 각각 Toolathlon 66 파일 스캔.
   기대: `cand_sha256`, `pair_sha256`가 PRE와 정확 동일.

2. **between_window_counts bit-identical** — 5개 enum 값 카운트가 origin/main과 정확 동일:
   `declarative=1226, no_side_effect=888, payload_dependent=405, targeted_writes=248, high_volume=1024`.
   ★ 리포트 표시 계층 변경이 JSON 카운트에 영향 없음을 실증.

3. **전체 pytest 통과** (기존 + 신규 테스트)

4. **신규 테스트 추가**:
   - `test_high_volume_own_wording` — high_volume이 `_BW_OBS_HIGH_VOLUME` 문면을 받는지 (다른 4분기 문면과 배타)
   - `test_no_over_claim_wording` (기존 확장) — 신규 상수 및 렌더 결과 4분기 전부에 §3.2 금지어 없음
   - `test_between_window_counts_stable_post_b23` — 표시 계층 변경이 JSON `between_window_counts` 5개 값에 영향 없음
   - `test_markdown_tier_order_evidence_strength` — markdown 집계 블록에 4개 aggregate line이 다음 순서로 나오는지: (1) `indicated, by tool identity: declarative` → (2) `indicated, by interval scan: no_side_effect ...; payload_dependent ...` → (3) `high_volume:` → (4) `writes to other targets: targeted_writes`. Top-level tiers 3개 (indicated / high_volume / writes to other targets)가 증거 강도 순.
   - `test_no_not_established_tier` — 렌더 결과에 "not established" 그룹 헤더 미표시 (구 문면 제거 확인)

5. **§3.2 금지어 grep guard** — 신규 상수 (`_BW_OBS_HIGH_VOLUME`) · 렌더 결과 4분기 모두

6. **`_BW_OBS_NOT_ESTABLISHED` 상수 제거 확인** — 파일 내 grep으로 삭제 확인

7. **실 세션 렌더** — 09d9abe9 세션 재렌더:
   - per-pair `between_window: high_volume — State-changing tools were invoked in a long tool interval...` 형식 (해당 세션에 high_volume 발생 시)
   - 집계 블록에 4개 aggregate line이 top-level tiers 3개 순서 (indicated → high_volume → writes to other targets) 대로 출력되는지 확인
   - README 예시 output §1.7 예상 형식과 일치

### §2.2 KILL 조건

- 카운트 하나라도 어긋남 → 즉시 롤백. 규칙 변경 아님 (표시 계층 코드 오류로 처리).
- bit-identical 실패 (waste_span_ids 또는 between_window_counts) → 즉시 롤백.
- 금지어 검출 → 문면 정정 후 재검증. 재검증 실패 시 롤백.
- 실 세션 렌더에서 신규 4분기 문면 4개 중 하나라도 미표시 → 롤백.
- "not established" 문자열이 렌더 결과에 남으면 → 롤백 (b23 후 이 그룹은 empty).

---

## §3 — Toolathlon 예측 카운트 (재확인)

변경 후 Toolathlon 렌더에서:

**카테고리 breakdown**: 3,791 idempotent (무변)

**between_window 카운트 (JSON, 무변)**:
- declarative = 1,226
- no_side_effect = 888
- payload_dependent = 405
- targeted_writes = 248
- high_volume = 1,024

**markdown 집계 (top-level tiers 3개 / aggregate lines 4개, 증거 강도 순)**:
- indicated (no state change) = 1,226 + 888 + 405 = **2,519**
- high_volume = **1,024** (신규 자체 층, 82.78% 하한)
- writes to other targets = **248** (77.93% 하한, 순서 후미)
- not established = **없음** (그룹 제거)

**KILL 규칙**: 어느 카운트든 어긋나면 표시 계층 코드 오류. 롤백 후 원인 분석 → 재구현.

---

## §4 — 커밋 체인 (Rule 8, squash 금지)

1. `docs(prereg): b23 high_volume extension pre-registration`
   - 본 문서 `docs/GREYZONE_B23_EXTENSION_PREREG.md` 신규
   - 증거 인라인 (b23 판정 29/30, 82.78%, FALSE 1건 F1, VOL 0)
   - `field_test/diagnostics/` 원본은 커밋 안 함

2. `feat(report): promote high_volume to own top-level tier (3 tiers, 4 lines, by evidence strength)`
   - `src/clew/report/_enrich.py` — **무변** (0 lines)
   - `src/clew/report/json_report.py` — **무변** (0 lines, JSON 스키마 유지)
   - `src/clew/report/markdown.py`:
     - `_BW_OBS_HIGH_VOLUME` 신규 상수
     - `_BW_OBS_NOT_ESTABLISHED` 상수 제거
     - per-pair 4분기 분기: `high_volume → _BW_OBS_HIGH_VOLUME`
     - 집계 블록 재정렬: 4 aggregate lines를 top-level tiers 3개 순서 (indicated → high_volume → writes to other targets) 대로 출력
     - "not established" 라인 제거
     - high_volume 라인 아래 `Validated on Toolathlon: 29/30 ... 82.78%` 통계 (조건부 렌더)

3. `test(report): high_volume tier wording + tier order + not-established removal`
   - `tests/test_between_window.py` 확장 (5 신규 테스트, §2.1 §4)

4. `docs(readme): document (b-2-3) 29/30 result + 3 top-level tiers (4 lines) ordered by evidence strength`
   - README §"Idempotent sub-classification" 서브섹션 재구조화
   - high_volume 서브섹션 확장 (29/30, 82.78%, F1 1건)
   - 그룹 헤더: "no state change indicated" → "high_volume" → "writes to other targets"
   - "not established" 그룹 헤더 제거
   - "Report shows ..." 문장을 "three top-level tiers rendered as four aggregate lines" 형태로 정정 + 순서 근거 (증거 강도 순) 추가
   - "Honest scope for Claude Code users" 마지막 문장 조정
   - README 예시 output (line 15-33) 09d9abe9 재렌더 결과로 갱신

**RESULTS 이관 없음** — per-pair 문면과 README 어느 곳도 `docs/GREYZONE_B23_RESULTS.md` 파일을 참조하지 않음. (b-2-3) 증거는 본 사전등록 `선행 근거` 섹션 인라인으로 충족. `feedback_diagnostics_uncommitted.md` 원칙 유지.

**선행 merge 순서**:
1. 로컬 `main`을 `origin/main` (`f56718d`)로 fast-forward
2. 본 확장 브랜치 (`feat/high-volume-tier` 또는 유사) 생성 및 4 커밋
3. PR 오픈 → 승인 → merge
4. (필요 시) 새 릴리스

---

## §5 — 상시 규칙 (본 확장에서 항구 규칙으로 승격)

**규칙**: 리포트 렌더 문면·구조 (per-pair 라인 · 집계 블록 · 그룹 헤더 · 라인 수·순서) 가 바뀌면 **같은 PR에서 README 출력 예시를 재생성한다.**

**배경 (이 규칙을 지금 박는 이유)**:
- **0.3.2 (between_window 도입)**: 렌더 라인 신설, README 예시 갱신 누락.
- **b21 확장 (targeted_writes 3-tier)**: 집계 블록 3-tier 재구조화, README 예시 라인 22-33 갱신 누락 (본 확장 §1.7에서 발견).

두 번 반복됐으므로 **관행이 아니라 규칙**으로 고정.

**적용 방식**:
1. **문면·라인 수·순서 변경 커밋**과 **README 예시 재생성 커밋**을 같은 PR·같은 브랜치에 함께 포함.
2. 재생성은 실 세션 렌더로 (본 확장의 경우 09d9abe9). 손으로 짜맞추지 않는다.
3. **자동화 (권장)**: README 예시와 실제 렌더를 대조하는 테스트를 추가한다.
   - 후보 방식: 픽스처 트레이스로 렌더한 결과의 특정 라인 (예: `Redundant-invocation candidates:` 시작 블록, `- between_window:` 라인) 을 README 예시 블록과 비교.
   - 픽스처는 결정적이어야 함 (frozen input, frozen expected output).
   - 테스트 이름 (제안): `test_readme_example_matches_current_render`.
4. **테스트 잠금이 즉시 도입되지 않으면**, PR 리뷰 체크리스트에 "README 예시 재생성 여부" 항목을 추가한다 (본 확장 §4 커밋 4에서 처리).

**한계**:
- README에 예시가 여러 개 있으면 어느 것을 대조할지 명시 필요. 본 확장에서는 line 15-33 예시 하나만 대상.
- 픽스처 트레이스가 향후 렌더 변경에 취약. 픽스처 자체를 사전등록해서 동결하는 방식도 고려.

**본 확장 §4 커밋 4에서의 즉시 적용**:
- README 예시 09d9abe9 재렌더 결과로 갱신 (§1.7)
- 테스트 추가 (`test_readme_example_matches_current_render`) — 본 확장에서 도입 시도. 픽스처 설계 여의치 않으면 §4 커밋 3 테스트에 최소 라인 대조 형태로 포함하고, 완전 자동화는 후속 별도 사전등록으로.

---

## §6 — 참조

- `field_test/diagnostics/greyzone_b23_feasibility_PREREG.md` (b-2-3 판단 가능성 사전등록, 로컬)
- `field_test/diagnostics/greyzone_b23_feasibility_RESULTS.md` (b-2-3 판정 결과, 로컬)
- `docs/GREYZONE_B21_EXTENSION_PREREG.md` (선행 확장, targeted_writes 3-tier)
- `docs/GREYZONE_EXPANSION_PREREG.md` (Rule V2, enum 정의, §2.2 그룹핑 원본)
- `memory/feedback_observed_not_confirmed.md` (관측 서술 원칙)
- `memory/feedback_frozen_absolutes.md` (동결 문면)
- `memory/feedback_diagnostics_uncommitted.md` (진단 스크립트 커밋 금지)
- `memory/feedback_mechanical_target_comparison_unreliable.md` (b-2-1 대상 매칭 미신뢰 근거 — 본 확장에서 대상 매칭 재도입 안 하는 이유)

---

_이 문서 이후 사용자 승인 대기. 승인 시 커밋 1 (docs prereg)부터 시작._
