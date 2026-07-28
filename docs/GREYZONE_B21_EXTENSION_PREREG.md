# targeted_writes 결정론 확장 사전등록 — 리포트 그룹핑 재구조화

**작성 시각 (UTC)**: 2026-07-28T11:21:06Z
**HEAD 해시**: `6c71f47c9f2bf25fd34785857f57955119e3ae64` (main, `v0.3.2` 이후)
**선행 merge 필수**: `docs/clopper-pearson-label` PR (Clopper-Pearson 라벨 통일; 본 사전등록의 §선행 근거 라벨은 정정본 기준)
**작성**: 구현 **전**
**저자**: 클로드 (사전등록자) / 사용자 (승인자)

---

## 선행 근거

- **(b-1) `no_side_effect`** : 30/30 TRUE, 95% 양측 Clopper-Pearson 하한 88.43% (2.5% each tail)
- **(b-2-2) `payload_dependent`** : 30/30 TRUE, 95% 양측 Clopper-Pearson 하한 88.43%
- **(b-2-1) `targeted_writes`** : **28/30 TRUE, 95% 양측 Clopper-Pearson 하한 77.93%**
  - F2 write-then-revert 실측 2건 : `[08] survey.tex` · `[20] NOTE.md`
  - 각각 파일에 3회 쓰기 (내용 상이) · 마지막 쓰기가 origin sha 로 복원
  - Stage 2 구간 안 변화점 2 개 신호 (다른 어떤 표본에도 인-윈도우 변화 없음)
- L1 SUCCESS 도달 (TIE-BREAKING 28 포함) → 결정론 확장 가능

**증거 문서 (커밋 안 함, `field_test/diagnostics/` 하위)**: `greyzone_b21_PREREG.md`, `greyzone_b21_RESULTS.md`, `greyzone_b21_sample30_seed53_view.md`, `greyzone_b21_sample30_seed53.json`. 이 사전등록 본문에 요약 인라인.

---

## §0 — 절대 불가침

이 확장은 **리포트 표시 레이어의 세분화** 다. **탐지·분류·카운트 무변**.

### §0.1 무변 파일
- `src/clew/detect/cascade.py`, `structural.py`, `semantic.py` — 무변
- `src/clew/report/_enrich.py` — 무변 (`_classify_between_window`, `_BW_DECLARATIVE_TOOLS`, `_BW_SIDE_EFFECT_TOOLS`, `_BW_BLACKBOX_TOOLS`, `_BW_CONTEXT_LIMIT` 모두 무변)

### §0.2 무변 값
- 5개 `between_window` enum 값 (`declarative` / `no_side_effect` / `payload_dependent` / `targeted_writes` / `high_volume`) — 무변
- Rule V2 우선순위 — 무변
- Toolathlon 5개 카운트 (**1,226 / 888 / 405 / 248 / 1,024** = 3,791) — 무변
- `waste_span_ids` bit-identical (PRE=POST sha256 확인, `cand_sha256 = 5c0c94d6…`, `pair_sha256 = 742b51a7…`) — 무변
- JSON `between_window_counts` 최상위 필드 값 · JSON `waste_details[].between_window` 필드 스키마 — 무변
- 프리즌 파라미터 (φ, N, embedding model) — 무변

### §0.3 변하는 것 (오직 리포트 표시 계층)
- 리포트에서 `targeted_writes` 를 별도 중간 층으로 분리
- per-pair `between_window: targeted_writes` 라인 문면 갱신
- README 서브섹션에 `targeted_writes` 검증 결과 (28/30, 77.93%, F2 2건 관측) 추가
- 기존 `_POSSIBLE_CAUSES` · `_CATEGORY_NOTE` 등 기타 문면 무변

---

## §1 — 변경 내용

### §1.1 그룹핑 재구조화 (3층 구조로)

★ **정확한 프레이밍**: "커버리지 66% → 73%" 표현은 부정확 (2층 축 아님). 실제 변화:

**기존 (2층)**:
```
관측 완료 그룹 = declarative + no_side_effect + payload_dependent (2,519)
미확립 그룹    = targeted_writes + high_volume (1,272)
```

