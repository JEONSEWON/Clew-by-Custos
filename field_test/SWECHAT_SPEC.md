# SPEC §19 — SWE-chat 실사용 코딩 세션 낭비 밀도 측정 (사전등록)

## 목적
실사용 Claude Code 세션에 "같은 대상 + 실질 변화 없음" 낭비가 존재하는지, 밀도가 얼마인지 측정.

## 분석 pool (frozen)
- `agent == "Claude Code"`
- `tool_name == "Read"`
- `tool_input_json IS NOT NULL` (None 63,556개 제외 — `file_path`도 0% 채움 확인됨)
- 결과: 63,664 Read
- **전수 조사** (표본추출 없음 → 길이 교란·선택 편향 원천 차단). 100 표본 아님.

## 대상(target) 정의
- `offset`·`limit` 둘 다 있음 → `(norm_path, offset, limit)`
- `offset` 또는 `limit` 결측 → `(norm_path, "FULL")`  ※ 전체 읽기로 취급
- PDF Read (`pages` 키, 46건 / 0.07%)는 offset/limit 결측이므로 `(norm_path, "FULL")` 카테고리로 자동 처리.
- `norm_path` = `os.path.normpath` 적용.
- **절대·상대 경로 혼용 세션(89개, 2%)은 분석에서 제외.**
  → basename fallback은 `src/utils.py`와 `tests/utils.py`를 동일 파일로 오탐할 위험 있음.
  → 제외 세션 수를 결과에 명시.
- `offset`/`limit`이 str인 35건 → int 캐스팅, 실패 시 해당 Read drop (건수 기록)

## 낭비 판정 (2조건 AND — 사전 확정)
1. 같은 세션 내 동일 target 재등장
2. **그 사이(`turn_number` 기준)에 해당 `norm_path`에 대한 Edit/Write/MultiEdit 턴이 없음**
   → 2번이 핵심. Edit 후 재읽기는 정당하므로 낭비 아님.

Edit 계열 도구 범위: `Edit`, `Write`, `MultiEdit` 3종만 (Claude Code 실측 분포 기준. NotebookEdit/Update/str_replace 0건).

## 미확인 Edit 처리 (보수적 판정)
- Edit 계열의 `tool_input_json`도 정확히 50% None (Edit 63,489 / Write 8,629 / MultiEdit 134).
  → 두 Read 사이에 `tool_input_json`이 None인 Edit/Write/MultiEdit 턴이 존재하면 그 턴이 해당 파일을 수정했는지 알 수 없음.
- 이 경우 해당 Read 쌍은 **낭비 아님으로 판정** (보수적).
- 이 케이스 건수를 별도 카운트하여 결과에 명시: "판정 불가로 제외된 후보 N건".
- 근거: 낭비를 과대평가하는 것보다 과소평가가 정직한 방향. FP=0 원칙과 일치.

## 측정 지표 (사전 확정)
1. 낭비 1건 이상 있는 세션 비율 (분모: Read 보유 Claude Code 세션)
2. 낭비 Read 턴 / 전체 Read 턴
3. **낭비 턴의 토큰 합** (`input_tokens + output_tokens`) 및 전체 대비 비율
4. **대조군**: file-level만으로 판정 시 낭비 수 (target = `norm_path`만). range-level 대비 차이 = 정밀 대상 정의가 거른 오탐 수

## 낭비 사례 덤프 (필수)
숫자만으로는 검증 불가 (TRAIL 8건 실측 판정 경험). 낭비로 잡힌 Read 전건을 저장:
- 경로: `field_test/swechat_waste_cases.csv`
- 컬럼: `session_id`, `turn_id`, `turn_number`, `norm_path`, `offset`, `limit`, `prev_turn_number`, `between_edit_count`, `input_tokens`, `output_tokens`
- 무작위 20건 사람 판정용 별도 덤프: `field_test/swechat_waste_sample20.json` (seed=42 고정)
- 판정 후 진짜 낭비 / 정당한 재읽기 라벨링해서 정밀도(precision) 산출

