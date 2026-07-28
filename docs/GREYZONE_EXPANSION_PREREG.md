# 결정론 확장 사전등록 — `idempotent` 하위 필드 `between_window`

**작성 시각 (UTC)**: 2026-07-27T12:16:04Z
**HEAD 해시**: `03029b318fd582c9fb7c45a9b507c38ab54c3af9` (main, `v0.3.1` 이후)
**작성**: 구현 **전**
**저자**: 클로드 (사전등록자) / 사용자 (승인자)

**선행 근거**:
- (b-1) 정밀도 30/30 TRUE → `greyzone_b1_precision_RESULTS.md`
- (b-2-2) 정밀도 30/30 TRUE → `greyzone_b22_RESULTS.md`
- 두 결과의 **95% 양측 Clopper-Pearson CI 하한 ≈ 88.43%** (2.5% each tail) — "confirmed" 문면 금지 근거

---

## §0 — 절대 불가침 (사전등록에 명시)

이 확장은 **리포트 분류 레이어의 세분화** 다. 탐지 변경 아님.

### §0.1 무변 파일 (git diff 로 확인)
- `src/clew/detect/cascade.py` — 무변
- `src/clew/detect/structural.py` — 무변
- `src/clew/detect/semantic.py` — 무변

### §0.2 무변 동결 파라미터
- φ = 0.514345 (임베딩 임계)
- N = 2 (최소 반복 수)
- 임베딩 모델 (SentenceTransformer)
- 기존 4개 카테고리 라벨: `error_repeat` / `side_effect` / `idempotent` / `unclassified`

### §0.3 waste_span_ids bit-identical
- 무엇이 waste 인지는 **1비트도 안 바뀐다**.
- 검증 방식: 확장 전(PRE) · 확장 후(POST) 각각 Toolathlon 66 파일 스캔 결과의 `waste_span_ids` 리스트 sha256 이 일치.
- 불일치 시 즉시 중단.

### §0.4 JSON 스키마 하위호환
- **필드 추가만**. 삭제·이름 변경·값 도메인 변경 없음.
- 기존 소비자 (기존 4개 라벨만 소비) 는 계속 동작.

---

## §1 — 변경 내용

### §1.1 스키마 변경

`idempotent` 라벨을 받는 pair 리포트 객체에 하위 필드 하나 추가:

```json
{
  "category": "idempotent",
  "between_window": "no_side_effect"    // ← 신규
}
```

`between_window` 는 **enum, 5개 값**. 다른 3개 카테고리 (`error_repeat`, `side_effect`, `unclassified`) 는 이 필드를 갖지 않는다. 소비자는 `between_window` 가 없으면 종전 스키마로 해석.

### §1.2 Enum 값 정의 (판정 규칙 · 결과 보고 수정 금지)

각 값은 **exclusive**. 판정 순서는 §1.3 참조.

---

#### `"declarative"`

**정의**: 재조회 대상 (candidate) 의 도구가 아래 목록에 속함. 도구 자체가 선언적·멱등이라 "재실행" 의 개념이 흐릿하고 판정 대상이 아님.

**도구 목록 (동결)**:
```
local-claim_done
filesystem-create_directory
```

- `local-claim_done`: agent 가 "완료" 를 선언하는 순수 선언적 마커.
- `filesystem-create_directory`: POSIX `mkdir -p` 성격. 이미 존재하면 no-op.

목록 확장은 별도 사전등록.

---

#### `"no_side_effect"`

**정의**: origin ↔ candidate 사이 span 중 `_SIDE_EFFECT_TOOLS` 에 속하는 tool span 이 **0 개**.

**`_SIDE_EFFECT_TOOLS` (동결)**:  
Toolathlon adapter 기준. 전체 목록은 `field_test/diagnostics/greyzone_b_writesplit.py` 의 `_SIDE_EFFECT_TOOLS` 상수 를 정본. 요약 (범주별 대표):