**변경 (3층)**:
```
indicated (관측 완료 · 무변)                             : 2,519
  - by tool identity                                     : declarative (1,226)
  - by interval scan (no writes / opaque writes)         : no_side_effect (888) + payload_dependent (405)
targeted_writes (신규 중간 층)                           : 248
  - by interval scan (writes to other targets)           : targeted_writes (248)
not established (감소)                                    : 1,024
  - not established                                       : high_volume (1,024)
```

TOTAL 3,791 무변. **`not established` 가 1,272 → 1,024 로 감소하고, `indicated` 는 2,519 무변 · `targeted_writes` 248 이 별도 중간 층으로 분리됨**.

### §1.2 per-pair 문면 (신규 상수)

`src/clew/report/markdown.py` 최상단에 추가:

```python
_BW_OBS_TARGETED_WRITES = (
    "State-changing tools were invoked in the interval, targeting other "
    "resources; this reread's output is unchanged from the first call."
)
```

**설계 근거**:
- "대상 매칭" 근거는 (b-2-1) 검증에서 양방향 오류로 판명 → 문면에 담지 않음
- 판정 근거는 sha256 동일성 (재조회 출력) → "output is unchanged from the first call" 로 표현
- 집계 통계 (28/30, 하한) 는 집계 블록 · README 에만. per-pair 반복 금지
- 외부 파일 참조 없음 (`docs/*.md` 링크 안 붙임)

**기존 3분기 → 4분기**:
- `declarative` → `_BW_OBS_DECLARATIVE` (무변)
- `no_side_effect`, `payload_dependent` → `_BW_OBS_NO_CHANGE` (무변)
- **`targeted_writes` → `_BW_OBS_TARGETED_WRITES` (신규 · 위)**
- `high_volume` → `_BW_OBS_NOT_ESTABLISHED` (무변)

### §1.3 markdown 집계 블록 재구조화

**기존**:
```
- Redundant-invocation candidates: N idempotent pairs. ...
  - idempotent N — X with no state change indicated, Y not established
    - by tool identity: declarative D
    - by interval scan: no_side_effect NS; payload_dependent PD
    - not established: targeted_writes TW; high_volume HV
  - _Whether these were wasted invocations is a user judgment..._
```

**변경**:
```
- Redundant-invocation candidates: N idempotent pairs. ...
  - idempotent N — X with no state change indicated, W with writes to other targets, Z not established
    - indicated, by tool identity: declarative D
    - indicated, by interval scan: no_side_effect NS; payload_dependent PD
    - writes to other targets: targeted_writes TW
      - Validated on Toolathlon: 28/30 hand-labeled TRUE (95% two-sided Clopper-Pearson lower ≈ 77.93%). Two write-then-revert observed.
    - not established: high_volume HV
  - _Whether these were wasted invocations is a user judgment..._
```

카운트 계산 (신규 상수):
```python
indicated = bw_counts["declarative"] + bw_counts["no_side_effect"] + bw_counts["payload_dependent"]
targeted  = bw_counts["targeted_writes"]
not_established = bw_counts["high_volume"]  # 기존 (targeted + high) 아님
```

**★ 집계에서 증거 축 (declarative vs no_side_effect/payload_dependent) 을 유지하는 이유**:
`docs/GREYZONE_EXPANSION_PREREG.md` §9 (declarative 문면 정정) 와 일관성. declarative 는
도구 이름으로 분기 (`the interval between calls was not examined`), no_side_effect ·
payload_dependent 는 interval scan 근거 (`No state change was observed between the two calls`).
per-pair 문면이 두 증거 축을 구분하는데 집계에서 한 줄로 합치면 §9 정밀도 정정이
뭉개진다. 3층 프레이밍은 상위 (indicated / writes / not established), 증거 축은 하위
(`indicated, by tool identity` · `indicated, by interval scan`) 로 나눠 표현.

**★ 통계 라인의 "Validated on Toolathlon:" prefix 이유**: 사용자가 자기 트레이스로
CLI 를 돌렸을 때 "28/30 이 내 데이터 통계인가?" 로 오해하지 않게 검증 출처를 명시.
통계 값 자체는 (b-2-1) hand-labeled 사전등록 (`greyzone_b21_PREREG.md`) · 결과
(`greyzone_b21_RESULTS.md`) 근거.

