# Cascade Absence-Sentinel Amendment — 사전등록

`docs/ADAPTER_R2_RELAXATION_PREREG.md` §2.1 · §2.4-2.5 개정안.
승인 전 코드 변경 없음. 아래 수치는 전부 승인 전 dry-run 실측이다.

- detector 기준: `main` = `194c73d` (702 tests)
- 실행: `PYTHONPATH=src`
- raw: `field_test/diagnostics/_cascade_precision_sweep*.RESULTS.json`

---

## 1. 문제 — R2 방어가 벤더 placeholder 에 우회됐다

`src/clew/model.py:81-87` 의 불변식은 이 실패 모드를 **명시적으로 예견**하고 있다:

> *"a tool call with no output is invalid data — cascade sha256 gate would match
> empty-vs-empty as waste"*

방어 수단은 **모델 층에서 빈 tool `output_text` 를 금지**하는 것이었다.
전제는 *"출력 없는 tool 호출은 잘못된 데이터"* 다.

**그 전제가 실증적으로 틀렸다.** 아무것도 출력하지 않는 `Bash` 호출은 정상이고 흔하다.
Claude Code 는 그 자리를 자기 문자열로 채운다:

```
$ grep -c "Bash completed with no output" <CC session>.jsonl
9
```

이 문자열은 **원본 트랜스크립트의 벤더 텍스트**다 (우리 어댑터가 합성한 게 아니다 —
`grep -rn "no output" src/clew/` 에 생성 지점 없음). 따라서:

1. 벤더 placeholder 가 비어 있지 않으므로 **불변식을 통과한다**
2. `cascade` tool 분기는 sha256 완전 일치를 본다 (`cascade.py:62`)
3. "출력 없음" 두 건이 **서로의 중복으로 판정된다** — 불변식이 막으려던 바로 그 결과

같은 원칙이 **non-tool 분기에는 이미 구현돼 있다** (`cascade.py`, R2 §2.1):

> *"empty output_text is absence, not expression. cosine on absence is a
> malformed question ... Skip both empty-vs-empty and empty-vs-value"*

**tool 분기에만 이 원칙이 없다.** 이 개정안은 원칙을 추가하는 게 아니라
**두 분기를 같은 원칙 아래로 되돌린다.**

---

## 2. 실측 — 무엇이 플래그되고 있는가

### 2.1 CC 어댑터 (로컬 Claude Code 세션 40건)

| 항목 | 값 |
|---|---|
| tool span | 8,606 |
| 플래그된 span | **31** (0.36%) |
| 플래그가 1건 이상인 세션 | 7 / 40 |
| distinct 플래그 출력 | 9 |
| 플래그 출력 길이 | min 4 · p50 31 · p90 96 · **max 118** |

distinct 9건 전수:

| 건수 | 길이 | 내용 | 성질 |
|---|---|---|---|
| **20** | 31 | `(Bash completed with no output)` | **부재 (벤더 placeholder)** |
| 2 | 59 | `No matches found\n\nFound 0 total occurrences across 0 files.` | **부재 (검색 결과 0)** |
| 2 | 96 | `    {\n "command": "vercel deploy --prod", ...` | 파일 내용 조각 |
| 2 | 90 | (위와 거의 동일한 조각) | 파일 내용 조각 |
| 1 | 117 | `The file ...\app\page.tsx has been updated. All occurrences were s…` | 쓰기 확인문 |
| 1 | 89 | `The file ...\globals.css has been updated successfully.` | 쓰기 확인문 |
| 1 | 22 | `Updated task #1 status` | 상태 확인문 |
| 1 | 4 | `done` | 사소 |
| 1 | 118 | `<tool_use_error>Cancelled: parallel tool call Bash(…) er…` | 취소 에러 |

도구별: Bash 25 · Grep 2 · Edit 2 · TaskUpdate 1 · WebSearch 1.

### 2.2 Corpus B (Toolathlon · 4 파일 샘플 · 240 트레이스)