- filesystem writes: `filesystem-write_file`, `filesystem-edit_file`, `filesystem-move_file`, `filesystem-copy_file`, `filesystem-delete_file`
- github state changes: `github-create_or_update_file`, `github-delete_file`, `github-create_issue`, `github-create_pull_request`, `github-update_issue`, `github-create_repository`, `github-add_labels`, `github-create_comment`, `github-merge_pull_request`, `github-update_pull_request`, `github-create_branch`, `github-close_issue`, `github-add_issue_comment`, `github-push_files`, `github-fork_repository`
- emails send: `emails-send_email`, `emails-send`, `emails-reply`, `emails-forward`
- SQL/logging writes: `snowflake-write_query`, `google-cloud-logging_write_log`
- excel writes: `excel-write_data_to_excel`, `excel-add_sheet`, `excel-format_cells`, `excel-delete_sheet`, `excel-rename_sheet`
- word writes: `word-create_document`, `word-add_paragraph`, `word-format_text`, `word-add_heading`, `word-add_table`, `word-save_document`
- sheets writes: `google_sheet-update_cells`, `google_sheet-append_values`, `google_sheet-clear_range`, `google_sheet-create_spreadsheet`, `google_sheet-add_sheet`
- forms: `google_forms-create_form`, `google_forms-add_question`
- notion writes: `notion-API-post-page`, `notion-API-patch-page`, `notion-API-patch-block-children`, `notion-API-post-database`, `notion-API-post-page-property`, `notion-API-delete-block`, `notion-API-post-database-query`
- woocommerce writes: `woocommerce-woo_products_update`, `woocommerce-woo_products_create`, `woocommerce-woo_orders_update`, `woocommerce-woo_orders_create`
- canvas state changes: `canvas-canvas_enroll_user`, `canvas-canvas_unenroll_user`, `canvas-canvas_create_course`, `canvas-canvas_update_course`, `canvas-canvas_delete_course`, `canvas-canvas_create_announcement`, `canvas-canvas_create_conversation`, `canvas-canvas_upload_file_from_path`, `canvas-canvas_upload_file`, `canvas-canvas_create_assignment`, `canvas-canvas_update_assignment`, `canvas-canvas_create_quiz`, `canvas-canvas_update_quiz`, `canvas-canvas_create_module`, `canvas-canvas_create_page`
- k8s state: `k8s-kubectl_create`, `k8s-kubectl_apply`, `k8s-kubectl_delete`, `k8s-kubectl_replace`, `k8s-kubectl_patch`, `k8s-kubectl_scale`
- code exec / shell: `terminal-run_command`, `local-python-execute`
- playwright interactions: `playwright_with_chunk-browser_click`, `browser_type`, `browser_navigate`, `browser_press_key`, `browser_close`, `browser_scroll`, `browser_hover`, `browser_select_option`, `browser_fill`, `browser_upload_file`, `browser_drag`, `browser_tab_new`, `browser_tab_close`
- rail booking: `rail_12306-buy-tickets`, `rail_12306-book-tickets`, `rail_12306-cancel-tickets`
- pptx writes: `pptx-open_presentation`, `pptx-save_presentation`, `pptx-add_slide`, `pptx-update_slide`, `pptx-delete_slide`

Claude Code adapter 는 별도 매핑 (아래 §1.5).

---

#### `"payload_dependent"`

**정의**: origin ↔ candidate 사이에 아래 목록의 도구 (payload 로 임의 코드/명령/쿼리를 받는 것) 가 **≥ 1 개**. 인자만으로 대상·효과 특정 불가.

**도구 목록 (동결)** — `_BLACKBOX_TOOLS`:
```
local-python-execute
terminal-run_command
snowflake-write_query
google-cloud-logging_write_log
```

목록 확장 (예: kubectl_apply YAML manifest 도 payload 의존) 은 별도 사전등록.

**참고**: `google-cloud-bigquery_run_query` 는 read-only 로 이미 A 하위 read-only 집합에 있음. payload_dependent 판정에는 포함 안 함.

---

#### `"targeted_writes"`

**정의**: origin ↔ candidate 사이에 `_SIDE_EFFECT_TOOLS` 도구가 **≥ 1 개** 있지만, **`_BLACKBOX_TOOLS` 는 0 개**. 즉 모든 사이 side-effect 가 target-in-args (경로·식별자로 대상 특정 가능한 write).

---

#### `"high_volume"`

**정의**: origin ↔ candidate 사이에 side-effect 도구가 **≥ 1 개** 있고 (즉 `no_side_effect` 조건에 걸리지 않고), **총 tool span 수 ≥ 20** 인 경우.

**중요**: side-effect 0 개인 long-read 케이스 (예: 사이에 read 25 개 · write 0 개) 는 `no_side_effect` 로 분류. `high_volume` 은 (b-2) 안 세부 분류로만 부여. 원래 측정 스크립트 (`greyzone_b2_judgeable.py`) 와 정합.

**임계값 20 의 근거**:
- (b-2) 재분해 시 도입한 문턱. 판단 재료 (히스토그램 관측):
  - 사이 tool 20 미만: 판정 재료가 20 개 안팎으로 사람이 훑을 수 있음.
  - 20 이상: judge 입력 길이 · 사람 판독 부담이 급증.
- 실측 분포 (Toolathlon (b-2-3), 1,024 건):
  ```
  [20, 30)  : 236
  [30, 50)  : 362
  [50, 100) : 403
  [100, ∞)  :  23
  ```
- 이 임계값은 **판독 부담 근거의 편의값** 이며, 낭비 여부의 물리적 임계가 아님. 향후 200+ 검증에서 임계 재조정 여지 있음. 재조정 시 별도 사전등록.

### §1.3 Enum 배타 분류 우선순위 (동결 · 실측 정합 확정)