### §1.4 JSON 리포트 — 무변

`between_window_counts` 최상위 필드 5개 enum 값 그대로.
`waste_details[].between_window` 필드 그대로.

**리포트 그룹핑은 markdown 표시 계층에서만 재구조화**. JSON 스키마 무변, 하위호환 유지. 기존 4-라벨 소비자 무영향, 기존 5-enum 소비자 무영향.

### §1.5 §3 금지 문면 (동결 유지)

기존 §3.2 금지 문면 목록 (`confirmed waste`, `verified waste`, `proven waste`, `waste confirmed`, `waste verified`, `guaranteed waste`, `definite waste`) 유지. 신규 `_BW_OBS_TARGETED_WRITES` 문면에 금지어 없음 (사전 검증 완료).

### §1.6 README 서브섹션 업데이트

**기존 targeted_writes 문면** (README:86):
```
- targeted_writes — a state-changing tool with a specific target is between the two calls. Not hand-verified; reported as observation.
```

**변경**:
```
- targeted_writes — a state-changing tool with a specific target is between the two calls.
  Hand-labeled sample: 28/30 TRUE (95% two-sided Clopper-Pearson lower bound ≈ 77.93%).
  Two cases were write-then-revert: a `.tex` file and a `.md` file each restored to origin content after intermediate modifications.
  Grouped separately from `no_side_effect` and `payload_dependent` (30/30) in the report because the evidence strength differs.
```

**기존 grouping 문면** (README:81, 85):
- `**Grouped as "no state change indicated" in the report:**` 아래 3개 (declarative, no_side_effect, payload_dependent) 유지
- `**Grouped as "not established" in the report:**` 아래에서 `targeted_writes` 제거 → 신규 그룹 헤더 `**Grouped as "writes to other targets" in the report:**` 신설 (targeted_writes 하나만)
- 기존 "not established" 그룹은 `high_volume` 만 남음

**Aggregate 라인 (README:89)** 무변 (5개 카운트 그대로):
```
Aggregate on Toolathlon (3,791 idempotent pairs):
`declarative 1,226` / `no_side_effect 888` / `payload_dependent 405` / `targeted_writes 248` / `high_volume 1,024`.
```

---

## §2 — 검증 기준

### §2.1 필수 검증 (모두 통과해야 릴리스)

1. **waste_span_ids bit-identical** — PRE (v0.3.2 = `6c71f47`) · POST 각각 Toolathlon 66 파일 스캔.
   기대: `cand_sha256 = 5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4`,
   `pair_sha256 = 742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0`.

2. **between_window_counts bit-identical** — 5개 enum 값 카운트가 v0.3.2와 정확 동일:
   `declarative=1226, no_side_effect=888, payload_dependent=405, targeted_writes=248, high_volume=1024`.
   ★ 리포트 표시 계층 변경이 JSON 카운트에 영향 없음을 실증.

3. **전체 pytest 통과** (267 예상: 253 + 신규)

4. **신규 테스트 추가**:
   - `test_targeted_writes_own_wording` — targeted_writes 가 `_BW_OBS_TARGETED_WRITES` 문면 받는지 (다른 4분기 문면과 배타)
   - `test_no_over_claim_wording` (기존 확장) — 신규 상수 및 렌더 결과 4분기 전부에 금지어 없음
   - `test_between_window_counts_stable_post_regrouping` — 리포트 표시 계층 변경이 JSON `between_window_counts` 5개 값에 영향 없음
   - `test_markdown_indicated_targeted_not_established_split` — markdown 집계 블록에 3층 구조 (indicated / writes to other targets / not established) 라인이 나오는지

5. **§3.2 금지어 grep guard** — 신규 상수 (`_BW_OBS_TARGETED_WRITES`) · 렌더 결과 4분기 모두

6. **실 세션 렌더** — 09d9abe9 세션으로 재렌더:
   - per-pair `between_window: targeted_writes — State-changing tools were invoked in the interval...` 표시 확인
   - 집계 블록에 "writes to other targets: targeted_writes 1" 라인 확인