| 항목 | 값 |
|---|---|
| tool span | 6,250 |
| 플래그된 span | **347** (5.6% — CC 대비 **15배 밀도**) |
| 어댑터 하드 실패로 스킵된 엔트리 | 23 (`ValueError`) — §7.4 참조 |
| distinct 플래그 출력 | 44 |
| 플래그 출력 길이 | min 34 · p50 89 · p90 163 · **max 9,301** |

상위 도구:

| 건수 | 도구 | 성질 |
|---|---|---|
| **139** | `emails-send_email` | **같은 이메일 반복 발송 — 실제 중복 side effect** |
| **138** | `local-claim_done` | **완료 선언 반복 — 실제 행동 병리** |
| 13 | `terminal-run_command` | |
| 9 | `excel-write_data_to_excel` | 중복 쓰기 |
| 7 | `filesystem-write_file` | 중복 쓰기 |
| 6 | `filesystem-read_file` | 중복 읽기 |

**Corpus B 에서 cascade tool 분기는 실제 수확이 있다.** CC 에서만 노이즈다.
이 비대칭이 이 개정안의 범위를 결정한다.

---

## 3. 기각된 안 — 길이 임계 (dry-run 이 죽였다)

CC 플래그가 전부 118자 이하이므로 길이 임계가 자연스러워 보인다. **양쪽에서 재보면 죽는다:**

| 규칙 | CC 제거 | **Corpus B 제거** |
|---|---|---|
| `len < 120` | 31/31 (100.0%) | **308/347 (88.8%)** |
| `len < 200` | 31/31 (100.0%) | **317/347 (91.4%)** |

`'{"type":"text","text":"Email sent successfully to emp001@company.com","annotations":null}'`
은 **89자**다. CC 보일러플레이트를 길이로 자르면 **Corpus B 최고 가치 발견(중복 이메일
발송 139건)이 함께 죽는다.**

**길이는 판별 축이 아니다. 부재(absence) 여부가 판별 축이다.**

---

## 4. 제안 — 부재 센티넬(absence sentinel)

### 4.1 원칙

어댑터는 **자기 벤더가 "출력 없음" 을 어떻게 표기하는지** 안다. 그 지식은 어댑터에 있어야
한다 (§22.5 벤더 블록 처리 관례와 같은 층). detector 는 벤더 문자열을 몰라야 한다.

따라서: **어댑터가 표시하고, detector 는 R2 §2.1 원칙을 tool 분기에도 적용한다.**

### 4.2 구현안 비교

| 안 | 내용 | 판정 |
|---|---|---|
| **A (권고)** | `Span` 에 additive 필드(예: `output_is_absent: bool = False`) 추가. CC 어댑터가 벤더 placeholder 인식 시 `True`. `cascade` tool 분기가 `True` 인 span 을 skip (non-tool 분기의 empty-skip 과 동형) | 벤더 지식=어댑터 · 원칙=detector · 다른 어댑터로 확장 가능 |
| B | 어댑터가 `output_text` 를 빈 문자열로 정규화 + `model.py` 불변식 완화 + tool 분기 empty-skip | 두 분기가 완전 동형이 되나 **불변식 제거**는 R2 §2.4-2.5 를 되돌리는 것 |
| C | `cascade` tool 분기가 벤더 문자열 목록을 들고 skip | **기각** — 벤더 지식이 detector 로 새고 어댑터마다 목록이 필요 |
| D | 어댑터가 해당 span 을 아예 버림 | **기각** — 그 호출은 실제로 일어났다. coverage·카운트가 왜곡된다 |

### 4.3 센티넬 집합 — 결정 필요 (Q1)

| 후보 | 문자열 | CC 제거 | Corpus B 제거 |
|---|---|---|---|
| S1 (좁음) | `(Bash completed with no output)` 정확 일치 | **20 / 31 (64.5%)** | **0 / 347 (0.0%)** |
| S2 (권고) | S1 + `No matches found` 로 시작하는 출력 | **22 / 31 (71.0%)** | **0 / 347 (0.0%)** |