`idempotent` 라벨을 받은 pair 에 대해 아래 순서로 첫 번째 매치가 값이 됨. **이 순서는 사전등록 dry-run (§8) 으로 §4.1 예상 카운트를 정확히 재현하도록 확정**.

```
if cand.tool ∈ {local-claim_done, filesystem-create_directory}:
    between_window = "declarative"
elif not any(s.tool ∈ _SIDE_EFFECT_TOOLS for s in between if s.kind == "tool"):
    between_window = "no_side_effect"
elif n_between_tools >= 20:
    between_window = "high_volume"
elif any(s.tool ∈ _BLACKBOX_TOOLS for s in between if s.kind == "tool"):
    between_window = "payload_dependent"
else:
    between_window = "targeted_writes"
```

**우선순위 근거**:
1. **declarative 최상위**: 도구 identity 로 즉시 결정. between-window 무관.
2. **no_side_effect 두 번째**: 사이 side-effect 도구가 하나도 없으면 그 시점에서 판정 완료. total tool span 수는 무관 (long-read 세션도 side-effect 0 이면 여기).
3. **high_volume 세 번째** (side-effect ≥ 1 전제 하에): 판정 자체가 곤란한 컨텍스트 부담 축을 먼저 배제.
4. **payload_dependent > targeted_writes**: blackbox 가 하나라도 있으면 판정 곤란이 지배. targeted 는 blackbox 부재 조건에서만 부여.

**원래 측정 스크립트와의 정합**:
- `greyzone_b_writesplit.py`: side-effect 0 → (b-1) · side-effect ≥ 1 → (b-2)
- `greyzone_b2_judgeable.py`: (b-2) 안에서 high_volume → payload_dependent → targeted_writes 순 배타 판정
- 이 두 스크립트의 로직을 그대로 하나의 판정 함수로 병합한 것이 위 우선순위.

**§8 dry-run 결과** (§4.1 재현 확인):
- 위 순서 (V2): 1,226 / 888 / 405 / 248 / 1,024 = 3,791 ✅
- 대안 순서 (high_volume 을 no_side_effect 앞에 두는 V1): no_side_effect 671 / high_volume 1,241 → **§4.1 재현 실패**.

### §1.4 어디에 적용되나

`between_window` 는 `category == "idempotent"` 인 pair 리포트에만 부여. `category` 자체의 산출은 무변 (§0.1 detect layer 그대로).

### §1.5 어댑터별 도구 목록 관리

- Toolathlon: `_SIDE_EFFECT_TOOLS` · `_BLACKBOX_TOOLS` · declarative set 은 위와 같이 동결.
- Claude Code: 다른 매핑 필요. 대략:
  - declarative: **없음** (CC 에는 claim_done 계열 도구 없음)
  - side-effect: `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash`, `PowerShell` (Bash 는 blackbox 이기도 함)
  - blackbox: `Bash`, `PowerShell` (임의 명령 실행)

CC adapter 상수 세트도 코드에서 명시적으로 정의하되 이 사전등록의 부록으로 목록 확정 (아래 §1.6).

### §1.6 Claude Code 어댑터용 세트 (동결)

```
CC_DECLARATIVE = {}   # 해당 도구 없음
CC_SIDE_EFFECT_TOOLS = {
    "Edit", "Write", "MultiEdit", "NotebookEdit",
    "Bash", "PowerShell",
    # 아래는 CC MCP 확장 어댑터가 붙는 경우 추후 사전등록으로 확장
}
CC_BLACKBOX_TOOLS = {"Bash", "PowerShell"}
```

`Bash` 는 side-effect 집합과 blackbox 집합에 동시 소속. `_BLACKBOX_TOOLS ⊂ _SIDE_EFFECT_TOOLS` 는 CC 에서도 성립 (§1.3 판정 순서에 영향 없음).

---

## §2 — 검증된 것 / 안 된 것 구분

### §2.1 검증 상태 표

| enum | 어떤 집합 | 검증 상태 | 근거 |
|---|---|---|---|
| `declarative` | Toolathlon (a): claim_done 1,042 + create_directory 184 = 1,226 | **판단 대상 아님** | 도구 정의상 재실행이 낭비/무낭비 논의 대상이 아님 |
| `no_side_effect` | Toolathlon (b-1) = 888 | **검증 완료 30/30 TRUE** | `greyzone_b1_precision_RESULTS.md` (2026-07-27) |
| `payload_dependent` | Toolathlon (b-2-2) = 405 | **검증 완료 30/30 TRUE** | `greyzone_b22_RESULTS.md` (2026-07-27) |
| `targeted_writes` | Toolathlon (b-2-1) = 248 | **미검증** | 별도 사전등록 예정 |
| `high_volume` | Toolathlon (b-2-3) = 1,024 | **미검증** | 별도 사전등록 예정 |

