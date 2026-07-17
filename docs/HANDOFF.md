# HANDOFF — Clew/Custos 다음 담당자 인수인계

**규칙 7 적용**: 이 문서는 SPEC 에서 파생된다. 나란히 쓰지 않는다.

- 사실 출처: `field_test/SWECHAT_SPEC.md` §19, §19.1, §19.2, §19.3 및 `docs/CC_TRANSCRIPT.md` §21, §22.
- 숫자마다 출처 섹션 표기. 여기서 새로 만든 숫자 없다.
- SPEC 과 충돌하면 SPEC 이 정본이다.

---

## 1. 현재 상태 (2026-07-17)

### 브랜치 · 커밋 상태
- 활성 브랜치: `feat/cc-adapter` (origin 동기화).
- 최근 병합: PR #12 (`6ea7adc`, main). CC 어댑터 라운드 전체가 `feat/cc-adapter → main` 으로 인수됨.
- 마지막 커밋 (본 라운드): `92a2a14` — §22.7 첫 실행 진단 fold-back.

### T1 달성
- **T1 = "Claude Code 세션 JSONL 을 파이프라인에 통과시킨다"** — 달성. 근거: `docs/CC_TRANSCRIPT.md` §22.6.
- 대상 세션 `f96aee88-…` 에서 `python -m clew analyze <path>.jsonl` 이 오류 없이 완료 (total_spans 181, 조인 실패 0, Pydantic 검증 실패 0). 근거: `docs/CC_TRANSCRIPT.md` §22.6.
- 첫 실행 결과 waste 3건 — Edit cos=1.0000, Write 0.9959, Bash 0.6577. 근거: `docs/CC_TRANSCRIPT.md` §22.6 표.
- **3건 전부 오탐.** 근거: `docs/CC_TRANSCRIPT.md` §22.7 요약 표.

### 어댑터 매핑 (frozen §22.1)
- `span_id = tool_use.id` (1:1 조인, `docs/CC_TRANSCRIPT.md` §21.3 Q6: 180/180 unique).
- `input_text = json.dumps(tool_use.input, sort_keys=True, ensure_ascii=False)` (§22.2).
- `output_text` — str 은 그대로, list 는 text 블록 이어붙이기 + 그 외 타입은 `json.dumps + warn` (§22.5 addendum, 2026-07-17).
- v1 은 `tool_use ↔ tool_result` 쌍만 스팬. thinking/text 블록은 스팬 생성 안 함 (§22.3).

### 규칙 적용 상태
- **규칙 7 (fold-back)**: `docs/CC_TRANSCRIPT.md` §21 (transcript recon), §22.7 (진단) — 외부 raw 확인 후 즉시 SPEC 에 반영.
- **규칙 8 첫 적용**: `field_test/SWECHAT_SPEC.md` §19.2 (v4 분류기 사전등록, 커밋 `82d905d` push → 결과 커밋 `04bd49d` 순서 확정). 근거: SPEC §19.2 "규칙 8 커밋 체인" 표.
- CC 어댑터 라운드 (`feat/cc-adapter`) 도 규칙 8 실무 형태 적용: §22 사전등록 (`bbd9c9e`) → 코드 (`e6dc770`) → 결과 (`b7ed00c`) → fold-back (`92a2a14`).

---

## 2. 말할 수 있는 것 · 말할 수 없는 것 (정직 경계)