**두 안 모두 Corpus B 를 단 한 건도 건드리지 않는다.**

S2 의 근거: `No matches found\n\nFound 0 total occurrences across 0 files.` 도 부재다 —
검색이 실행됐고 아무것도 없었다. 두 번 아무것도 못 찾은 것은 중복 작업이 아니다.

S2 적용 후 CC 생존 플래그 **9건**: Bash 5 · Edit 2 · TaskUpdate 1 · WebSearch 1.
이 중 Edit 2건(같은 파일 반복 수정)과 96/90자 파일 조각은 **실제 중복 후보로 남는다** —
개정안이 죽이려는 대상이 아니다.

---

## 5. 사전 예측 (승인 후 구현 시 재현되어야 하는 값)

S2 · 안 A 기준.

| 예측 | 값 |
|---|---|
| P1 | CC 40 세션 플래그 **31 → 9** |
| P2 | Corpus B 240 트레이스 플래그 **347 → 347** (무변) |
| P3 | `0c33c4fb` `waste_span_count` **6 → 0** (6건 전부 S1 문자열) |
| P4 | `18c2eb67` `waste_span_count` **17 → 3** (14건이 S1 문자열) |
| P5 | `waste_ratio` 변화 **없음** (cascade `waste_cost` 는 CC 에서 이미 $0.00 — 별건 dry-run 확증) |
| P6 | `union_wr_char` 변화 **없음** (측정 트레이스에서 `per_detector.repeat` 는 이미 0.0) |
| P7 | `coverage_stats` · `category_counts` 스키마 변화 없음 |

P5·P6 이 이 개정안의 성질을 규정한다: **금액이 아니라 카운트와 상세 표를 고친다.**
파트너가 리포트를 열었을 때 보는 것이 바뀐다.

---

## 6. 결정 필요 항목

- **Q1** 센티넬 집합 = S1(좁음) / **S2(권고)**
- **Q2** 구현안 = **A(권고 · additive 필드)** / B(불변식 완화)
- **Q3** `Span` 에 필드를 추가하면 **공개 JSON 리포트 스키마**에 노출할지.
  노출하지 않으면 리포트 소비자(웹앱)는 변화를 못 본다. 노출하면 스키마 추가다.
  기본 권고: **노출하지 않음** (내부 신호 · 웹앱은 카운트 감소만 관측)
- **Q4** Toolathlon·Exgentic 어댑터에도 센티넬 훅을 열어둘지.
  현재 두 코퍼스에서 매칭 0건이므로 **훅만 열고 집합은 비움** 이 권고

---

## 7. 범위 밖 · 미해결 (넘겨 읽지 말 것)

1. **비용 산출은 손대지 않는다.** cascade 도구 출력 가격 책정은 별건 dry-run 이
   기각했다 (효과 $0.000021 · `_cascade_pricing_dryrun_RESULTS.md`). 이 개정안과 무관.
2. **표본**: CC 40 세션(사설) · Corpus B 4파일 240 트레이스(공개 HF 샘플).
   **Corpus C(Exgentic) 미측정** · Corpus B 전량(6,780) 미측정.
3. **공개 WR 수치(0.92~0.98)에 영향 없을 것으로 예측**하나(P6) Corpus B/C 전량
   재실행으로 확인하지 않았다. 승인 후 구현 단계에서 확인 대상.
4. **부수 관측(이 개정안 범위 밖)**: Corpus B 샘플에서 어댑터가 `ValueError` 로
   하드 실패한 엔트리 **23건** (`tool_calls.function.arguments` JSON 파싱).
   `iter_toolathlon_traces` 는 제너레이터라 한 건이 파일 전체를 중단시킨다.
   별건 사안으로 기록만 한다.
5. **동결 가드**: 이 변경이 동결 테스트·manifest 와 충돌하면 가드를 삭제·skip 하지
   않는다. per-trace 로 drift 를 검증하고 strict xfail + 사유를 남긴다
   (`feedback_intentional_drift`).