**"검증 완료" 계산 근거**: sample n=30, 30/30 TRUE (100%). **95% 양측 Clopper-Pearson CI 하한 ≈ 88.43%** (2.5% each tail, 관례 통일 — 초기 문서의 "90% CI" 라벨은 오류, 값 자체는 정확). 이 사전등록에서 "확정" 문면 금지의 근거.

### §2.2 리포트에서의 구분 규칙 (동결)

리포트 (READ_ME 요약 / JSON payload / 대시보드) 에서 아래 두 그룹을 **섞어서 표시하지 않는다**:

- **관측 완료 그룹** = `declarative` + `no_side_effect` + `payload_dependent` (합 = **2,519 건** on Toolathlon)
- **미확립 그룹** = `targeted_writes` + `high_volume` (합 = **1,272 건**)

집계 표시 시 두 그룹 카운트를 별도 컬럼/줄로 출력. 하나의 백분율로 합치지 않음.

**예 (금지)**: "idempotent 3,791 (66.4% waste confirmed)" — 왜 안 되는지: `confirmed` 문면 사용 + 검증·미검증 혼합.

**예 (허용)**:
```
idempotent 3,791
  ├─ 2,519 with no observed state change between calls (declarative 1,226; no_side_effect 888; payload_dependent 405)
  └─ 1,272 not established (targeted_writes 248; high_volume 1,024)
```

---

## §3 — 문면 (동결)

관측 서술만. 판정은 사용자.

### §3.1 허용 문안 (영문 정본) — §9 수정 후

**요약 (category-level)**:
```
idempotent 3,791 — 2,519 with no state change indicated, 1,272 not established
```

("observed" → "indicated": declarative 는 도구 이름만으로 분기하므로 관측 서술이 부적절. §9 참조.)

**per-pair — 3 개로 분리** (§9):

`declarative`:
```
Tool is declarative or idempotent by name; the interval between calls was not examined.
```

`no_side_effect`, `payload_dependent`:
```
No state change was observed between the two calls.
```

`targeted_writes`, `high_volume`:
```
State change potential not established from the trace alone; see full context.
```

**대시보드·리포트 header**:
```
Redundant-invocation candidates: {count} idempotent pairs.
No verdict is rendered — refer to context and judge whether each was intentional.
```

### §3.2 금지 문안 (동결 · 코드 grep 가드)

아래 문자열 (대소문자 무시) 을 리포트/문서에서 사용 금지:

```
"confirmed waste"
"verified waste"
"proven waste"
"waste confirmed"
"waste verified"
"guaranteed waste"
"definite waste"
```

리포트 산출 코드에 문자열 상수 grep 테스트 추가:
```python
def test_no_over_claim_wording():
    banned = ["confirmed waste", "verified waste", "proven waste", ...]
    for path in report_source_files():
        text = path.read_text().lower()
        for b in banned:
            assert b not in text, f"금지 문안 '{b}' 이 {path} 에 있음"
```

### §3.3 판정 위임 문장 (항상 병기)

관측 완료 그룹에도 아래 문장 병기:
```
Whether these were wasted invocations is a user judgment; the tool records only the observation.
```

한국어 리포트일 경우:
```
낭비 여부는 사용자 판단입니다. 도구는 관측 사실만 기록합니다.
```

---

## §4 — 예상 결과 (구현 전 예측)

### §4.1 Toolathlon 예측 (동결 · 재현 검증 대상)

`data/toolathlon/hf/*.jsonl` 66 파일 스캔 후 `between_window` 카운트:

| enum | 예측 카운트 |
|---|---:|
| `declarative` | **1,226** |
| `no_side_effect` | **888** |
| `payload_dependent` | **405** |
| `targeted_writes` | **248** |
| `high_volume` | **1,024** |
| **합계** | **3,791** |

**근거**: `data/hf_recon/toolathlon_waste_classify.json` (A=3,791) + `field_test/diagnostics/greyzone_b_writesplit.py` · `greyzone_b2_judgeable.py` 산출.

**KILL 규칙**: 구현 후 위 5개 카운트 중 **하나라도** 예측치와 다르면:
1. 즉시 보고 · 멈춤
2. 어느 규칙이 다르게 해석됐는지 diff 확인
3. 규칙 재검토 → 사전등록 수정판 재작성 (본 문서 폐기)

### §4.2 Claude Code 예측 (범위 예측)

CC 트라젝토리는 idempotent 자체가 소수. 어댑터 도구 세트가 다르므로 정확 카운트는 구현 후에만 확정 가능. 아래는 예측 **범위** 이며, KILL 임계가 아닌 sanity check 로 사용.

**예측 (§1.6 CC 세트 기준)**:
- 총 idempotent: **30 ~ 200 pairs** (§0 README 앵커: CC waste ~ 0.80% of tool spans, Toolathlon 대비 1/3).
- 분포 예측:
  - `declarative` : **0** (CC 에는 claim_done 계열 없음)
  - `no_side_effect` : **60 ~ 80%** (Read/Read 반복이 CC 낭비 주 패턴)
  - `payload_dependent` : **10 ~ 30%** (Bash 가 사이에 있으면)
  - `targeted_writes` : **5 ~ 15%** (Edit/Write 가 사이에 있으면)
  - `high_volume` : **0 ~ 5%** (CC 트라젝토리 길이가 대체로 20 미만)

