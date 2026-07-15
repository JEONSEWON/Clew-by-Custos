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
- `norm_path` = `os.path.normpath` 적용. 세션 내 절대·상대 혼용 89 세션(2%)은 basename fallback, 발동 건수 별도 카운트
- `offset`/`limit`이 str인 35건 → int 캐스팅, 실패 시 해당 Read drop (건수 기록)

## 낭비 판정 (2조건 AND — 사전 확정)
1. 같은 세션 내 동일 target 재등장
2. **그 사이(`turn_number` 기준)에 해당 `norm_path`에 대한 Edit/Write/MultiEdit 턴이 없음**
   → 2번이 핵심. Edit 후 재읽기는 정당하므로 낭비 아님.

## 측정 지표 (사전 확정)
1. 낭비 1건 이상 있는 세션 비율 (분모: Read 보유 Claude Code 세션)
2. 낭비 Read 턴 / 전체 Read 턴
3. **낭비 턴의 토큰 합** (`input_tokens + output_tokens`) 및 전체 대비 비율
4. **대조군**: file-level만으로 판정 시 낭비 수 (target = `norm_path`만). range-level 대비 차이 = 정밀 대상 정의가 거른 오탐 수

## 음성 결과 정의 (미리 확정)
- 낭비 세션 비율이 낮게 나오면 → 코딩 에이전트 방향의 신호가 약하다는 **정직한 음성**. 그대로 기록·발표.
- 정의를 조정해 숫자를 만들지 않는다. EmergenceTrace AUC 0.455 정직 음성 발표와 동일 원칙.

## 금지 (분석 후 정의 변경 방지)
- pool 정의 사후 수정 금지
- target 정규화 규칙 사후 튜닝 금지
- "사이에 변화 없음" 조건 완화 금지
- 낭비 많은 세션만 골라 보기 금지