### §2.2 KILL 조건

- 카운트 하나라도 어긋남 → 즉시 롤백. 규칙 변경 아님 (표시 계층 코드 오류로 처리)
- bit-identical 실패 (waste_span_ids 또는 between_window_counts) → 즉시 롤백
- 금지어 검출 → 문면 정정 후 재검증. 재검증 실패 시 롤백
- 실 세션 렌더에서 신규 4분기 문면 4개 중 하나라도 미표시 → 롤백

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

**markdown 집계 (3층 구조)**:
- indicated (no state change) = 1,226 + 888 + 405 = **2,519**
- writes to other targets = **248** (신규 중간 층)
- not established = **1,024** (감소, 기존 1,272 - 248)

**KILL 규칙**: 어느 카운트든 어긋나면 표시 계층 코드 오류. 롤백 후 원인 분석 → 재구현.

---

## §4 — 커밋 체인 (Rule 8, squash 금지)

1. `docs(prereg): targeted_writes extension pre-registration`
   - 본 문서 `docs/GREYZONE_B21_EXTENSION_PREREG.md` 로 이관 (증거 인라인, `field_test/diagnostics/` 원본은 커밋 안 함)
   - 초기 이관본 (§1.3 markdown 예시가 §9 증거 축을 부분 뭉갬)

2. `docs(prereg): correct §1.3 markdown example — preserve §9 evidence-axis split`
   - §1.3 예시 하위 라인 분리 (`indicated, by tool identity` · `indicated, by interval scan`)
   - 통계 라인에 `Validated on Toolathlon:` prefix 추가 (사용자 데이터로 오해 방지)
   - 설계 근거 노트 추가 (§9 일관성 · 출처 명시 근거)

3. `feat(report): split targeted_writes into own reporting group (3-tier)`
   - `src/clew/report/_enrich.py` — **무변** (0 lines)
   - `src/clew/report/markdown.py` — 상수 `_BW_OBS_TARGETED_WRITES` 신규, per-pair 4분기 분기, 집계 블록 3층 재구조화 (증거 축 분리 유지)
   - `src/clew/report/json_report.py` — **무변** (0 lines, JSON 스키마 유지)

4. `test(report): targeted_writes wording + count stability + 3-tier markdown`
   - `tests/test_between_window.py` 확장 또는 신규 파일 (4 신규 테스트)

5. `docs(readme): document (b-2-1) 28/30 result + F2 revert honesty scope`
   - README 서브섹션 `targeted_writes` 문면 갱신
   - 그룹핑 헤더 3개 (`indicated` / `writes to other targets` / `not established`) 로 재구조화
   - Aggregate 라인 무변 (카운트 5개 그대로)

**RESULTS 이관 없음** — per-pair 문면과 README 어느 곳도 `docs/GREYZONE_B21_RESULTS.md` 파일을 참조하지 않음. (b-2-1) 증거는 본 사전등록 `선행 근거` 섹션 인라인으로 충족. `feedback_diagnostics_uncommitted.md` 원칙 유지.

**선행 merge 순서**: 
1. `docs/clopper-pearson-label` PR (라벨 통일)
2. 본 확장 PR (4 커밋)
3. (필요 시) 새 릴리스

---

## §5 — 참조

- `field_test/diagnostics/greyzone_b21_PREREG.md` (b-2-1 검증 사전등록, 로컬)
- `field_test/diagnostics/greyzone_b21_RESULTS.md` (b-2-1 검증 결과, 로컬)
- `docs/GREYZONE_EXPANSION_PREREG.md` (Rule V2, enum 정의, §2.2 그룹핑 원본)
- `docs/clopper-pearson-label` PR (본 사전등록 하한 값 라벨 정정 선행)
- `memory/feedback_observed_not_confirmed.md` (관측 서술 원칙)
- `memory/feedback_frozen_absolutes.md` (동결 문면)
- `memory/feedback_diagnostics_uncommitted.md` (진단 스크립트 커밋 금지)

---

_이 문서 이후 사용자 승인 대기. 승인 시 커밋 1 (docs prereg) 부터 시작._