**Sanity check 실패 조건 (KILL 아님, 재검토 트리거)**:
- `declarative` > 0 (CC 에 그런 도구 없어야 함) → §1.6 세트 오류
- `high_volume` > 20% (CC 가 그렇게 길면 스캔 대상 자체 재검토)
- 총 idempotent > 500 (예측 상한 3배 이상, 규칙 오해석 의심)

---

## §5 — 검증 기준

### §5.1 필수 검증 (모두 통과해야 릴리스)

1. **waste_span_ids bit-identical (§0.3)**  
   PRE (main HEAD `03029b3`) · POST (확장 브랜치) 각각 Toolathlon 66 파일 스캔.
   ```
   PRE_hash  = sha256(sorted(waste_span_ids_pre))
   POST_hash = sha256(sorted(waste_span_ids_post))
   assert PRE_hash == POST_hash
   ```
   또한 pair 별 (`(origin_span_id, cand_span_id)`) 리스트 sha256 도 동일해야 함.

2. **전체 테스트 통과**  
   `pytest` (CI 실행되는 세트) all green. 신규 테스트 3개 이상 추가:
   - `test_between_window_enum_exclusive` — 예측 카운트 5개 재현
   - `test_between_window_priority_order` — §1.3 우선순위가 지켜지는지
   - `test_no_over_claim_wording` — §3.2 금지 문안 grep

3. **§4.1 예측 카운트 재현**  
   Toolathlon 66 파일 스캔 결과 5개 값이 예측치와 정확히 일치.

4. **waste 0 건 케이스 정상 렌더**  
   idempotent 가 0 인 트라젝토리에서도 리포트 출력이 정상 (필드 없음 또는 empty enum). 회귀 테스트 추가.

5. **JSON 스키마 하위호환**  
   기존 4개 라벨만 소비하는 JSON consumer 가 계속 동작:
   - `between_window` 없는 카테고리에도 필드 자체가 없어야 함 (null 도 안 됨)
   - 기존 필드 이름·타입 · 값 도메인 모두 그대로

### §5.2 KILL 조건 (즉시 중단)

- **§5.1 #1 (bit-identical) 실패** → 탐지 레이어 오염. 즉시 롤백.
- **§5.1 #3 (예측 카운트 불일치)** → 규칙 재검토 · 사전등록 재작성. 이 사전등록은 폐기.
- **§3.2 금지 문안이 코드/문서 어디에라도 남아 있으면** → 정리 후 재검증.

### §5.3 승인 프로세스 (Rule 8 준수)

1. 이 사전등록 문서를 브랜치 `prereg/greyzone-expansion` 로 push.
2. PR URL 을 사용자에게 제출 · **정지**.
3. 사용자 승인 후 두 번째 커밋 (구현 코드).
4. 세 번째 커밋 (검증 산출물 · docs).
5. squash / rebase 금지.

---

## §6 — 범위 밖 (명시)

이 사전등록에 포함 안 됨 · 별도 사전등록 필요:

- **(b-2-1) `targeted_writes` 248건 검증**  
  → 별도 표본 30 판정. 원칙: FILE 재조회 + 사이에 다른 파일 write 는 무관 · DIR 재조회 + 사이 write 는 관측 손실 가능.

- **(b-2-3) `high_volume` 1,024건에 judge 적용**  
  → 결정론으로는 못 넘긴다. LLM judge 부착 여부는 별도 사전등록. 판정 자체가 곤란한 케이스가 상당수 (표본 30 관측 시 상당수 UNCLEAR 예상).

- **README · PyPI · 릴리스 노트 반영**  
  → 별도 릴리스 사전등록 (버전 넘버링 · 변경 로그 · 홍보 문면 별도 승인).

- **대시보드 UI**  
  → **금지** (`project_urgent_improvements_2026_07.md` 명시). 이 사전등록도 UI 만들지 않음.

- **`_SIDE_EFFECT_TOOLS` · `_BLACKBOX_TOOLS` · declarative 세트 확장**  
  → 각각 별도 사전등록. 이번 릴리스는 §1.2 목록으로 동결.

- **CC adapter 실측 재현**  
  → §4.2 는 예측이지 KILL 기준 아님. CC 예측이 어긋나도 이 릴리스는 진행. 다만 재검토 트리거.

- **F5 (server caching) 대안 가설의 대규모 반박**  
  → `(b-1) RESULTS §4` 로 부분 반박. 대규모 (200+) 재검증에서 재확인.

---

## §7 — 규율 (동결)