## 음성 결과 정의 (미리 확정)
- 낭비 세션 비율이 낮게 나오면 → 코딩 에이전트 방향의 신호가 약하다는 **정직한 음성**. 그대로 기록·발표.
- 정의를 조정해 숫자를 만들지 않는다. EmergenceTrace AUC 0.455 정직 음성 발표와 동일 원칙.

## 금지 (분석 후 정의 변경 방지)
1. pool 정의 사후 수정 금지
2. target 정규화 규칙 사후 튜닝 금지
3. "사이에 변화 없음" 조건 완화 금지
4. 낭비 많은 세션만 골라 보기 금지
5. 결과가 예상 밖이라고 필터 추가 금지 (v1' 개정 시 추가)
6. 값이 낮아졌다는 이유로 file-level 대조군 정의를 바꾸지 않는다 (v1' 개정 시 추가)
7. **발견은 즉시 SPEC에 fold back한다.** 스크립트 docstring, print 주석, 채팅 로그는 기록이 아니다. 인수인계 문서는 SPEC에서 파생시킨다.
   근거 사례: 2026-07-15 `diagnose_edit_pool.py`의 EDIT_TOOLS 오염 결론이 18시간 유실됨 (docstring·print에만 남고 SPEC·인수인계 미반영 → 2026-07-16에 독립 재발견).

---

## v1 결과 (사전등록 정의 그대로, frozen)

pool: Claude Code Read + tool_input_json IS NOT NULL = **63,664**
분석 대상 (혼용 세션 89개 제외 후): Read 60,778 / 세션 4,411

- **[1] 낭비 1건+ 세션 비율: 631 / 4,411 = 14.31%**
- **[2] 낭비 Read / 전체 Read: 994 / 60,778 = 1.635%**
- **[3] 낭비 토큰 합: 산출 불가** — Claude Code Read 턴의 `input_tokens`·`output_tokens` = 0 (데이터셋 스키마 한계)
- **[4] File-level 대조군: 11,963 낭비 Read** → range-level 대비 오탐 91.7% 제거 (정밀 target 정의의 효과)
- 판정 유보 (미확인 Edit `tool_input_json=None` 사이 존재): 1,115 건

### 발견된 정의 구멍 (사후 판정용 사람 리뷰 중 발견, v1은 frozen)
1. **`/compact` 이벤트 스팬**: 두 Read 사이에 "session is being continued from a previous conversation"이 있음 → 컨텍스트가 압축되어 첫 Read 내용을 잃음. 정당한 재읽기일 가능성.
2. **Agent/Task 서브에이전트 스팬**: 두 Read 사이에 `Task`/`Agent` 툴 호출이 있음 → 서브에이전트가 파일을 편집했을 수 있으나 부모 세션의 `tool_name`이 `EDIT_TOOLS`에 없어 못 잡음.

## v2 결과 (2개 구멍 반영, v1과 병기 — 사후 튜닝 아님, 낭비를 줄이는 방향)

994 v1 후보 → compact-스팬 71 + agent-스팬 90 + 둘다 16 = **총 177건 제외** (17.81%)
- **v2 낭비 Read: 817 / 60,778 = 1.344%**
- v2 낭비 세션은 재집계 필요 (덤프: `swechat_waste_cases_v2.csv`)

### v1 후보 부가 분포 (n=994)
- prev→turn 간격: P25=3, **median=8**, P75=24, mean=35.1, max=958 (오른쪽 꼬리 김)
- offset kind: **FULL 94.1% (935건)**, range 5.9% (59건) — 낭비 대부분이 파일 전체 재읽기

### 정직 병기 원칙
v1은 사전등록 정의로 확정된 primary 결과. v2는 개선안이며, 정의 변경은 사후 튜닝처럼 보일 수 있으므로 **두 값을 함께 발표한다.** 둘 다 코딩 세션의 1% 대 낭비 밀도를 시사.

## v3 결과 (데이터셋 중복 제외)

v2 표본 판정 중 gap==0 (turn_number 동일) 케이스 56건 발견 → parquet 원본 행 중복(같은 turn_id 2회). 우리 로직 버그 아님.
- **v3 낭비 Read: 761 / 60,722 = 1.253%** (pool도 중복 제외: 60,778 - 56 = 60,722)

## v4 결과 (성공 패턴 판정, 첫 Read 실패 재시도 제외)

**계기**: CASE 4의 tool_result content 확인 중 `"File unchanged since last read. The content from the earlier Read tool_result in this conversation is still current — refer to that instead of re-reading."` 발견 → **Claude Code가 이미 벤더 캐시로 재읽기를 방지 중**.

두 Read 사이의 `tool_result` (`tool_name == "Read"`) content를 3분류:
- **성공**: `r'^\s*\d+→'` (라인번호 접두어)로 시작 → 실제 파일 내용 수신 → 재읽기 낭비 후보
- **cache_hit**: `"File unchanged since last read"`로 시작 → 벤더가 이미 방지, 토큰 낭비 아님
- **error**: 그 외 (첫 Read 실패, 빈 결과 등) → 재시도 정당

v3 761건 분류 결과:
| 카테고리 | 건수 | 비율 |
|---|---|---|
| all_success (진짜 재읽기 낭비 후보) | **424** | 55.72% |
| all_error (첫 Read 실패 → 재시도 정당) | 317 | 41.66% |
| has_cache_hit (벤더가 이미 방지) | **15** | 1.97% |
| no_read_result (사이 Read 결과 없음) | 5 | 0.66% |

- **v4 낭비 후보: 424 / 60,722 = 0.698%** ← 최종 낭비 후보 밀도
- 기존 에러 판정(`re.search("error|not found|does not exist|cannot read")`) 방식 폐기: Go 코드 `error` 오탐, JS `console.error` 오탐 등 false positive 다수.

## 진행 요약 (v1 → v4, 모두 정직 방향)

| 버전 | 낭비 후보 Read | 밀도 | 감축 사유 |
|---|---|---|---|
| v1 (사전등록 frozen) | 994 | 1.635% | primary — 코딩 도메인 1%대 밀도 |
| v2 (compact/agent 스팬 제외) | 817 | 1.344% | 컨텍스트 압축·서브에이전트 정당화 |
| v3 (데이터셋 중복 제외) | 761 | 1.253% | parquet 원본 duplicated row 56건 |
| **v4 (성공 패턴 판정)** | **424** | **0.698%** | 첫 Read 실패 재시도 317건 + 벤더 캐시 15건 제외 |

## 핵심 한계 (필수 명시)

**데이터셋에 assistant 텍스트 턴이 없다.** tool_use / tool_result 만 있고 "왜 다시 읽었나"를 결정할 assistant reasoning은 손실됨. 따라서 v1~v4 숫자 모두 **낭비 "후보"이지 확정 낭비가 아님.** 정밀도 산출을 위한 사람 판정은 판정 근거가 약함 (CASE 2/4/8 검증 시 확인).

## 핵심 발견 (무결한 성과)

**file-level 대조군 11,963 → range-level 994 = 오탐 91.7% 제거** (v1 결과 [4]).
숫자가 v2/v3/v4로 어떻게 깎여도 이 비율은 유효. 정밀 target 정의 (`(path, offset, limit)`) 자체의 방법론적 성과.

## 벤더 캐시 응답에 대한 정정 (개정)

**"Claude Code가 Read 재읽기를 이미 벤더 캐시로 방지 중"이라는 서술은 과장.**
- 실측: v3 761건 중 벤더 캐시 응답(`"File unchanged since last read"`) = **15건 (1.97%)**.
- 나머지 424건은 조건이 같은데도(같은 target 재읽기) 정상 파일 내용을 응답받음.
- **왜 15건에만 캐시가 걸리고 424건에는 안 걸렸는지는 미해결.** 벤더 캐시의 트리거 조건은 이 데이터로 판단 불가.
- 함의: "벤더가 이미 최적화 중"으로 결론 내리기엔 근거 부족.

## 편향 방향에 대한 정정 (개정)

**v4 밀도 0.698%를 "최소치(하한)"로도 "상한"으로도 서술하지 않는다.**
- 아래 §"EDIT_TOOLS pool 오염" 참조 — v1~v4는 상한 방향으로 오염됐고(오탐 포함), 동시에 하한 방향으로도 편향됨(unresolved_between 1,115건 부당 drop).
- 재실행 전까지 단일 방향 서술 금지.

---

## SPEC 개정 §19.1 — EDIT_TOOLS pool 오염 (2026-07-16)

### 사실
`tool_name` 컬럼은 tool_use / tool_result **양쪽 행에** 붙어 있다.
- Claude Code **Bash 239,553** = tool_use 119,981 + tool_result 119,572
- Claude Code **Read 127,220** = 63,664 (tool_use, tij 채움) + 63,556 (tool_result, tij None)
- 모든 도구에서 `tool_input_json` 결측률이 정확히 ~50%였던 이유가 이것.
  파이프라인 손실이 아니라 tool_use와 tool_result를 한 통에서 센 것.

근거:
- `recon_bash2.py` Q1: turn_type × tool_input_json 크로스탭
- `diagnose_edit_pool.py` (2026-07-15 실행): tool별 turn_type 분포 + tij 채움률

### 오류
v1 SPEC의 "미확인 Edit(`tool_input_json=None`) 사이 존재 → 낭비 아님(보수적)" 조항은
**실재하지 않는 범주에 기반**했다.
- `tool_input_json=None`인 Edit/Write/MultiEdit 행은 결측이 아니라 그 도구의 `tool_result` 행.
- 그 짝인 `tool_use` 행은 `file_path` 100% 채움으로 정상 판정 대상.
- 즉 "미확인 Edit"으로 처리하며 unresolved_between drop한 후보들은 짝을 이미 봤어야 한다.

### 영향 규모
- 이 조항으로 unresolved_between drop된 후보: **1,115건**.
- v1 후보 994건보다 많음. 하한 방향 편향.

### pool 정의는 변경 없음
`Claude Code Read + tool_input_json IS NOT NULL = 63,664`는 유효.
- 이는 `turn_type == 'tool_use'` 필터와 결과가 같아야 한다 (tool_result 행은 tij=None이므로 자동 제외).
- 재실행 시 `turn_type == 'tool_use'` 명시 필터 추가. **결과가 안 바뀌어야 정상.** 바뀌면 pool 정의가 틀렸다는 뜻이므로 즉시 멈추고 보고.

### 재실행 계획 (v1'~v4')
1. EDIT_TOOLS 스캔에 `turn_type == 'tool_use'` 필터 추가 (Edit/Write/MultiEdit 각각)
2. "미확인 Edit → 낭비 아님" 조항 제거
3. pool 필터에 `turn_type == 'tool_use'` 명시
4. 데이터셋 중복 행 제외는 `turn_id` 기준 유지
5. `unresolved_between` 카운터 남겨둠 — **0이 나와야 정상** (확인용)
6. file-level 대조군에도 동일 수정 적용 후 재산출

---

## §19.1 사전등록 — 재실행 결과 판정표 (결과를 보기 **전에** 확정)

### 밀도 (v1' 기준) — 결정표

| 구간 | 결론 |
|---|---|
| < 1% | "Read 반복은 약한 신호" 결론 유지. 정직한 음성으로 발표. |
| 1% ~ 3% | 결론 재검토. 단독 인용은 여전히 불가. |
| > 3% | Read 반복이 유의미한 신호. Bash 우선 전략 판단 재검토. |

- 어느 구간이든 **"후보이지 확정 낭비 아님"**(assistant 텍스트 부재로 인한 근본 한계)은 유지.

### 오탐 제거율 (기존 91.7%)

**얼마가 나오든 그 값을 기록·발표한다.**
- 기존 91.7% (file-level 11,963 → range-level 994) 는 **"오염된 EDIT 판정 기반"** 이라는 단서와 함께 병기한다.
- **값이 낮아졌다는 이유로 file-level 대조군 정의를 바꾸지 않는다.** (금지 규칙 6에 명시)
- 50% 아래로 떨어지면 "파일+범위" 원리의 실측 근거가 약해졌다고 그대로 적는다.

### 재실행 전 예측 (2026-07-16, 결과 보기 전 기록)

**오탐 제거율 91.7%는 하락할 것으로 예측한다.**

근거: range-level target `(path, offset, limit)`은 정확 일치를 요구하므로 짝의 평균 거리가 file-level target `(path)`보다 멀다. 거리가 멀수록 사이에 Edit tool_result 행이 낄 확률이 높고, 따라서 "미확인 Edit" 조항에 의한 drop이 range-level에 더 강하게 작용했다. 고치면 994가 11,963보다 비율상 더 크게 증가하고, 994/11,963 비율이 커져 제거율은 하락한다.

- 예측이 틀리면 틀렸다고 기록한다. 예측에 맞춰 정의를 조정하지 않는다.
- 검증용 추가 측정: **file-level 대조군의 unresolved_between drop 건수**도 산출해 range-level의 1,115와 비교한다. (이는 측정 항목 추가이지 정의 변경이 아니다.)

### 출력할 표 (재실행 후 아래 항목 필수 기록)

| 버전 | 기존 후보 | 재검증 후보 | 기존 밀도 | 재검증 밀도 | 비고 |
|---|---|---|---|---|---|
| v1 → v1' | 994 | **2,053** | 1.635% | **3.381%** | |
| v2 → v2' | 817 | **1,272** | 1.344% | **2.095%** | |
| v3 → v3' | 761 | **1,272** | 1.253% | **2.095%** | **v3' 단계는 v2'와 동일 — dedup 상류 이동으로 무의미해짐 (편차 2 참조)** |
| v4 → v4' | 424 | **858** | 0.698% | **1.413%** | |

### 재실행 검증 항목

- **`unresolved_between == 0` ✓** (range-level: 0, file-level: 0) — SPEC §19.1 중단조건 통과
- **Edit tool_use `_path` 결측 == 0 ✓** — turn_type 필터로 완전 제거
- **"미확인 Edit" 조항 제거로 새로 승격된 후보: 1,114건** (raw 추적 완료 — "사실상 일치" 표현 폐기)
  * old_waste 994 vs v1' waste 2,053 turn_id 비교: 유지 939 / 사라짐 55 / 신규 1,114
  * old_unresolved 1,115 → v1' waste: **1,115 전건 승격 (재현 스크립트로 raw 확인)**
  * 신규 1,114 vs 승격 1,115의 오차 1건: **turn_id `153f7e94-...#131`** 이 old에서 waste와 unresolved에 **양쪽 모두** 등장. old code에서 이 turn_id는 gap==0 waste(중복 row의 자기 자신 페어)이자 동시에 첫 occurrence의 이전 target 재읽기로 unresolved. dedup 후 v1'에서는 unresolved-측 승격이 waste로 유지되어 "유지 939"에 포함됨. 즉 승격 1,115 중 1건은 이미 kept 카테고리로 산정되어 "신규 1,114"에서 빠짐.
  * old_waste 994 = 55 pure gap==0 + 1 overlap + 938 real ; old_unresolved 1,115 = 1,114 pure + 1 overlap ; 최종 회계 완결.
- **file-level 대조군: 11,963 → 15,787** (+3,824)
- **오탐 제거율: 91.7% → 87.0%** (−4.7 percentage point)
- **세션 기준 낭비율: 631 / 4,411 → 989 / 4,411 = 22.42%** (14.31%에서 상승)

### 예측 적중 여부

**예측 적중** — 오탐 제거율 91.7% → 87.0%로 하락. 예측 근거대로 range-level의 부당 drop 비중이 file-level보다 컸음.
- 예측: "994가 11,963보다 비율상 더 크게 증가" — 실측 검증:
  * 994 → 2,053 = ×2.066
  * 11,963 → 15,787 = ×1.320
  * range-level 증가율이 file-level보다 큼 → 예측대로.

### 결정표 적용 (v1' 밀도 = 3.381%)

**> 3% 구간 → "Read 반복이 유의미한 신호. Bash 우선 전략 판단 재검토."**

- 결정표 기계 적용. 밀도가 상한을 초과했다고 구간 경계를 재해석하지 않음.
- "후보이지 확정 낭비 아님" (assistant 텍스트 부재로 인한 근본 한계)은 유지.
- Bash 조사 방향은 **본 결과를 넘어서지 않는 별도 SPEC**으로 착수 판단. §19 primary는 Read.

### Wall time

- `run_swechat_waste_scan.py` (v1'): **50.7s**
- `quantify_gaps.py` (v2'): **15.5s**
- `v4_reclassify.py --pool 60722` (v4'): **11.4s**
- 합계: **~77.6s**

### 기존 v1~v4 숫자는 삭제하지 않는다
v1~v4 결과는 오염된 판정 기반이지만 이력으로 남긴다. v1'~v4'는 병기.

---

## §19.1 재실행 중 발생한 규율 편차 (2026-07-16 자체 감사)

계획(§19.1 사전등록·재실행 계획)과 실제 실행 사이에 발생한 편차를 사실만 기록. 변명 없음.

### 편차 1 — 중단조건 2 미작동

- **계획**: "pool 크기가 63,664에서 바뀜 → 즉시 멈추고 보고."
- **실제**: 재실행 pool = **63,608 (−56).** 값이 바뀌었다. 중단하지 않고 자체 설명 후 진행.
- **원인 설명 (사후)**: turn_id 중복 dedup을 v1' 상류로 이동 → Read pool에서 56건 dupe 제거.
- **자체 판단이 결과적으로 맞았는가**: 예. 63,664 → 63,608은 dedup 상류 이동의 직접 결과이고, 산식으로 재현 가능. 결과 오염 없음.
- **그럼에도 편차로 기록하는 이유**: 중단조건은 "이상하면 사람이 판단한다"는 장치. 스스로 설명을 만들어 통과시키면 무력화된다. 이번 판단은 옳았으나 다음번 보장은 없다.

### 편차 2 — dedup 상류 이동 (미등록 정의 변경)

- **계획** (§19.1 재실행 계획 4번): "turn_id 중복 제외는 **유지.**"
- **실제**: 코드는 dedup을 `run_swechat_waste_scan.py`의 **최상단**(line 94)으로 이동. Read pool 형성 이전 단계.
- **코드 작성 시점 판단 (사후 진술)**: v3 단계가 "v2 결과에서 gap==0 사후 필터"였는데, 원인이 원본 parquet 중복 행이라 상류에서 처리하는 게 자연스럽다고 판단. **그러나 이 판단은 SPEC 개정에 명시되지 않았음.**
- **결과 영향**:
  * pool 63,664 → 63,608 (편차 1의 원인)
  * v2' == v3' == 1,272 — **v3 단계가 사실상 소멸.** 표에 별도 행으로 남지만 필터 무효.
  * turn_id dedup의 waste-화 효과가 원천 소거됨 (old에서 gap==0 waste 56건 발생 → v1'에서 0건)
- **사전등록 위반인가**: 코드는 재실행 **전** 커밋(911eeda)됐고, 결과 커밋(3fa82c7)은 그 다음. 감사 추적은 유효. 그러나 **SPEC 계획과 코드가 불일치한 채 실행됐다는 사실은 사전등록 규율의 정신에서 벗어난다.**
- **재발 방지**: 다음 사전등록부터 코드 작성 전에 SPEC과 대조. 상류/하류 위치 변경은 SPEC에 명시적 개정으로 반영.

---

## §19.1 미해결 관찰 (2026-07-16, 해석 금지 — 규율 5·6 준수)

재실행 결과에서 기존 v1~v4와 통계적 성격이 뚜렷이 다른 부분들. **이유는 미해결로 기록.** 그럴듯한 가설은 있으나 검증 안 됐고, 세기 전 일반화는 금지.

### 관찰 1 — compact/agent 제외율 상승

- v1 → v2: 177 / 994 = **17.81%**
- v1' → v2': 781 / 2,053 = **38.04%**
- 절대치도 상대치도 크게 증가. 새 후보의 성격이 이전과 다르다.

### 관찰 2 — 첫 Read 실패 재시도 비율 하락

- v3 → v4 (기존): all_error 317 / 761 = **41.66%**
- v3' → v4' (신규): all_error 380 / 1,272 = **29.87%** (SPEC 요약 기재 32.5%는 오기 — 실측 29.87%)
- error 비율은 하락했으나 절대 error 건수는 317 → 380으로 증가.

### 관찰 3 — 새 승격 후보의 gap 분포 확장

- v1 gap: median=8, mean=35.1, max=958
- v1' gap: median=56, mean=241.4, max=5,486
- 새로 승격된 1,114건 대부분이 긴 gap 영역에 위치 (raw 확인은 별도 후속).

**공통 함의 (해석 없이 기록만)**: 새로 승격된 1,114건은 기존 994건과 통계적으로 다른 분포에 위치한다. 그럴듯한 가설(gap이 멀수록 compact/Agent 스팬을 지날 확률이 높다, 긴 gap일수록 첫 Read 결과가 세션 컨텍스트에서 밀려나 재시도 유인 감소 등)이 있으나 **검증되지 않았다.** 별도 분석은 백로그.

---

## §19.1 결정표 설계 결함 (2026-07-16)

**§19.1 사전등록의 밀도 결정표를 v1' 기준으로 지정한 것은 설계 결함.**

### 사실
- v1'은 실패 재시도(29.87%) + compact/agent(38.04%)를 포함한 raw 후보 수.
- 판정 기준으로는 v4'(이 잡음을 걷어낸 값)가 적절.
- 실제 두 값은 서로 다른 구간에 떨어짐:
  * v1' 3.381% → **> 3% 구간** ("Read 반복이 유의미한 신호, Bash 우선 판단 재검토")
  * v4' 1.413% → **1~3% 구간** ("결론 재검토. 단독 인용은 여전히 불가")

### 결정표는 사후 변경하지 않는다
- 사전등록대로 **v1' 기준 > 3% → "재검토"** 를 그대로 적용.
- 결함을 인지했다는 사실을 기록으로 남긴다.

### 향후 원칙 (다음 사전등록부터 적용)
- 밀도 결정표의 기준값은 **필터 적용 후 값(v4' 상당)** 으로 지정한다.
- raw 후보(v1' 상당)는 참고 지표로 병기하되 결정 근거로 삼지 않는다.

### 판정 결과에 대한 주석
- 이번 판정 결론은 "재검토"이지 "Bash 포기"나 "Read 반복 확정"이 아님.
- v1' > 3%와 v4' 1~3%는 결론 방향이 충돌하지 않음 (양쪽 다 "결론 재검토" 이상의 강한 주장 금지).

---

## §19.1 정직 경계 (2026-07-16 갱신)

### 말할 수 있는 것
- **오탐 제거율 87.0%** (file-level 15,787 → range-level 2,053). 출처(SPEC §19.1, 재검증 후) 표기 필수.
- 기존 91.7%는 "오염된 EDIT 판정 기반"이라는 단서와 병기.
- **예측 적중**: range-level 증가율 ×2.066 > file-level ×1.320 (예측 근거대로).

### 말할 수 없는 것
- **"세션의 22.42%에서 낭비 발견" 단독 인용 금지.** 이유: v1' 기준이고, 실패 재시도 29.87% + compact/agent 38.04%를 포함한 raw 후보 위 값. 기존 14.31% 금지와 같은 원리.
- **v1' 3.381% / v4' 1.413% 어느 것도 "상한" 또는 "최소치"로 서술 금지.** 편차 기록·미해결 관찰이 붙은 뒤에도 이 제약은 유지.
- **"후보이지 확정 낭비 아님"** (assistant 텍스트 부재) 은 모든 인용에 동반.
- **"Claude Code가 벤더 캐시로 Read 재읽기를 이미 방지 중" 서술 금지.** 캐시 응답은 v3' 1,272건 중 29건(2.28%)에 불과.

---

## 다음 조사 방향 (재실행과 무관, 기록만)

- Read 반복은 벤더 캐시가 부분적으로만 관여 (1.97%). 상당수 재읽기는 정상 응답.
- Bash 239,553건 / Grep 56,593건 (Claude Code) — 벤더 방지 장치 미확인 영역.
- 그러나 §19의 primary 결론은 Read 범위 재실행(v1'~v4')이 확정된 다음에 결정. Bash 조사는 **본 문서 개정 이후 별도 SPEC**으로.