### 말할 수 있는 것
- **오탐 제거율 87.0%** (file-level 15,787 → range-level 2,053). 출처: `field_test/SWECHAT_SPEC.md` §19.1 재실행 검증 항목 + 정직 경계.
- **예측 적중 실적**: (a) §19.1 오탐 제거율 하락 예측 적중 (91.7% → 87.0%, range-level ×2.066 > file-level ×1.320). (b) §19.2 v4'' 예측 적중 (v4'' = 955 ∈ [950, 1000]). 출처: SPEC §19.1 "예측 적중 여부" · §19.2 결과 "예측 적중 여부".
- **벤더 골드셋 71 = 참양성 하한**. 71 / 2,053 = 3.458% (v1' 전체 분모). 출처: SPEC §19 "벤더 골드셋". **정밀도가 아니다.**
- **T1 사실**: CC JSONL → Trace 파이프라인 통과. 출처: `docs/CC_TRANSCRIPT.md` §22.6 · §22.7 정직 경계.
- **thinking 평문 부재는 벤더 구조 한계이지 데이터셋 파이프라인 손실이 아니다.** 원본 리콘으로 확증. 출처: `docs/CC_TRANSCRIPT.md` §21.1 (2026-07 기준 496/496 zero).
- **tool_use ↔ tool_result 1:1 조인** (원본 기준). SWE-chat 의 1:N (max_dup=5) 은 파이프라인 산물. 출처: `docs/CC_TRANSCRIPT.md` §21.3, §21.5 (교차 참조).
- **§21.4 벤더 포맷 전환 (2026-03-28)** 은 원본 transcript 로 확증됨. 출처: `docs/CC_TRANSCRIPT.md` §21.4.

### 말할 수 없는 것 (인용 금지)
- **"91.7%" 단독 인용 금지** — 오염 EDIT 판정 기반. 87.0% 병기 필요. 출처: SPEC §19 "핵심 발견" 각주.
- **"87.0% 는 read-once 대비 차별점" 서술 금지** — 두 도구는 같은 목표에 다른 경로 (측정 vs 회피). 87.0% 는 "순진한 file-level 매칭 대비" 방법론 근거로만 유효. 출처: SPEC §19.1 정직 경계 단서 (2026-07-17 fold-back), §19.3 "인용 금지".
- **"42% 첫 Read 실패 실측" 인용 금지**. 원 41.66% 는 두 버그(정규식 오분류 15.66% + 창문 any) 의 합작. 실측 재계산 (v4'' × prev-tcid × `[→\t]`): error 7.31% ~ unknown 포함 22.72%. **원칙(첫 시도 성공 여부는 판정에 필수)은 유지, 크기만 붕괴.** 출처: SPEC §19.2 관찰 6.
- **v1' 3.381% / v4' 1.413% / v4'' 1.573% 어느 것도 "상한" 또는 "최소치" 서술 금지**. 출처: SPEC §19.1 · §19.2 정직 경계.
- **"세션의 22.42% 에서 낭비 발견" 단독 인용 금지**. 출처: SPEC §19.1 정직 경계.
- **"Claude Code 가 벤더 캐시로 재읽기를 이미 방지 중" 서술 금지** — v3' 1,272 중 29건 (2.28%). 출처: SPEC §19 "벤더 캐시 응답 정정".
- **"clew analyze 가 CC 세션에서 낭비 N건 검출" 인용 금지** — 첫 실행 3/3 오탐. 결함 1~4 수정 전까지 검출 수치 무의미. 출처: `docs/CC_TRANSCRIPT.md` §22.7 정직 경계.
- **§22.7 관찰의 "13 → 4 = 69.2%" 수치 인용 금지** — n=25 단일 세션. **방향 재현 사실만 기록.** 출처: `docs/CC_TRANSCRIPT.md` §22.7 관찰.
- **§21.2 토큰 usage 5쌍 가설 (`prev.cache_read + prev.cache_creation = next.cache_read`) 인용 금지** — 5쌍 관찰. 전수 검증 전 규율 5 (미검증 인과). 출처: `docs/CC_TRANSCRIPT.md` §21.2.
- **"§19 / §19.1 을 사전등록했다" 외부 서술 시 "커밋 순서는 증명되나 외부 타임스탬프는 결과 이후" 단서 병기.** §19.1 편차 3. 다음 라운드 (§19.2, CC 어댑터) 부터는 규칙 8 적용됨.
- **unknown 15.409% 단서 병기 필수**: v4'' = 955 인용 시 "분류기가 v3' 의 15.4% 를 확정 못함" 함께. 출처: SPEC §19.2 "음성 결과 정의 발동".

### 폐기된 서술 (이전 인수인계 정정)
- **발견 ② "'첫 시도 성공 여부' 가 낭비 판정에 필수 — 42% 실측"** — 42% 인용 폐기. 원칙만 유지. 출처: SPEC §19.2 관찰 6.
- **발견 ① "91.7%"** — 87.0% 로 정정. "read-once 대비" 프레이밍 제거. 출처: SPEC §19.1 정직 경계 + §19.3 인용 금지.
- **v4** — 최신 분류기는 v4'' (2026-07-17, prev-tcid + `[→\t]` + unknown 범주). 출처: SPEC §19.2 결과.

---

## 3. 다음 작업 — §22.8 사전등록 대상

**§22.8 은 아직 작성되지 않았다.** 결함 1~4 는 진단되었으나 해법은 사전등록 대상이다.

### 해결 대상 결함 (모두 `docs/CC_TRANSCRIPT.md` §22.7 출처)
1. **결함 1 — origin 고정** (`src/clew/detect/structural.py:64,68`): `origin = occurrences[0]` 로 고정. occurrences[i] vs occurrences[j] (i,j ≥ 1) 동일해도 origin 과 다르면 둘 다 탈락. 실측 증거: Read `(file_path, offset, limit)` 완전 동일 재호출 4건 존재했으나 repeat 후보 0건. **§19 는 모든 쌍 비교. 제품과 분석의 알고리즘이 다르다.**
2. **결함 2 — pingpong input 게이트 부재** (`structural.py:85-88, 99`): `agent_or_node_id` 만 비교. waste 3건 전부 pingpong 출처, 3/3 오탐. SPEC §19.1 `EDIT_TOOLS unknown_hit`, §19.2 `all_success` 와 동일 계열 (라벨/주석 vs 로직 불일치).
3. **결함 3 — Edit/Write output_text 가 템플릿** (`src/clew/detect/cascade.py:36`): Edit distinct 5/31 (16%), Write 접두사 `"File created successfully at: <path>"`. **φ 는 output_text 를 비교하므로 템플릿 위에서 항상 높은 cos.** 구조 게이트가 유일한 방어. 결함 1·2 가 그 방어를 뚫는다.
4. **결함 4 — Bash `description` 이 command 재호출을 가림**: input 전체 직렬화 (§22.1) 에서 매 호출 새 description 이 붙어 command-only 동일 재호출 9건이 소실. **repeat 0 의 직접 원인 중 하나.** SPEC §20 은 command 문자열만 보는 설계였다. 여기서 갈린다.

### 사전등록 제약 (§22.8 작성 시)
- **φ = 0.514345 는 frozen.** 결함 3 을 φ 조정으로 풀지 않는다. 출처: `docs/CC_TRANSCRIPT.md` §22.7 미해결.
- 규칙 8 절차: 사전등록 커밋 → push + PR 오픈 (외부 타임스탬프 확정) → 실행 → 결과 커밋. 병합은 반드시 merge commit. 출처: SPEC 금지 규칙 8 부칙.
- 예측·중단조건·정의를 결과 보고 수정 금지. 출처: SPEC 금지 규칙 1~6 + §19.2 "금지".

### 판단 지점 (결함 3 미해결, `docs/CC_TRANSCRIPT.md` §22.7)
- Edit/Write 는 **input 이 신호, output 이 노이즈** 로 보임 (같은 파일 + 같은 new_string 재적용 = 낭비).
- 이는 §22 매핑과 cascade 설계 양쪽에 걸린다. §22.8 사전등록 대상.

---

## 4. 무결한 발견 (clean findings)

**정정된 형태로만 인용한다.**

1. **정밀 target 정의의 방법론적 성과: file-level 15,787 → range-level 2,053, 오탐 87.0% 제거.**
   - 출처: SPEC §19.1 재실행 검증 항목.
   - 단서: "순진한 file-level 매칭 대비" 방법론 근거로만 유효. read-once 대비 차별점 아님.
   - 예측 근거 성립: range-level 증가율 ×2.066 > file-level ×1.320 (SPEC §19.1 예측 적중).

2. **첫 Read 실패 여부는 낭비 판정에 필수 (원칙 유지, 크기 붕괴).**
   - 출처: SPEC §19.2 관찰 6 + 관찰 5 (gap 상관).
   - v4'' × prev-tcid × `[→\t]`: error 93/1,272 = 7.31%, unknown 196 = 15.41%.
   - 창문 방식은 이 신호를 과장했다 (gap≥100 에서 99%). prev-tcid 직접 조인이 올바른 축.
   - **"42%" 인용 금지.**

3. **벤더 골드셋 참양성 하한 71 = 3.458%.**
   - 출처: SPEC §19 "벤더 골드셋".
   - `tool_call_id` 조인 방식 (adjacency 폴백 금지, progress 행 49% 로 구조적 부적합).
   - **정밀도 아님. 참양성 하한.**

4. **v4'' 분류기 예측 950~1000 실측 955.**
   - 출처: SPEC §19.2 결과 "예측 적중 여부".
   - 사전등록 3칸 (858/812/1,006/424/516) 재현 일치.
   - 단서: unknown 15.4% 병기 필수.

5. **읽기 target 재정의의 자기 재현 (방향만).**
   - 출처: `docs/CC_TRANSCRIPT.md` §22.7 관찰.
   - SWE-chat 87.0% 논지가 CC 자기 세션에서 방향 재현. **값 인용 금지, n=25.**
   - 남의 데이터로 잰 논지가 자기 데이터에서 처음 재현된 사례.

6. **T1 파이프라인 통과 (기술적 성취).**
   - 출처: `docs/CC_TRANSCRIPT.md` §22.6.
   - CC JSONL 어댑터 + tool_use↔tool_result 1:1 조인 + sort_keys 직렬화 + list-content 규약 (§22.5) 이 실 세션에서 작동함.
   - **낭비 검출 성능 별개.**

---

## 5. 규율 1~8

### 규율 1~6 (base, SPEC 금지 절 참조)
- (1) pool 정의 사후 수정 금지.
- (2) target 정규화 규칙 사후 튜닝 금지.
- (3) **raw 확인.** 배경 사실 서술에도 적용. 필드명·용어 의미는 코드로 확인 후에만 정직 경계에 진입. 출처: SPEC §19.1 편차 5 + §19.3 편차.
- (4) 낭비 많은 세션만 골라 보기 금지.
- (5) 미검증 인과 인용 금지 (§21.2 5쌍 가설이 대상).
- (6) 값이 낮아졌다는 이유로 대조군 정의 변경 금지.

### 규칙 7 — fold-back
- **발견은 즉시 SPEC 에 반영.** 스크립트 docstring · print · 채팅 로그는 기록이 아니다.
- **인수인계는 SPEC 에서 파생.** 나란히 쓰지 않는다 — 이 문서가 그 예.
- 부칙: fold back 했다고 결론 산출 코드를 삭제해도 되는 것은 아니다. 재현 경로가 남아야 한다.
  - `field_test/diagnostics/` 에 one-off 진단 스크립트를 두고 상단에 재현 대상 SPEC 항목 명시. 예: `field_test/diagnostics/diag_cc_first_run.py` (§22.6/§22.7 재현).
- 출처: SPEC 금지 규칙 7 + `docs/CC_TRANSCRIPT.md` §22.7 fold-back 실행.

### 규칙 8 — 사전등록 push 먼저
- **로컬 커밋은 순서만 증명, 시각 증명 아님.** `GIT_COMMITTER_DATE` 조작 가능.
- **push 이벤트 (GitHub 서버 측) 만이 외부 타임스탬프.**
- **PR 오픈 시점 = 타임스탬프.** 머지 대기 불필요.
- **머지 방식**: 반드시 merge commit. squash/rebase 는 SHA 재작성으로 인용 해시 dangling → 사전등록 논증 파괴.
- 출처: SPEC 금지 규칙 8 + 부칙 (main 브랜치 보호).

### 규칙 8 적용 이력
| 라운드 | 사전등록 커밋 (push 시각 확정) | 결과 산출 커밋 |
|---|---|---|
| §19.2 v4'' | `82d905d` | `04bd49d`, `f502002` |
| CC 어댑터 (§22) | `bbd9c9e` | `e6dc770`, `b7ed00c`, `92a2a14` |

---

## 6. 백로그

### §22.8 대상 (다음 사전등록)
- 결함 1 (origin 고정) 해법.
- 결함 2 (pingpong input 게이트) 해법.
- 결함 3 (Edit/Write output_text 템플릿) 해법 — 매핑 vs cascade 설계 결정 필요. φ 조정 불가.
- 결함 4 (Bash description 은닉) 해법.
- 출처: `docs/CC_TRANSCRIPT.md` §22.7.

### 검증 백로그
- **§21.2 5쌍 가설 전수 검증** — tool_result 텍스트 → 다음 assistant `cache_creation_input_tokens` 귀속. 검증 성공 시 낭비 판정에 토큰 값 부착 가능. 출처: `docs/CC_TRANSCRIPT.md` §21.2 백로그.
- **§21.3 다세션 1:1 조인 확인** — 현재 1 세션 기준. 출처: `docs/CC_TRANSCRIPT.md` §21.3 함의.
- **§22.6 다세션 repeat=0 재현성 확인** — 이 세션 특성인지 일반 현상인지. 출처: `docs/CC_TRANSCRIPT.md` §22.6 함의.
- **§22.6 Edit cos=1.0000 세션 내 검사** — transcript 노출 없이. 출처: `docs/CC_TRANSCRIPT.md` §22.6 함의.

### 미해결 관찰 (검증 안 된 가설로 결론짓기 금지)
- **관찰 2 — 첫 Read 실패 재시도 비율 하락** (v3 41.66% → v3' 29.87%, 절대 건수 317 → 380 증가). 구조적 귀결 메커니즘으로 미설명. 출처: SPEC §19.1 미해결 관찰.
- **관찰 3' — v1'/v4' 후보군 성격 변화**. 신규 승격 median gap 189 vs 유지 9. 긴 gap 재읽기가 짧은 gap 과 동일 성격의 낭비인지 판단 불가. 출처: SPEC §19.1 미해결 관찰.
- **관찰 4 — `os.path.normpath` OS 의존성**. Windows/Linux 재실행 시 CSV 리터럴 표기 상이. 상대·절대 매칭이 구분자에 의존하면 결과 달라질 가능성 — 미검증. 출처: SPEC §19.1 미해결 관찰.
- **관찰 5 — prev=success × gap 상관의 인과**. 상관은 실측, 인과 (첫 실패→즉시 재시도, 첫 성공→긴 gap) 는 미검증. 출처: SPEC §19.2 관찰 5.
- **§19.3-1 — mtime 사각지대**. read-once 예방 범위 실측 불가 (mtime 데이터 부재). Clew 낭비 후보 CSV 에서 read-once 대비 정량 비교 방법 현재 없음. 출처: SPEC §19.3.

### 별도 SPEC 대상
- **Bash 조사** (239,553건 / Grep 56,593건). 벤더 방지 장치 미확인 영역. §19 primary 확정 후 별도 SPEC. 출처: SPEC "다음 조사 방향".

### E unmatched 잔여 (§19.2 결과)
- `File does not exist ...` 카테고리 사전등록 누락. 다음 개정 라운드에서 규칙 8 준수하며 처리. **본 라운드에서 문자열/카테고리 추가 금지.**
- `File content ... exceeds maximum allowed tokens ...` 문자열 (편차 7 계열). 다음 라운드.
- `<system-reminder>` 접두 후 `\d+[→\t]` 68건 (앵커 우회) — unknown 으로 분류 (사전등록 그대로).
- 출처: SPEC §19.2 관찰 1·2·3.

---

## SPEC 충돌 보고

**충돌 발견 없음.** 이 문서의 모든 수치·서술은 SPEC (§19-§19.3, `docs/CC_TRANSCRIPT.md` §21-§22.7) 에서 파생됨. SPEC 이 정본. 이 문서가 SPEC 과 어긋난다고 판단되면 SPEC 을 따르고 이 문서를 정정한다.