1. **본 문서는 사전등록. 구현 금지.** 사용자 승인까지 코드 변경 없음.
2. **문면·도구 목록·임계값은 위에 확정된 값 이후 수정 금지.** 구현 결과 보고 수정 시 이 사전등록 폐기하고 재작성.
3. **산출물은 커밋 안 함** (`field_test/diagnostics/` 하위) — 이 사전등록 자체와 검증 산출물은 예외 (`docs/` 이관 후 PR).
4. **CLI 는 판정 안 함**. 관측만.
5. **결과 보고와 사전등록 사이에 발견된 미묘한 이슈** (예: `hidden` volatility 등) 는 이 사전등록 수정으로 처리 안 함. 새 사전등록으로 처리.

---

## §8 — Dry-run 검증 기록 (사전등록 정합성)

**검증 시각 (UTC)**: 2026-07-27T12:23:00Z (§1.3 초안 이후 · 승인 전)
**스크립트**: `field_test/diagnostics/greyzone_expansion_dryrun.py`
**목적**: 사전등록 §1.3 우선순위가 §4.1 예상 카운트를 재현하는지 실측. 구현 아님 — 분류 함수만 counting 목적으로 실행.

### §8.1 이슈 발견

사전등록 §1.3 초안 (Rule V1: high_volume 을 no_side_effect 보다 앞에 둠) 은 `(b-1) 888` 을 재현 못 함. 실측:

| enum | 예상 | Rule V1 (초안) | Rule V2 (수정판) |
|---|---:|---:|---:|
| declarative | 1,226 | 1,226 ✅ | 1,226 ✅ |
| no_side_effect | 888 | **671 ❌ (-217)** | 888 ✅ |
| payload_dependent | 405 | 405 ✅ | 405 ✅ |
| targeted_writes | 248 | 248 ✅ | 248 ✅ |
| high_volume | 1,024 | **1,241 ❌ (+217)** | 1,024 ✅ |
| TOTAL | 3,791 | 3,791 | 3,791 |

**상이 pair**: 정확히 217 건. 전부 `high_volume → no_side_effect` (V1 → V2 방향). 특징 — side-effect 도구 0 개 인데 total tool span ≥ 20 (사이에 read 20 ~ 40 개). Rule V1 은 이 pair 를 total tool 축으로 먼저 판정해 high_volume 으로 흡수 → (b-1) 정의 위반.

### §8.2 원인 분석

원래 측정 스크립트 (`greyzone_b_writesplit.py` + `greyzone_b2_judgeable.py`) 는 두 단계:

1. side-effect 0 개 → (b-1) 로 분리 (total tool 무관)
2. side-effect ≥ 1 개인 (b-2) 안에서만 high_volume · payload_dependent · targeted_writes 세부 분류

사전등록 §1.3 초안은 이 두 단계를 하나로 병합하며 side-effect 축을 total tool 축보다 뒤에 뒀음. (b-2-3) high_volume 이 원래 정의부터 "side-effect ≥ 1 전제" 였다는 점을 사전등록 정의 §1.2 에서 명시적으로 표현하지 못한 것이 근본 원인.

### §8.3 수정

**§1.2 `high_volume` 정의** 앞에 "side-effect ≥ 1 이면서" 조건 명시.

**§1.3 우선순위** 를 Rule V2 로 확정:
1. declarative (도구 identity)
2. **no_side_effect (side-effect 0 이면 여기 · total tool 무관)**
3. high_volume (side-effect ≥ 1 + total tool ≥ 20)
4. payload_dependent (side-effect ≥ 1 + blackbox 있음)
5. targeted_writes (side-effect ≥ 1 + blackbox 없음)

### §8.4 규율 준수

- 이 수정은 사전등록 본문의 결과 판정 기준 (§5 검증·KILL) 을 바꾸지 않는다.
- 수정 사유: 사전등록 §4.1 예상 카운트 · 기존 실측 (`data/hf_recon/toolathlon_waste_classify.json` A=3,791 + (b-1)·(b-2) 하위 카운트) 와의 정합성 확보.
- 사용자 지시 (구현 전 dry-run 요청) 에 따른 사전 정합성 검증. 규율 위반 없음.
- 승인 전 문서 정합성 조정으로 취급.

### §8.5 재현 서술

Toolathlon 66 파일에 대해 §1.3 Rule V2 우선순위를 적용하면 위 §8.1 표의
**Rule V2 열이 정확히 재현** 된다. Rule V1 을 적용하면 no_side_effect ·
high_volume 두 자리에서 정확히 217 pair 가 어긋난다 (같은 표 V1 열).

계산 단위: `_A_DECLARATIVE ∪ _A_IDEMPOTENT_WRITE ∪ _A_READ_ONLY` (subset A,
Toolathlon 판정 §5.2) 총 3,791 pair.
스캔 범위: `origin.end_time < s.start_time < cand.start_time` · tool span 만.

---

## §9 — §3.1 문면 정합성 조정 (사전등록 정합성)

**조정 시각 (UTC)**: 2026-07-28T00:00:00Z (§3.1 초안 이후 · 승인 후 · 구현 중)
**목적**: `declarative` per-pair 문면이 관측 서술 취지 (§3) 와 어긋난다는
사용자 지적에 대한 정합성 조정. 구현·검증·카운트 무변.

### §9.1 이슈 발견

`declarative` enum 은 §1.3 Rule V2 1 단계에서 도구 이름만으로 분기하며
`between_tools` 스캔이 발생하지 않는다. §3.1 초안은 declarative 에도
"관측 완료 3 값" 공통 문면 (`No state change was observed between the two calls.`)
을 부여했으나, 이는 **관측하지 않은 것을 관측했다** 고 서술하는 셈이 된다.
`memory/feedback_observed_not_confirmed.md` 원칙 (관측 서술만) 위반.

### §9.2 원인 분석

§3.1 초안은 §2.2 "관측 완료 그룹" 그룹핑 (3 값) 을 그대로 per-pair
문면에 상속. 그러나 그룹 라벨은 **"판정 위임 가능성"** 축이고, per-pair
문면은 **"어떤 증거로 그렇게 말하는가"** 축이라 축이 다르다.
declarative 는 판정 위임 가능성은 그룹과 같으나 증거 종류는 다름
(tool identity vs interval scan).

### §9.3 수정

**§3.1 per-pair 문면을 3 개로 분리**:

| enum | 증거 축 | 문면 |
|---|---|---|
| `declarative` | tool identity | `Tool is declarative or idempotent by name; the interval between calls was not examined.` |
| `no_side_effect`, `payload_dependent` | interval scan (no side-effect / blackbox) | `No state change was observed between the two calls.` |
| `targeted_writes`, `high_volume` | interval scan (writes present) | `State change potential not established from the trace alone; see full context.` |

**§3.1 category-level summary 도 조정** — `"observed"` → `"indicated"` (두 증거 축을 모두 덮음):
```
idempotent 3,791 — 2,519 with no state change indicated, 1,272 not established
```

**집계 하위 라벨도 증거 축으로 분리**:
- by tool identity: `declarative`
- by interval scan: `no_side_effect`, `payload_dependent`
- not established: `targeted_writes`, `high_volume`

### §9.4 규율 준수 근거

- **선례**: §8 (Rule V2 확정) 도 폐기가 아니라 §8 기록 + 수정으로 처리. 그때는
  분류 규칙 변경 (217 pair 이동). 이번은 문장 하나이고 카운트·로직 영향 0.
- **동결 원칙 취지 부합**: 동결 목적은 "결과를 보고 유리하게 바꾸는 것" 방지.
  이 수정은 (a) 결과 산출 전, (b) 카운트 무변, (c) 주장을 **더 보수적** 으로
  (관측했다 → 관측 안 함) 만드는 방향이므로 원칙에 부합.
- **금지 문면 (§3.2) 재확인**: 신규 문면 3 개 모두 §3.2 금지 목록에 없음 —
  `confirmed`, `verified`, `proven`, `guaranteed`, `definite` 미사용.
- **§5 검증 기준·KILL 조건 무변**. §4.1 예상 카운트 무변.

### §9.5 승인 프로세스

사용자 승인 후 문서 조정 → 구현 계속. 재승인·재사전등록 아님.

### §9.7 기존 `_POSSIBLE_CAUSES` 텍스트 §3.2 정합 조정

`src/clew/report/markdown.py` `_POSSIBLE_CAUSES` 상수의 한 문장:
```
For Bash requeries the state between calls is not directly observable from the
trace; treat those as *state change uncertain* rather than confirmed waste.
```
원 문장 취지는 "`confirmed waste` 라고 부르지 마라" 로 §3.2 정신과 정합.
그러나 마크다운 리포트는 훑어 읽히므로 부정 구문 안 금지어가 단독으로
눈에 들어올 위험이 있고, §3.2 grep 가드 (신설) 도 부정 구문 여부를
구분하지 않음.

**수정**:
```
For Bash requeries the state between calls is not directly observable from the
trace; treat those as *state change uncertain* — the tool does not render a
final waste verdict.
```

`verdict` 표현은 `_BW_HEADER_NO_VERDICT` 와 일관. **탐지·카운트·판정 기준
무변**. 신규 가드가 기존 텍스트에 적용된 결과.

### §9.8 (신설) POST 검증 결과 인라인

**커밋 2 완료 후 실측 (구현·테스트·검증 완료 시점)**:

**§0.3 waste_span_ids bit-identical 검증**:
- PRE (main HEAD `03029b3`) · POST (구현 브랜치) 각각 Toolathlon 66 파일 스캔
- 결과 정확 일치:
  - `cand_sha256 = 5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4`
  - `pair_sha256 = 742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0`
  - 파일 수 = 66, 트라젝토리 수 = 6,780, 총 waste pair 수 = 8,042
- 판정: PASS. detection layer 무변 확인.

**§4.1 카운트 재현 검증**:
- 구현된 `_classify_between_window` 를 Toolathlon 66 파일 · subset A pair 3,791 건
  에 적용한 실측:
  - `declarative` = 1,226 (expected 1,226) ✅
  - `no_side_effect` = 888 (expected 888) ✅
  - `payload_dependent` = 405 (expected 405) ✅
  - `targeted_writes` = 248 (expected 248) ✅
  - `high_volume` = 1,024 (expected 1,024) ✅
  - TOTAL = 3,791
- 판정: PASS. §4.1 KILL 조건 없음.

**§5.1 필수 검증 항목별 통과**:
| 항목 | 결과 |
|---|---|
| #1 waste_span_ids bit-identical | ✅ (위 sha256) |
| #2 전체 테스트 통과 | ✅ 253 passed |
| #2 신규 테스트 3+ 추가 | ✅ 14 tests (`tests/test_between_window.py`) |
| #3 §4.1 예측 카운트 재현 | ✅ (위 5개 값) |
| #4 waste 0 건 케이스 정상 렌더 | ✅ (`test_no_waste_case_renders_without_crash`) |
| #5 JSON 스키마 하위호환 | ✅ (`between_window` field present iff idempotent, not null) |
| §3.2 금지 문면 grep 가드 | ✅ (소스 + 렌더 결과 모두 무검출) |

**§4.2 CC 28-세션 sanity check 결과**:
- 크래시 0 / 28 세션 ✓
- 총 waste pair (tool, sha256-eq) = 44
- 카테고리: error_repeat 1 / side_effect 6 / idempotent 16 / unclassified 21
- idempotent 16 pair 의 between_window 분포:
  - `declarative` = 0 (0.0%) ✅ CC 세트에 없음이 확인됨 (§1.6 세트 오류 없음)
  - `no_side_effect` = 4 (25.0%)
  - `payload_dependent` = 1 (6.2%)
  - `targeted_writes` = 2 (12.5%)
  - `high_volume` = 9 (56.2%) ★ **FLAG (KILL 아님)**
- 총 idempotent 16 < 500 ✅ (규칙 오해석 sanity check 통과)

★ **CC high_volume FLAG 기록**: CC 세션은 재조회 간격이 길어 (도구 20+ 개
개재) high_volume 이 56.2%. 즉 이 확장의 실익은 다도구 환경 (Toolathlon 같은)
에 집중되며 CC 단일 세션에는 제한적. §4.2 예측 (0-5%) 과 어긋나며, 향후
별도 사전등록으로 임계값 20 재검토 대상. 이 릴리스는 §6 규정 (§4.2 는 KILL
아님) 에 따라 진행.

### §9.6 JSON `note` 필드 문면 추가 (신규 텍스트)

`src/clew/report/json_report.py` 의 report 최상위 `note` 필드는 §3 동결
범위 밖 (§3.1 은 category-level / per-pair / dashboard header / judge
delegation 4 개 wording 만 동결. `note` 필드 자체는 기존 텍스트도 §3 밖).

이 구현에서 `note` 에 아래 한 줄 신규 추가:
```
between_window records how the interval was classified; no state-change verdict is rendered.
```

**근거**:
- markdown 의 §9 정밀도 조정 (declarative 는 관측 아니라 도구 identity
  기반) 과 일관 — "records observation only" 는 declarative 를 관측 서술로
  잘못 덮음.
- "records how the interval was classified" 는 declarative (tool identity)
  · no_side_effect / payload_dependent (interval scan) · 미확립 (interval
  scan · 결론 유보) 세 경우를 모두 정확히 덮음.
- 금지 문면 (§3.2) 없음 (`confirmed` / `verified` / `proven` / `guaranteed`
  / `definite` 미사용).

---

## §10 — 참조

- `greyzone_b1_precision_PREREG.md` / `greyzone_b1_precision_RESULTS.md`
- `greyzone_b22_PREREG.md` / `greyzone_b22_RESULTS.md`
- `greyzone_b_writesplit.py` / `greyzone_b2_judgeable.py` — 도구 세트 정본
- `docs/TOOLATHLON.md` §23 — 어댑터 매핑
- `data/hf_recon/toolathlon_waste_classify.json` — A=3,791 확정
- `memory/feedback_frozen_absolutes.md` — 동결 문서 절대값 원칙
- `memory/feedback_no_hypothetical_case_judgment.md` — 가상 케이스 판정 금지
- `field_test/diagnostics/greyzone_expansion_dryrun.py` — §8 dry-run 스크립트 (재현 명령 §8.5)

---

_이 문서 이후 사용자 승인 대기. 승인 시 두 번째 커밋 (구현). 승인 전 코드 변경 없음._
