# CC_TRANSCRIPT — Claude Code 원본 transcript 리콘 결과

**Scope**: 이 문서는 **제품 입력 포맷** 명세다. SWE-chat 파생 데이터셋(`conversations.parquet`) 이 아니라 Claude Code 원본 JSONL (`~/.claude/projects/<slug>/<uuid>.jsonl`) 을 대상으로 한다.

**Fold-back 규칙 (SPEC 규칙 7)**: 외부 사실을 raw 로 확인한 후 SPEC 에 반영. 코드 어댑터 작성 전 리콘 결과부터 문서화한다.

**근거 스크립트**: `field_test/diagnostics/recon_cc_transcript.py` (Q1~Q6 · Q3-A/B · Q4-A/B/C).
**리콘 표본**: `~/.claude/projects/` 전 9 프로젝트, 20 세션 파일 (2026-06-18 ~ 2026-07-17). 세부 통계는 최근 완료 세션 1개 (`f96aee88-...`, 779 라인) 기준. 파일 크기 상위 아님 (규모 교란 회피).

**transcript 커밋 금지**: 실 작업 내용이라 레포에 원본 데이터 포함하지 않는다. 스크립트만 커밋.

---

## §21.1 — thinking 평문 부재 (검증됨)

**사실**: Claude Code assistant 메시지의 `type=thinking` content 블록은 `thinking` 필드가 빈 문자열이고, 대신 `signature` (base64 blob) 이 저장된다.

블록 구조 (Q4-A raw):
```json
{"type": "thinking", "thinking": "", "signature": "EsYCCokBCA8YAipAF6BPF7A61wbfDyfQNiYI9bcg...(len=444)"}
```
- keys: `['signature', 'thinking', 'type']`
- `type`: str len=8
- `thinking`: str len=0
- `signature`: str len=444

**전수 (Q4-B, 9 프로젝트 / 20 파일)**:
- thinking 블록 총 553건
- `thinking` 텍스트 non-zero **1건** (52자, 2026-06-30T12:28:27Z)
- `redacted_thinking` 블록: 0건

**시간 분포 (Q4-C)**:
- 2026-06: n=57, min=0, max=52, nonzero=1
- 2026-07: n=496, min=0, max=0, nonzero=**0**
- ts_min: 2026-06-18T15:04:44Z / ts_max: 2026-07-17T10:48:03Z

**결론**: Claude Code 는 thinking 평문을 저장하지 않는다. signature blob 만 남긴다. 2026-07 기준 100% 0자.

**함의**:
- SWE-chat 의 `assistant_thinking` = 128건 (37,978 assistant 행의 0.34%) 는 **파이프라인 손실이 아니다.** 원본에도 없다.
- "왜 다시 읽었나 판정 불가" 는 **데이터셋 한계가 아니라 벤더 구조 한계.** 원본 transcript 를 확보해도 이 한계는 유지된다.
- SWECHAT_SPEC.md 의 정직 경계 서술은 이 사실에 의해 근거 강화된다 (링크만, 아래 §21.5 교차 참조 참조).

---

## §21.2 — 토큰 usage 존재 (SWE-chat 과 다름)

**사실**: assistant 턴 344/344 (100%) 에 `message.usage` 딕셔너리가 부착된다.

**필드 (Q3-A)**:
```
input_tokens / output_tokens
cache_creation_input_tokens / cache_read_input_tokens
cache_creation.{ephemeral_1h_input_tokens, ephemeral_5m_input_tokens}
server_tool_use.{web_search_requests, web_fetch_requests}
service_tier / inference_geo / iterations / speed
```

**샘플 raw**:
```json
{"input_tokens": 6, "cache_creation_input_tokens": 11968,
 "cache_read_input_tokens": 18483, "output_tokens": 152, ...}
```

**output_tokens (nonzero 344/344)**: min=90, median=629, max=20223.

**tool 턴 (user role + tool_result) 에는 usage 미부착.**

### §21.2 미검증 가설 — tool_result 비용 귀속

5쌍 관찰 (Q3-B, Read tool_result char 수 vs 인접 assistant usage):
```
P#0: read_chars=3542   prev cache_r=30451  |  next cache_r=31544 cache_c=2864
P#1: read_chars=2852   prev cache_r=31544  |  next cache_r=34408 cache_c=2242
P#2: read_chars=757    prev cache_r=34408  |  next cache_r=36650 cache_c=635
P#3: read_chars=659    prev cache_r=36650  |  next cache_r=37285 cache_c=513
P#4: read_chars=1035   prev cache_r=44379  |  next cache_r=45048 cache_c=738
```

**미검증 가설**: `prev.cache_read + prev.cache_creation = next.cache_read` 가 관찰 3쌍에서 성립. tool_result 텍스트가 다음 assistant 턴의 `cache_creation_input_tokens` 에 계상되는 것으로 보인다. char/token 비율 1.19~1.40 (n=5).

**5쌍이다. 전수 검증 전까지 인용 금지 (규율 5).**

**백로그**: 전수 검증을 사전등록 (규칙 8: PR 먼저) 후 "실측 토큰 비용" 측정. 검증되면 낭비 판정에 토큰 값을 붙일 수 있다.

---

## §21.3 — tool_use ↔ tool_result 1:1 조인 (SWE-chat 과 다름)

**사실 (Q6, `f96aee88-...` 세션 기준)**:
- 조인 필드: `tool_use.id` ↔ `tool_result.tool_use_id`
- tool_use 총 180, unique 180
- tool_result 총 180, unique 180
- 중복 tool_use_id: 0
- 고아 (매칭 없는 result / use): 각각 0

**per-tool**:
- Bash: use=108, res_pair_max=1, use_with_>1_res=0
- Read: use=25, res_pair_max=1, use_with_>1_res=0
- Edit=31, Write=11, Grep=4, ToolSearch=1

**함의**:
- SWE-chat 의 Bash 1:N (SPEC §19.1: 1,732 keys, max_dup=5) 은 **파이프라인 산물이다.** 원본은 1:1.
- 1 세션 기준. **다세션 확인은 백로그.**

---

## §21.4 — 벤더 포맷 변경 독립 확증

**Read tool_result 라인 접두 (Q5, `f96aee88-...` 세션)**:

repr / ord:
```
'1\t# SPEC §19 — SWE-chat 실사용 코딩 세션 낭비 밀도 '
ord=[49, 9, 35, 32, 83, 80, 69, 67, ...]
```
- ord[0]=49 (`'1'`), ord[1]=**9 (TAB, U+0009)**
- 화살표(U+2192, ord=8594) **아님**.

**함의**:
- SWE-chat 에서 관찰한 "2026-03-28 벤더 포맷 전환" (SPEC §19.2 사실 A) 이 원본 transcript 로 확증됨.
- 캐시 마커 `unchanged` 17건 검출 → **`File unchanged since last read` 문구는 변경되지 않았다.**

**어댑터 설계 지침**:
- 벤더 출력 포맷은 변한다. 하드코딩 정규식에 의존하지 마라.
- **인식 실패 시 조용히 넘어가지 말고 명시적 에러**를 낸다.
- 근거 사례: `LINE_PREFIX = re.compile(r'^\s*\d+→')` 가 9,941건(15.66%)을 조용히 error 로 오분류 (SPEC §19.2 편차 7 계열).

---

## §21.5 — SWECHAT_SPEC.md 교차 참조

- **§21.1 (thinking 부재)** → `field_test/SWECHAT_SPEC.md` "핵심 한계" (line 147 근방) 의 "assistant_thinking 0.34%" 서술을 이 문서로 갱신 (근거 강화). 내용 복사 금지, 링크로 참조.
- **§21.3 (조인 1:1)** → `field_test/SWECHAT_SPEC.md` §19.1 Bash 1:N 서술 (max_dup=5) 은 파이프라인 산물임이 원본 리콘으로 확증.
- **§21.4 (포맷 전환)** → `field_test/SWECHAT_SPEC.md` §19.2 사실 A 예측(전환 시점) 이 원본으로 확증.

**이 문서 (CC_TRANSCRIPT.md) 가 원본 기준 사실의 단일 출처 (single source).** SWECHAT_SPEC.md 는 파생 데이터셋 분석 결과만 유지.

---

## §22 — 어댑터 매핑 규약 사전등록 (규칙 8: PR 먼저)

**사전등록 원칙**: 어댑터 매핑이 탐지 결과를 결정한다. 결과 나온 뒤에 매핑을 조정하면 "결과 보고 정의를 맞췄다" 와 구분 불가능하다. 이 문서를 push 후 PR 승인 뒤에만 어댑터 코드 작성.

**근거 파일 참조**:
- `src/clew/detect/structural.py` (repeat/pingpong 로직, `_normalize_input` L20, tool 입력 게이트 L68)
- `src/clew/detect/cascade.py` (φ 게이트 L36 — `origin.output_text` vs `candidate.output_text`)
- `src/clew/ingest/langgraph.py` L121 (`agent_or_node_id = s.name` — CC 어댑터도 이 규약 상속)

### §22.1 — 확정된 매핑 규약

| Span 필드 | CC 소스 | 근거 |
|---|---|---|
| `trace_id` | `sessionId` (JSONL top-level) | 세션 = 트레이스 단위 |
| `span_id` | `tool_use.id` | Q6: 180/180 unique, 중복 0 |
| `parent_span_id` | `parentUuid` (JSONL top-level) | CC 원본 필드 |
| `agent_or_node_id` | **`tool_use.name`** (Read/Bash/Edit/…) | Q5: 기존 로더가 `span.name` 사용 (langgraph.py:121). structural.py:68 이 tool kind 에 input 게이트를 걸므로 이름만으로 오탐 안 남 |
| `span_kind` | `"tool"` | v1 은 tool 스팬만 (§22.3) |
| `start_time` | assistant 라인 `timestamp` | tool_use 발신 시각 |
| `end_time` | **tool_result 라인 `timestamp`** | 근사 아님, 실측. Q6 1:1 조인으로 확보 |
| `input_text` | **`json.dumps(tool_use.input, sort_keys=True, ensure_ascii=False)`** | §22.2 |
| `output_text` | `tool_result.content` (텍스트 이어붙임) | φ 비교 대상 (cascade.py:36) |
| `token_count` | `None` | §21.2 Q3: tool 턴에 usage 미부착 |
| `model` | `None` | tool 스팬에 없음 |

### §22.2 — sort_keys 는 필수다

`_normalize_input` 은 `strip().casefold()` 뿐이다 (structural.py:20). **문자열 전체 비교**이므로 JSON 키 순서가 다르면 같은 호출을 놓친다.

- `sort_keys=True` 로 직렬화 결정론을 확보한다.
- **이건 정규화가 아니라 직렬화 규약이다.** 의미 정규화(경로 정규화 등)는 하지 않는다.
- 근거: SHA 재현성이 CRLF/LF 로 깨진 전례가 있다. 직렬화 비결정론은 조용히 틀린다.

### §22.3 — v1 어댑터는 tool 스팬만 만든다

**제외 대상과 근거**:

- **thinking 블록**: 평문 0자 (§21.1, 2026-07 기준 496/496 zero). `output_text` non-empty 검증 (model.py `_output_text_non_empty`) 실패 → 스팬 생성 불가.
- **assistant text 블록**: structural.py:68 의 input 게이트가 **tool kind 에만** 적용된다. `agent_or_node_id="assistant"` 로 두면 llm 스팬 다수가 전부 동일 그룹 → 대부분이 구조 후보 → φ 가 유일한 게이트가 된다. **E3 실측: 실데이터 same-topic 쌍은 φ 를 100% 넘는다** (`docs/ARCHITECTURE.md` L769, `docs/onboarding/05_validation.md` L187). φ 단독으로는 막지 못한다.
- **user text**: 탐지 대상 아님 (사용자 입력이지 에이전트 낭비 아님).
- **v1 범위: `tool_use ↔ tool_result` 쌍만.** 확장은 별도 사전등록.

### §22.4 — 재실행 전 예측 (결과 보기 전 기록)

#### 예측 1 — pingpong 오탐

`find_pingpong_candidates` (structural.py:76-92) 는 `agent_or_node_id` 만 본다. `input_text` 비교 없음. kind 필터는 주석(L79)뿐이고 **코드에 없다** (line 85-88 조건: `a1.id==a2.id AND b1.id==b2.id AND a1.id != b1.id`).

CC 에서 `Read → Bash → Read → Bash` 는 정상 작업 패턴이나 위 조건을 만족한다.

- **예측: pingpong 이 다수 검출되며 대부분 오탐이다.**
- **구체 예측: 779라인 세션 (`f96aee88-...`, tool_use 180) 에서 pingpong 후보 ≥ 10건.**
- 이는 SWECHAT_SPEC.md §19.1 `EDIT_TOOLS unknown_hit`, §19.2 `all_success` 와 동일 계열 (라벨/주석과 로직 불일치, 대상 미확인).
- **예측이 틀리면 틀렸다고 기록한다.** 결과 보고 pingpong 을 끄지 않는다.

#### 예측 2 — repeat_node

input 게이트 (structural.py:68) 가 range-level target 과 동등하게 작동할 것으로 예측한다. Q6 세션에서 Read 25건. 동일 input (`sort_keys` 직렬화 후 문자열 동일) 재호출만 후보가 된다.

- **구체 예측: repeat 후보 1~10건.** (25 Read 중 동일 인자 재호출 계열)
- 범위 밖이면 그대로 기록한다.

#### 음성 결과 정의

- 후보 0건이어도 어댑터 실패가 아니다. 한 세션에 낭비가 없을 수 있다.
- 그 경우 다른 세션 3개로 재확인하고, 여전히 0이면 **"이 코퍼스에서 검출 안 됨"** 으로 기록한다.
- **후보가 0이라고 매핑을 바꾸지 않는다.**

#### 중단 조건

1. Pydantic 검증 실패 → 즉시 멈추고 raw 출력. 매핑을 자체 판단으로 바꾸지 마라.
2. 조인 실패 (고아 `tool_use` / `tool_result`) 발생 → 멈추고 건수 보고. Q6 에서 0건이었다. 나오면 다른 세션 특성이다.
3. 파싱 실패 시 **조용히 skip 금지. 명시적 에러** (§21.4 어댑터 설계 지침).

### §22.5 — tool_result content 렌더링 규약 (2026-07-17 addendum)

**발견 (2026-07-17, 어댑터 첫 실행)**:
- 대상 세션 `f96aee88-...` tool_result 180건 중 **179건 `content: str`, 1건 `content: list`**.
- 그 1건은 `{"type":"tool_reference","tool_name":"TaskCreate"}` × 3 으로만 구성.
- text 블록 이어붙이기 → 빈 문자열 → Pydantic `output_text must be non-empty` raise.
- **§22.4 중단조건 1 이 정상 발동했다. 조용히 넘어가지 않았다.**
- tool_use raw: `id=toolu_01NmEu17XyHpHxm5ck1qCxb8, name=ToolSearch, input={query: "select:TaskCreate,TaskUpdate,TaskList", max_results: 3}, caller={type: direct}`. Q6 의 `ToolSearch: 1` 과 동일 메타 도구.

**전 세션 실측 근거 (20 파일 = 9 프로젝트 전수)**:
- list-form tool_result: **71건**.
- 블록 타입 value_counts: `text=34, image=15, tool_reference=36`.
- text-only list: 33.
- **non-text-only (text 블록 전무): 38건** ← 현재 케이스와 동일. `tool_reference` 만, 혹은 `image` 만으로 채워진 tool_result.
- mixed: 0.

**규약 (§22.1 output_text 행 개정)**:
- `content` 가 `str` → 그대로 사용.
- `content` 가 `list` → 블록별 렌더링 후 `"\n"` 으로 결합:
  - `type == "text"` → `block["text"]`
  - **그 외 모든 타입** → `json.dumps(block, sort_keys=True, ensure_ascii=False)` 로 직렬화
  - 매 블록에 대해 `warnings.warn` 으로 타입명 경고 (신호 보존)
- 렌더링 후에도 strip 결과가 빈 문자열 → **raise 유지** (진짜 빈 출력)

**설계 근거**:
1. **버리지 않는다.** 모르는 블록을 drop 하는 것은 `field_test/SWECHAT_SPEC.md` §19.1 `EDIT_TOOLS unknown_hit` ("미확인 Edit → 낭비 아님") 와 동일 계열의 실패다. 이름만 다르다.
2. **신호를 유지한다.** 경고가 계속 뜬다. 벤더 포맷 변경을 알아챌 수 있다 (§21.4). LINE_PREFIX 는 경고 없이 9,941건 (15.66%) 을 오분류했다.
3. **결정론적.** `sort_keys=True` — §22.2 와 동일 근거.
4. **특정 타입을 하드코딩하지 않는다.** `tool_reference` 만 특별 처리하면 다음 타입에서 재발한다. 벤더는 앞으로도 블록 타입을 추가한다.
5. **φ 에 의미가 있다.** 동일 인자로 같은 메타 도구를 두 번 호출하면 동일 `output_text` → cosine 높음 → 낭비 판정. 의미상 맞다.

**§22.4 예측 유지**: pingpong ≥ 10건, repeat 1~10건. 이 addendum 은 output_text 표현 규약이며 **탐지 정의를 바꾸지 않는다.** 예측 조정 없음.

### §22.6 — 첫 실행 결과 (2026-07-17)

**대상**: `f96aee88-df87-41a6-8f6e-be05d3928018.jsonl` (§21 리콘 세션과 동일).

**실행 명령**: `python -m clew analyze <path>.jsonl --no-snippets`

**어댑터 결과**:
- total_spans: 181 (synthetic root 1 + tool 180)
- tool_name_counts: `{Bash: 108, Read: 25, Write: 11, Edit: 31, Grep: 4, ToolSearch: 1}`
- 경고 (tool_reference): 3건 (모두 동일 tool_use = ToolSearch 1건)
- 조인 실패: 0
- Pydantic 검증 실패: 0 (§22.5 addendum 반영 후)

**§22.4 예측 대조**:

| 지표 | 예측 | 실측 | 판정 |
|---|---|---|---|
| pingpong 후보 | ≥ 10 | **6** | **빗나감** |
| repeat 후보 | 1 ~ 10 | **0** | **빗나감** |
| 최종 waste (φ ≥ 0.514345 통과) | — | **3** | Edit(cos=1.0000), Write(0.9959), Bash(0.6577) |

**빗나감 사실 기록 (조정 금지)**:
- pingpong 6 < 10: 4-window 교대 패턴이 예상보다 적었다. 실측 pair 분포: Bash-Bash × 2, Write-Write × 2, Read-Read × 1, Edit-Edit × 1 (원소 개수 6 = 3 페어 × 2).
- repeat 0: `sort_keys` 직렬화 후 완전 동일 인자 재호출 부재. 25 Read / 108 Bash 이 있음에도 인자가 매번 달랐다는 뜻. 이 세션 특성.
- 예측이 틀린 방향: 둘 다 **과대 예측**. 낭비 시그널이 예측보다 희소.

**함의 (추측 아닌 관찰)**:
- 이 세션 하나에서 pingpong 원소 6 중 3 (50%) 이 φ 통과. 단일 세션 표본으로 일반화 금지.
- repeat 0 은 이 세션이 "range/keyset 이 매번 다른 세션" 임을 의미. 다른 세션에서 재확인 필요 (백로그).
- Edit cos=1.0000 은 완전 동일 output_text 를 의미 — 세션 내 검사 필요 (백로그, transcript 노출 없이).

### §22.7 — 첫 실행 결과 진단 (2026-07-17 fold-back, 규칙 7)

**결과 요약**: waste 3건 **전부 오탐**.

| # | node | cosine | 실제 내용 | 판정 |
|---|---|---|---|---|
| 1 | Edit | 1.0000 | 같은 파일 (SWECHAT_SPEC.md), **다른 new_string** | 오탐 |
| 2 | Write | 0.9959 | **다른 파일 2개 생성** (basename 다름) | 오탐 |
| 3 | Bash | 0.6577 | 다른 스크립트, 출력 로그 상이 | 오탐 |

**근거 스크립트**: `field_test/diagnostics/diag_cc_first_run.py` (Q1~Q5).

#### 결함 1 — origin 고정 (structural.py:64,68)

```
origin = occurrences[0]
for cand in occurrences[1:]:
    ...
    _normalize_input(cand.input_text) == _normalize_input(origin.input_text)
```

- origin 이 그룹 **첫 등장 하나로 고정**된다. occurrences[i] 와 occurrences[j] (i, j ≥ 1) 가 동일해도 origin 과 다르면 **둘 다 탈락**.
- **실측 증거**: Read `(file_path, offset, limit)` 완전 동일 재호출 4건 존재. **repeat 후보 0건.**
- `field_test/SWECHAT_SPEC.md` §19 분석은 모든 쌍을 비교했다. **제품과 분석의 알고리즘이 다르다.**
- 영향 범위: repeat_node, requery_known (requery 는 repeat 의 특수형, structural.py:8 주석).

#### 결함 2 — pingpong 에 input 게이트 부재 (structural.py:85-88, 99)

- `find_candidates = find_repeat_candidates ∪ find_pingpong_candidates` (structural.py:99).
- pingpong 조건은 `agent_or_node_id` 만 비교 — input_text 무시.
- **waste 3건 전부 pingpong 출처** (repeat=0 이므로 논리적 귀결).
- §22.4 예측 1 은 **건수로는 빗나감 (6 < 10), 오탐 방향으로는 적중** — 6 pingpong 원소 중 3이 φ 통과, **3/3 오탐**.
- `field_test/SWECHAT_SPEC.md` §19.1 `EDIT_TOOLS unknown_hit`, §19.2 `all_success` 와 동일 계열 (라벨/주석과 로직 불일치, 대상 미확인).

#### 결함 3 — Edit/Write output_text 가 템플릿 (φ 계층 무력화)

- Edit 31건: **distinct output_text 5/31 (16%)**. len 94~120. `"The file <path> has been updated successfully."` 순수 성공 문구.
- Write 11건: distinct 11/11 이나 접두사 `"File created successfully at: <path>"`. path 만 변수 → embedding 유사도 ≈ 1.
- **φ 는 output_text 를 비교한다** (`src/clew/detect/cascade.py:36`). 템플릿 위에서는 항상 높은 cos.
- **함의**: Edit/Write 에 대해 semantic 계층은 판별력이 없다. **구조 게이트가 유일한 방어**다. 결함 1·2 가 그 방어를 뚫는다.
- `docs/ARCHITECTURE.md` E3 (semantic 이 실데이터 same-topic 분리 실패) 보다 심각. 여기선 topic 도 아니고 **고정 템플릿**이다.

#### 결함 4 — Bash `description` 이 command 재호출을 가림

- Bash 108건 key-set: 97× `(command, description)`, 10× +`timeout`, 1× +`run_in_background`.
- `description` distinct **106/108** — 매 호출 새 문구.
- `command` distinct 99/108 (91.7%). **command-only 동일 재호출 9건** (`git status --porcelain` × 3, `cd ... && git log ...` × 4, `cd ... && git status` × 3, `git diff pyproject.toml` × 2, `ls field...` × 2).
- input 전체 직렬화 (§22.1) 가 이 9건을 소실시킨다. **repeat=0 의 직접 원인 중 하나.**
- ※ `field_test/SWECHAT_SPEC.md` §20 은 command 문자열만 보는 설계였다. **여기서 갈린다.**

#### 관찰 — §19 87.0% 의 자기 데이터 재현 (방향만, 값 인용 금지)

| | 건수 |
|---|---|
| `file_path` 만 같은 Read 재호출 | 13 |
| `(file_path, offset, limit)` 전부 같은 재호출 | 4 |
| **차이 (range 다른 재읽기)** | **9 = 69.2%** |

- `field_test/SWECHAT_SPEC.md` §19.1 오탐 제거율 87.0% 와 **같은 방향**. 값은 다름.
- **n=25. 단일 세션. 인용 절대 금지.** 방향 재현 사실만 기록.
- **이는 남의 데이터 (SWE-chat) 로 잰 논지가 자기 데이터에서 처음 재현된 사례**다.

#### 정직 경계 갱신

- **"clew analyze 가 Claude Code 세션에서 낭비 N건 검출" 인용 금지.** 첫 실행 3/3 오탐. 결함 1~4 수정 전까지 검출 수치는 무의미하다.
- T1 달성 사실 ("CC 로그를 읽고 파이프라인을 통과시킨다") 은 사실이다. 그건 말할 수 있다.

#### 미해결

- 결함 3 의 해법이 정해지지 않았다. Edit/Write 는 **input 이 신호이고 output 이 노이즈**로 보이나 (같은 파일 + 같은 new_string 재적용 = 낭비), 이는 §22 매핑과 cascade 설계 양쪽에 걸린다. **§22.8 사전등록 대상.**
- φ=0.514345 는 frozen 이다. **결함 3 을 φ 조정으로 풀지 않는다.**

---

## §22.8 — 구조 계층 결함 2건 사전등록 (2026-07-17, 규칙 8)

**범위**: 결함 1 (origin 고정) · 결함 2 (pingpong kind 필터). ①② 만.
**제외**: 결함 3 (Edit/Write output 템플릿) · 결함 4 (Bash description).

**사전등록 원칙**: 이 문서를 push 후 PR 오픈 (외부 타임스탬프 확정) 이후에만 코드 수정. 결과 보고 예측·중단조건·정의를 바꾸지 않는다. 규칙 8 실무 형태 (§19 부칙).

### §22.8.1 — 결함 1 수정: origin 고정 해제

**현재 (`src/clew/detect/structural.py:57-73`)**:
```python
groups: dict[str, list[Span]] = {}
for s in ordered:
    groups.setdefault(s.agent_or_node_id, []).append(s)
...
for occurrences in groups.values():
    if len(occurrences) < n:
        continue
    origin = occurrences[0]
    is_tool = origin.span_kind == "tool"
    ...
    for cand in occurrences[1:]:
        if is_tool and _normalize_input(cand.input_text) != _normalize_input(origin.input_text):
            continue
        ...
        pairs.append((origin, cand))
```

- origin 이 그룹 첫 등장 하나로 고정. occurrences[i], occurrences[j] (i,j ≥ 1) 가 동일해도 origin 과 다르면 둘 다 탈락.
- **실측 증거 (§22.7)**: Read `(file_path, offset, limit)` 완전 동일 재호출 4건 존재. repeat 후보 0건.

**개정**:
- **tool kind**: `(agent_or_node_id, _normalize_input(input_text))` 로 그룹핑. 각 하위그룹 내에서 `len(group) >= n` 확인 후 `origin = group[0]`, `cand = group[1:]`.
- **tool 아닌 kind**: 기존 동작 유지 (`agent_or_node_id` 만으로 그룹핑). 현재 코드가 tool kind 에만 input 게이트를 걸었으므로 이 구분을 보존한다.
- **O(n²) 아님.** dict 하위그룹핑으로 O(n).
- **Parent-AGENT gate (SPEC §16) 유지.** 하위그룹 내에서도 origin/cand 각각의 `_nearest_agent_ancestor_id` 를 비교.

**버그인가 정의 변경인가**:
- **의도** (`structural.py:2-6` docstring): "같은 노드를 같은 입력으로 반복 호출 = 낭비"
- **현재 코드**: "첫 등장과 같은 입력으로 호출"
- 의도와 코드가 불일치. **버그로 판단하나, 결과가 바뀌므로 사전등록한다.**
- `field_test/SWECHAT_SPEC.md` §19 분석은 모든 target 재등장을 카운트했다. **제품이 분석을 따라간다.**

### §22.8.2 — 결함 2 수정: pingpong kind 필터 추가

**현재 (`structural.py:76-92, 99`)**:
```python
# 핑퐁 노드는 kind=="llm" 이므로 입력 게이트 대상 아님(SPEC §8 2.1).   ← 주석 (L79)
if (
    a1.agent_or_node_id == a2.agent_or_node_id
    and b1.agent_or_node_id == b2.agent_or_node_id
    and a1.agent_or_node_id != b1.agent_or_node_id
):                                                                       ← 코드. kind 필터 없음
    pairs.append((a1, a2))
    pairs.append((b1, b2))

find_candidates = find_repeat_candidates ∪ find_pingpong_candidates      ← :99
```

- 주석은 llm 대상이라 하고, 코드엔 필터 없음.
- `field_test/SWECHAT_SPEC.md` §19.1 `EDIT_TOOLS unknown_hit`, §19.2 `all_success` 와 동일 계열 (라벨/주석과 로직 불일치).
- **실측 증거 (§22.7)**: waste 3건 전부 pingpong 출처, 3/3 오탐. CC 에서 `Edit → Bash → Edit → Bash` 는 정상 작업 패턴.

**개정**:
- `find_pingpong_candidates` 에 4-window 4개 스팬 모두 `span_kind == "llm"` 필터 추가.
- **주석(의도)에 코드를 맞춘다.**

**근거**:
- pingpong 의 의미는 "노드 A 와 B 가 서로 넘긴다" 는 멀티에이전트 패턴.
- tool 호출 교대는 정상 작업이지 pingpong 이 아니다.
- CC 어댑터는 tool 스팬만 만든다 (§22.3). 따라서 **CC 트레이스에서 pingpong = 0.** 의도된 결과 — CC 는 단일 에이전트 세션.
- LangGraph / OTel 트레이스 (Format A/C) 에서는 llm 스팬이 존재하므로 계속 동작.

### §22.8.3 — 기록만 (수정 없음, 이번 라운드 범위 밖)

#### 결함 3 — Edit/Write output_text 무판별력 (§22.7 결함 3 재기록)
- Edit 31건 distinct output 5/31 (16%). Write 접두사 `"File created successfully at: <path>"` 템플릿.
- **φ 는 Edit/Write 에 대해 판별력이 없다.** 구조 게이트가 유일한 방어.
- §22.8.1 수정으로 구조 게이트가 input 동일을 요구하게 되므로 실질 위험은 감소한다 (같은 파일 + 같은 `new_string` 이면 낭비, 다른 `new_string` 이면 하위그룹 분리로 후보 자체가 안 만들어짐).
- **φ = 0.514345 는 frozen. 조정하지 않는다.**
- **정직 경계**: 캐스케이드 2단계 (semantic φ) 가 Edit/Write 도구군에 대해 무의미하다는 사실을 남긴다. 향후 캐스케이드 설계 시 도구별 계층 활용도 차이를 명시.

#### 결함 4 — Bash `description` 이 command 재호출을 가림 (§22.7 결함 4 재기록)
- `description` distinct 106/108. command-only 재호출 9건 (`git status --porcelain` × 3 등) 이 input 전체 직렬화 (§22.1) 에서 소실.
- 해법 후보 "어댑터가 CC 도구 스키마를 안다 → Bash 는 command 만 서명" 은 하드코딩이며 `docs/CC_TRANSCRIPT.md` §21.4 어댑터 설계 지침 ("하드코딩 정규식에 의존하지 마라") 이 경고한 계열이다.
- **§22.9 별도 사전등록.** 어댑터가 도구 스키마를 아는 것이 정당한지 판단 필요.

### §22.8.4 — 재실행 전 예측 (결과 보기 전 기록)

대상 세션: `f96aee88-df87-41a6-8f6e-be05d3928018.jsonl` (§22.6 과 동일).

| 지표 | §22.6 실측 | 예측 | 근거 |
|---|---|---|---|
| pingpong 후보 | 6 | **0** | CC 는 tool 스팬만 (§22.3). llm 필터로 전멸 (§22.8.2) |
| repeat 후보 | 0 | **4 (±2)** | §22.7 결함 1 실측: Read full_input 재호출 4건 |
| 최종 waste (φ ≥ 0.514345 통과) | 3 | **4 (±2)** | Read output_text = 파일 내용. 동일 range 재읽기 → cos ≈ 1 |
| 오탐 (사람 판정) | 3/3 | **0/N** | §22.6 3건은 전부 pingpong 출처. pingpong 제거 시 소멸 |

**예측 근거 부기**:
- Bash command-only 재호출 9건은 §22.8 범위 밖 (결함 4). **후보로 안 나온다.** description 필드 차이로 input_text 하위그룹이 서로 다르게 분리됨.
- 최종 waste 가 나와도 **"후보"이지 확정 낭비가 아니다** (§21.1: thinking 부재로 판정 근거 약함). 판정은 세션 소유자가 한다.
- **예측이 틀리면 틀렸다고 기록한다.** 예측에 맞춰 정의 조정 금지.

### §22.8.5 — 음성 결과 정의

- **repeat 후보가 0 이면 수정 실패가 아니다.** `_normalize_input` 은 `strip().casefold()` 뿐이므로 JSON 직렬화 차이 (공백, 유니코드 정규화 등) 로 놓칠 수 있다. 그 경우 **원인을 raw 로 규명하고 기록.** 정의를 바꾸지 않는다.
- **오탐이 0 이 아니면 그대로 적고 원인 진단.** 결함 3·4 로 설명되는지 확인.

### §22.8.6 — 중단 조건

1. **기존 테스트 회귀** → 즉시 멈추고 실패 테스트명 + 전문 출력. 특히 pingpong / repeat 테스트가 tool 스팬 가정 위에 있으면 그 테스트가 무엇을 의도했는지 확인 필요. **테스트를 고쳐서 통과시키지 마라.**
2. **Format A / Format C (OTel / OpenInference) 트레이스 결과가 바뀜** → 멈추고 보고. §22.8.1 의 tool 하위그룹핑이 기존 로더에 영향을 줄 수 있다.
3. **φ / N / model 상수를 건드려야 하는 상황** → 즉시 멈춤. **frozen.**

### §22.8.7 — 규칙 8 커밋 체인 (사전등록 시각 증명)

| 커밋 | 목적 | 결과 산출 이전/이후 |
|---|---|---|
| (이 커밋) | §22.8 사전등록 (본문 · 예측 · 중단조건) | 이전 |
| (다음) | `structural.py` 수정 (§22.8.1 + §22.8.2) | 이전 |
| (그 다음) | 재실행 결과 + 관찰 | 이후 |

- 이 커밋은 코드 수정 전에 push 되어 PR 오픈 시각으로 외부 타임스탬프 확정.
- §22.8 본문은 이 커밋 이후 무수정. 관찰은 별도 섹션 (§22.8 결과, 추후 추가).
- 병합은 반드시 merge commit (SPEC §19 규칙 8 부칙).

### §22.8.8 — 재실행 결과 및 관찰 (2026-07-17)

§22.8 본문은 사전등록 시점 (`031639f`) 그대로. 결과와 관찰만 이 섹션.

**대상**: `f96aee88-df87-41a6-8f6e-be05d3928018.jsonl` (§22.6 과 동일).
**코드 커밋**: `ed58d5d` (structural.py 수정, `031639f` 이후, 결과 산출 전).
**테스트**: `python -m pytest -q` → **198 passed** (`tests/test_claude_code_ingest.py` UserWarning 1건 = §22.5 image 타입 신호 보존).

#### 예측 대조 (§22.8.4)

| 지표 | §22.6 실측 | 예측 (§22.8.4) | 이번 실측 | 판정 |
|---|---|---|---|---|
| pingpong 후보 | 6 | **0** | **0** | **적중** |
| repeat 후보 | 0 | **4 (±2)** | **6** | **적중 (상한선)** |
| 최종 waste (φ ≥ 0.514345 통과) | 3 | **4 (±2)** | **4** | **적중** |
| 오탐 판정 | 3/3 (§22.7) | **0/N** | **판정 대기** (raw 아래) | 세션 소유자 판정 |

**예측 근거 성립 확인**:
- pingpong 0: §22.8.2 `span_kind == "llm"` 필터로 CC (tool 스팬만) 에서 전멸. 의도된 결과.
- repeat 6: §22.7 결함 1 실측 4건은 origin 고정 해제 후 하한. 상한 6 은 origin 이 여러 cand 와 페어링된 경우 포함 (예: waste #1·#2 는 동일 origin 이 2 cand 와 각각 페어링).

#### waste 4건 raw (§22.7 Q2 형식, 경로 basename 마스킹, output 앞 200자)

##### waste #1 — cos=0.7888
- `origin.name=Read` span_id=`toolu_01FpniGnXxoE4AXg1R5SodkT`
- `cand.name=Read` span_id=`toolu_01JRtN5gD5Kasqx6s5uZ7eZA`
- **input_text (len=103, 동일)**:
  ```json
  {"file_path": "C:\\Users\\User\\Desktop\\Custos - clwe project\\field_test\\run_swechat_waste_scan.py"}
  ```
- origin.output_text[0:200]:
  `'1\t"""SPEC §19 SWE-chat waste density scan.\n2\t\n3\tPre-registered: field_test/SWECHAT_SPEC.md (commits 9ddb9bc, 9d9fab9, b1450f1).\n4\tDo NOT modify poolBASENAME(waste rules after seeing results.\n5\t)"""\n6\tim'`
- cand.output_text[0:200]:
  `'1\t"""SPEC §19 SWE-chat waste density scan (v1\'~v4\' — post-amendment).\n2\t\n3\tPre-registered: field_test/SWECHAT_SPEC.md.\n4\tAmendment 2026-07-16 (§19.1): EDIT_TOOLS pool contamination fix —\n5\ttool_name i'`
- same_basename: True (`run_swechat_waste_scan.py`)
- **output_text 다름** (원본 vs post-amendment). 판정 재료: origin↔cand 사이 파일 편집 있었는지.

##### waste #2 — cos=0.7888
- `origin.name=Read` span_id=`toolu_01FpniGnXxoE4AXg1R5SodkT` **(waste #1 과 동일 origin)**
- `cand.name=Read` span_id=`toolu_019vePnaQrtbXGzKLNvF7pUn`
- **input_text (len=103, waste #1 과 동일)**:
  ```json
  {"file_path": "C:\\Users\\User\\Desktop\\Custos - clwe project\\field_test\\run_swechat_waste_scan.py"}
  ```
- origin.output_text[0:200] — waste #1 origin 과 동일.
- cand.output_text[0:200] — waste #1 cand 와 동일 (동일 post-amendment 상태를 두 번 재읽기?).
- same_basename: True.
- 판정 재료: waste #1 과 waste #2 의 cand 두 개가 서로 같은 상태인지 (post-amendment 후 반복 재읽기) 다른 상태인지.

##### waste #3 — cos=1.0000
- `origin.name=Read` span_id=`toolu_016ruLyijuJSr2qDxWRagJen`
- `cand.name=Read` span_id=`toolu_01FyRBDgmMtoMk83jhGPbfpY`
- **input_text (len=93, 동일)**:
  ```json
  {"file_path": "C:\\Users\\User\\Desktop\\Custos - clwe project\\field_test\\SWECHAT_SPEC.md"}
  ```
- origin.output_text[0:200]:
  `'1\t# SPEC §19 — SWE-chat 실사용 코딩 세션 낭비 밀도 측정 (사전등록)\n2\t\n3\t## 목적\n4\t실사용 Claude Code 세션에 "같은 대상 + 실질 변화 없음" 낭비가 존재하는지, 밀도가 얼마인지 측정.\n5\t\n6\t## 분석 pool (frozen)\n7\t- \`agent == "Claude Code"\`\n8\t- \`tool_name == "R'`
- cand.output_text[0:200] — **origin 과 완전 동일 문자 (cos=1.0000)**.
- same_basename: True (`SWECHAT_SPEC.md`).
- 판정 재료: 앞 200자만 동일한지, 전문이 동일한지. cos=1.0000 은 전체 output_text 문자열 embedding 일치.

##### waste #4 — cos=0.5359
- `origin.name=Bash` span_id=`toolu_017bFHLqnQgAawh1jtWVMy3g`
- `cand.name=Bash` span_id=`toolu_01YSSm43o4VmMzA17sX8Cqqb`
- **input_text (len=127, 동일)**:
  ```json
  {"command": "cd \"C:/Users/User/Desktop/Custos - clwe project\" && git status --short 2>&1", "description": "Git status short"}
  ```
- origin.output_text[0:200]:
  `' M field_test/SWECHAT_SPEC.md\n M pyproject.toml\n?? field_test/diagnostics/'`
- cand.output_text[0:200]:
  `' M pyproject.toml'`
- same_command: True.
- **output_text 다름** (git 상태 변화). 판정 재료: 상태가 바뀔 만한 이벤트 (커밋/스테이징) 가 사이에 있었는지.

#### 관찰 1 — 결함 4 (Bash description) 는 이 세션에서 우회됨
- waste #4 는 `description="Git status short"` 로 완전 일치. §22.7 결함 4 (description distinct 106/108) 는 통계이며, description 이 동일한 경우도 존재한다는 것.
- **§22.9 (결함 4 별도 사전등록) 필요성 유지**: waste 로 검출되지 않은 command-only 재호출 9건은 여전히 소실 (input 전체 문자열 비교 상). 이번 세션에서는 우연히 하나 잡힌 것.

#### 관찰 2 — repeat 상한선 (6 = 예측 4±2 최댓값)
- §22.7 결함 1 진단 시 "full_input 재호출 4건" 이었으나 이번 repeat 6.
- 차이 원인: origin 이 여러 cand 와 각각 페어링. (예: waste #1·#2 는 동일 origin span_id 가 두 cand 와 각각 페어. `find_repeat_candidates` 는 하위그룹 내 (origin, cand_i) 쌍을 모두 반환).
- Distinct cand span_id 기준으로는 4~5 정도 (waste 4건 = distinct cand span_id 4).
- §22.8.1 개정 의도 부합 — "같은 서명 재등장 모두 페어링" 이므로 origin 1 × cand 2 = pair 2 가 정상 산출.

#### 관찰 3 — repeat 6 vs waste 4 의 gap
- repeat 6 중 waste 4 = φ 통과 4건. 2건은 φ < 0.514345 (탈락).
- φ 계층이 여기서 판별력 있는 사례. Read output 이 파일 내용이라 cos 이 실제 유사도 반영.
- §22.7 결함 3 (Edit/Write output_text 무판별력) 은 이번 세션에서 트리거 안 됨 — Edit/Write 재호출 자체가 하위그룹핑 후 부재.

#### 정직 경계 (§22.8.8 시점)

**말할 수 있는 것**:
- §22.8.1 (origin 고정 해제) · §22.8.2 (pingpong llm 필터) 코드 개정 완료. pytest 198 통과.
- 예측 3개 (pingpong · repeat · waste) 모두 사전등록 구간 내 적중.
- **오탐 판정은 세션 소유자 몫**: 4건 raw 전문 위에 제시. 그중 waste #1·#2 는 output 이 다르므로 파일 편집이 있었을 가능성 (§19 낭비 정의: 그 사이 Edit 있으면 낭비 아님). waste #4 는 git 상태 변화 (정당한 재확인 가능성). waste #3 은 output 완전 동일 (재읽기 후보 성립).

**말할 수 없는 것**:
- **"clew analyze 가 4건 낭비를 검출했다" 단독 인용 금지.** §21.1 thinking 부재로 "왜 다시 읽었나" 판정 근거 약함 유지. **후보이지 확정 낭비 아님.**
- **오탐 0/N 예측 적중 여부는 판정 이후에만 결론.** 지금은 판정 대기.
- **§22.8.8 결과를 다른 CC 세션으로 일반화 금지.** 단일 세션.

#### 미해결

- **결함 3 (Edit/Write output 템플릿)**: 이 세션에서 트리거 안 되어 실증 없음. Edit/Write 재호출이 있는 다른 세션에서 재확인 필요. 백로그.
- **결함 4 (Bash description)**: `field_test/diagnostics/diag_cc_first_run.py --q 4` 로 확인된 command-only 재호출 9건은 여전히 후보로 안 뜬다. §22.9 별도 사전등록 대상.
- **세션 소유자 판정 반영**: waste 4건 오탐/진성 라벨링 후 §22.8.8 에 추가.

---

## §22.10 — tool 스팬 동일성 게이트 사전등록 (2026-07-17, 규칙 8)

**범위**: `span_kind == "tool"` 스팬의 φ 게이트 앞에 sha256 바이트 동일성 게이트 추가.
**제외**: φ 값 조정, 모델 교체, LLM 스팬 처리 (§8 2.2 원 정의 유지).

**사전등록 원칙**: 이 문서를 push 후 PR 오픈 (외부 타임스탬프 확정) 이후에만 코드 수정. 결과 보고 예측·중단조건·정의를 바꾸지 않는다.

### §22.10.1 — 사실 (전부 실측)

근거: `field_test/diagnostics/diag_phi_truncation.py`, `field_test/diagnostics/diag_waste_context.py` (2026-07-17 실행).

- **묵시적 절단**. `tokenizer.model_max_length = 128`, `truncation_side = "right"`. `SentenceTransformer.encode(text, normalize_embeddings=True, convert_to_numpy=True)` 에 truncation 인자 없음 → 내부 `tokenize()` 가 `model.max_seq_length = 128` 로 자름.
- **waste #3 (SWECHAT_SPEC.md Read)**: origin 7,732 tok / cand 9,943 tok. **앞 128 토큰의 token_id sha256 이 완전 동일** (`60f9095f5eef479ac21a411f7dd0f302d42b3b65b29c934230b971d9e4704f86`) → cosine 1.0000. **전문 sha256 은 불일치** (24,872B vs 32,163B).
- **세션 규모**: Read 25건 중 **24건 (96.0%)** 이 128 토큰 초과. p50=1,237 / max=9,943 tok.
- **무관 파일 φ 통과**: `cosine(SWECHAT_SPEC.md, run_swechat_waste_scan.py) = 0.517910 > φ=0.514345`. 두 파일은 md vs py 로 완전히 다른 내용.
- **모델은 정상**: `cosine('안녕하세요, 오늘 날씨가 참 좋네요.', 'The mitochondria is the powerhouse of the cell.') = -0.024409`. **긴 텍스트에서만 무너진다** (앞 128 토큰이 같으면 뒤가 어떻든 벡터 동일).
- **Q5 sha256 게이트 시뮬레이션**: §22.8.8 repeat 후보 6건 전부 `sha256_equal = False`. `edits_in_window = [3, 5, 5, 0, 9, —]` 로 독립 확증 (창문 안에 target 파일 편집이 있었음). **이 세션에 진짜 낭비 0건.**

### §22.10.2 — 개정

**tool 스팬에 대해 φ 앞에 바이트 동일성 게이트를 추가한다. 캐스케이드 3단.**

```
구조:      (agent_or_node_id, normalize(input_text)) 하위그룹 (§22.8.1)
동일성:    sha256(origin.output_text) == sha256(cand.output_text)   ← 신규
semantic:  φ                                                        ← llm 스팬만
```

- **`span_kind == "tool"`**: 2단에서 판정 종료. **φ 를 호출하지 않는다.** 출력이 바이트 동일이면 상태가 안 변한 것이고, 다르면 변한 것이다. 도구에는 패러프레이즈가 없다.
- **`span_kind != "tool"`**: 기존대로 φ. LLM 출력은 같은 말을 다르게 할 수 있다.
- **φ=0.514345 는 손대지 않는다. frozen.** 모델도 교체하지 않는다. **이것은 φ 조정이 아니라 게이트 추가다.**

### §22.10.3 — 정직 경계 갱신 (필수)

- **"캐스케이드 2단 구조가 F1 0.857"** → 이 F1 은 합성 데이터 결과이며, **실데이터 tool output 에 대해 2단(φ)은 판별력이 없다** (이 세션 Read 96%가 128 토큰 절단). 이 단서 없이 F1 0.857 인용 금지.
- **E3 재해석**: "semantic layer 가 실데이터 same-topic 을 분리 못 한다" 의 **원인이 128 토큰 절단으로 확인됨.** 기존 서술에 원인 병기.
- **"cosine 은 단독 신호가 아니다"** → **"cosine 은 128 토큰 초과 tool output 에 대해 신호가 아니다 (절단)."** 원인이 다르면 해법이 다르다.

### §22.10.4 — 미해결 (기록만, 이 라운드에서 확인 금지 — 범위 밖)

- **[미검증] φ 캘리브레이션 데이터의 텍스트 길이.** 합성 데이터가 128 토큰 이하였다면 절단이 드러나지 않았을 것이다. `validation/CALIBRATION_LOG.md` 및 캘리브레이션 입력의 토큰 길이 분포 확인 필요. **백로그.**
- **Edit 후보 #4** (`.gitignore`, `edits_in_window=0`, `o_len=96 / c_len=94`): output 이 템플릿인데 길이가 다르다. 미규명. 백로그 (§22.9 결함 4 재검과 별개).

### §22.10.5 — 재실행 전 예측 (결과 보기 전)

**대상**: `f96aee88-df87-41a6-8f6e-be05d3928018.jsonl` (§22.8.8 동일).

| 지표 | §22.8.8 실측 | 예측 (§22.10.5) |
|---|---|---|
| repeat 후보 | 6 | **6** (구조 계층 무변) |
| 최종 waste | 4 | **0** |
| 오탐 | 4/4 | **0/0** |

근거: Q5 `sha256_equal 0/6`. 게이트가 6건 전부 차단한다.
**틀리면 틀렸다고 기록한다.**

#### 음성 결과 정의

- **waste 0 은 실패가 아니다.** 이 세션에 진짜 낭비가 없다는 뜻이다. `edits_in_window` (3, 5, 5, 0, 9) 가 독립 확증.
- **0 이 나왔다고 게이트를 완화하지 않는다.**

#### 중단 조건

1. **기존 198 테스트 회귀** → 즉시 멈춤. **테스트를 고쳐서 통과시키지 마라.** 무엇을 의도한 테스트인지 확인 후 보고.
2. **OTel/OpenInference (llm 스팬) 결과 변화** → 즉시 멈춤. 이 개정은 tool 스팬만 대상. `span_kind != "tool"` 분기가 기존 φ 경로를 그대로 통과해야 한다.
3. **φ / N / model 상수를 건드려야 하는 상황** → 즉시 멈춤. **frozen.**

### §22.10.6 — 규칙 8 커밋 체인 (사전등록 시각 증명)

| 커밋 | 목적 | 결과 산출 이전/이후 |
|---|---|---|
| `0a4ad7b` | §22.10 사전등록 (본문 · 예측 · 중단조건) | 이전 |
| `e306150` | §22.10.1 근거 스크립트 커밋 (0a4ad7b 누락분, 후속 보완) | 이전 |
| (다음) | `cascade.py` 수정 (§22.10.2 3단 게이트, tool kind 만) | 이전 |
| (그 다음) | 재실행 결과 + 관찰 → §22.10.7 신설 | 이후 |

- 사전등록 커밋 `0a4ad7b` 은 코드 수정 전에 push 되어 PR 오픈 시각으로 외부 타임스탬프 확정.
- §22.10 본문은 `0a4ad7b` 이후 무수정. 관찰은 §22.10.7 로 별도.
- 병합은 반드시 merge commit (§19 규칙 8 부칙).

**편차 (2026-07-18, 규칙 7 부칙 적용 누락)**:
사전등록 커밋 `0a4ad7b` 에 §22.10.1 근거 스크립트 (`diag_phi_truncation.py`,
`diag_waste_context.py`) 2건이 누락되어 재현 경로 없이 push 되었다. 후속 커밋
`e306150` 으로 보완. §22.8 사전등록에서 `verify_v4_filter_contradiction.py`
누락과 동일 계열 2번째 — 규칙 7 부칙 (근거 스크립트 커밋) 적용 누락, 사람 측
지시 오류. **사전등록 무결성 영향 없음**: §22.10.1 의 관측 사실은 `0a4ad7b`
시점에 이미 확정되어 외부 타임스탬프를 획득했고, 스크립트는 그 사실의 재현
경로일 뿐 사실을 변경하지 않는다. `e306150` 은 결과 산출 (§22.10.7) 이전에
위치한다.

### §22.10.7 — 재실행 결과 (2026-07-18)

**커밋**: `883a27d` (`src/clew/detect/cascade.py` 3단 게이트, tool kind 만).
**테스트**: `python -m pytest -q` → **198 passed, 1 warning in 24.33s** (기존 회귀 0, OTel/OpenInference 결과 무변).
**세션**: `f96aee88-df87-41a6-8f6e-be05d3928018.jsonl` (§22.6/§22.8.8 동일).
**실행 명령**: `python -m clew analyze <세션> --no-snippets`.

**결과 (raw)**:

```
# Clew Waste Report
- trace_id: f96aee88-df87-41a6-8f6e-be05d3928018
- analyzed: 2026-07-18T06:36:31Z
- detector params: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2

## Result: no waste detected
No wasteful patterns found (wasteful=False).
```

**§22.10.5 예측 vs 실측**:

| 지표 | §22.8.8 실측 | 예측 (§22.10.5) | 실측 (§22.10.7) | 판정 |
|---|---|---|---|---|
| repeat 후보 | 6 | 6 | **6** | 적중 |
| 최종 waste | 4 | 0 | **0** | 적중 |
| 오탐 | 4/4 | 0/0 | **0/0** | 적중 |

**후보별 sha256 게이트 raw** (Q5 재실행, `diag_phi_truncation.py --q 5`):

```
  #1: name=Read   target='v4_reclassify.py'                sha256_equal=False  o_len=3444  c_len=3917   edits_in_window=3
  #2: name=Read   target='run_swechat_waste_scan.py'       sha256_equal=False  o_len=10511 c_len=12516  edits_in_window=5
  #3: name=Read   target='run_swechat_waste_scan.py'       sha256_equal=False  o_len=10511 c_len=12516  edits_in_window=5
  #4: name=Edit   target='.gitignore'                       sha256_equal=False  o_len=96    c_len=94     edits_in_window=0
  #5: name=Read   target='SWECHAT_SPEC.md'                  sha256_equal=False  o_len=16016 c_len=20357  edits_in_window=9
  #6: name=Bash   target=None                               sha256_equal=False  o_len=74    c_len=17
sha256_equal True 건수: 0/6
```

**해석 (§22.10.5 음성 결과 정의 준수)**:
- 6 후보 전부 sha256 불일치. 게이트가 §22.8.8 waste 4건을 전부 차단했다.
- **waste 0 은 실패가 아니다** — 이 세션에 진짜 낭비가 없다는 뜻이다. `edits_in_window` (3, 5, 5, 0, 9) 가 창문 안 파일 편집 존재를 확증. 상태가 바뀐 뒤의 재조회는 낭비가 아니다.
- **`edits_in_window=0` 인 후보 #4** (Edit .gitignore, o_len=96/c_len=94): output 길이 상이 → sha256 불일치 정상. §22.10.4 백로그 (다음 라운드).
- **게이트 완화 없음**. φ=0.514345 · N=2 · model 무변. 3상수 frozen.

**중단 조건 발동 여부**:
- 회귀 (조건 1): **없음** (198 전부 통과).
- OTel/OpenInference 결과 변화 (조건 2): **없음** (span_kind != "tool" 분기는 기존 φ 경로 무변).
- φ/N/model 상수 변경 (조건 3): **없음**.

**정직 경계** (§22.10.3 재확인):
- 이 결과는 **단일 세션** (§22.6 이후 재사용) 관측이다. 20세션 전수는 다음 라운드.
- **F1 0.857 (합성) 은 계속 인용 금지** 조건 유지. 실데이터 tool output 에 대한 φ 판별력 부재는 §22.10.1 로 근거화됨.

---

## §22.11 — compact 창문 제외 게이트 사전등록 (2026-07-18, 규칙 8)

**범위**: tool 스팬 waste 판정에서 origin↔candidate 창문 안에 compact 경계가 있으면 waste 에서 제외한다 (CC 어댑터 한정).
**제외**: φ / N / model / sha256 로직 변경, ExitPlanMode 재검색 판단 (§22.12 별건), 다른 로더 (OTel/OpenInference) 동작 변경.

**사전등록 원칙**: 이 문서를 push 후 PR 오픈 (외부 타임스탬프 확정) 이후에만 코드 수정. 결과 보고 예측·중단조건·정의를 바꾸지 않는다.

### §22.11.1 — 사실 (전수, 20세션)

근거: `field_test/diagnostics/classify_21_positives.py`, `field_test/diagnostics/scan_all_cc_sessions.py`, `field_test/diagnostics/diag_positive_context.py` (2026-07-18 실행).

§22.10.2 게이트 (sha256 tool kind) 통과 waste 총 **21건**. `~/.claude/projects/**/*.jsonl` 전 세션 스캔 (20 세션). classify_21_positives.py 는 각 waste 의 origin↔cand 창문 안에서 4 축을 기계적으로 측정: compact_in_win, edits_in_window, user_in_window, prev_user[:40].

- **compact_in_win == True: 16 / 21** — 창문 안에 `isCompactSummary == True` 또는 `compactMetadata` 필드를 가진 JSONL 라인이 존재.
- **agent == "ToolSearch" AND input 에 "ExitPlanMode": 3 / 21** — Plan 모드 재검색. 그중 1건은 compact 와 겹침 (c848299d #2).
- **compact == False AND user_in_win == 0 AND agent != "ToolSearch": 0 / 21** — 이 라운드에서 관측되지 않음.
- **세 범주 미해당 (나머지): 3 / 21** — 전부 user_in_win ≥ 2, gap 25~64 분. 소유자 판정 별건 (compact 게이트 범위 밖).

**핵심**: sha256_equal == True 이면서도 16 건이 compact 직후 재조회다. compact 는 컨텍스트를 소거하므로 재조회가 정당하고 (도구가 파일을 안 바꿨으니) 출력이 동일한 것이 당연하다. **sha256 게이트는 "출력 동일" 은 잡으나 "컨텍스트 소거 후 정당 재조회" 를 구분하지 못한다.**

**classify_21_positives.py 가 실제로 본 필드** (필드명 추측 아님):

```python
# field_test/diagnostics/classify_21_positives.py:104-113
def _window_compact_flag(entries, o_ln: int, c_ln: int) -> bool:
    for ln, d in entries:
        if not (o_ln < ln < c_ln):
            continue
        if d.get("compactMetadata") is not None:
            return True
        if d.get("isCompactSummary") is True:
            return True
    return False
```

**실 JSONL 확인** (session `72015129`, L352/L353):

```
L352 type='system' timestamp='2026-06-20T11:27:38.369Z'
  compactMetadata: {'trigger':'auto','preTokens':167184,'postTokens':16819,'durationMs':151404,...}
L353 type='user'   timestamp='2026-06-20T11:27:38.370Z'
  isCompactSummary: True
```

두 마커 라인 모두 `timestamp` 필드를 갖는다 (adapter 가 시각 기준으로 경계를 잡을 수 있음, §22.11.3 참조).

### §22.11.2 — 개정

**CC 어댑터에서 파싱된 Trace 의 tool 스팬에 대해서만**, origin↔cand 창문 안에 compact 경계가 있으면 waste 에서 제외한다 (`sha256_equal` 판정 이전에 조기 continue).

- **compact 감지 필드** (§22.11.1 확인분 두 개 전부 사용):
  - `entry.get("compactMetadata") is not None`  → 경계로 취급
  - `entry.get("isCompactSummary") is True`     → 경계로 취급
- **경계 자료**: 각 감지 라인의 `entry["timestamp"]` (`_parse_ts` 로 tz-aware datetime).
- **cascade 판정**: origin.start_time < 어떤 경계 timestamp < candidate.start_time 이면 스킵.
- **다른 로더는 no-op**: OTel/OpenInference 어댑터는 이 경계를 만들지 않으므로 (§22.11.3 참조) 기존 판정 그대로.

**이것은 게이트 추가다. φ / N / model / sha256 로직 무변.** cascade 3단 구조 (§22.10.2) 는 유지:

```
구조:      (agent_or_node_id, normalize(input_text)) 하위그룹 (§22.8.1)
compact:   창문 안 compact 경계 있으면 continue    ← 신규 (tool kind, CC 만)
동일성:    sha256(origin.output) == sha256(cand.output)   (§22.10.2)
semantic:  φ                                       (llm kind)
```

### §22.11.3 — 설계 확인 (코드 인용, 사전등록 단계에서)

**Q1. Span 자료구조에 turn index / line number 가 있나?**

없다.

```python
# src/clew/model.py:22-36
class Span(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: str
    parent_span_id: str | None
    agent_or_node_id: str
    span_kind: SpanKind
    start_time: datetime
    end_time: datetime
    input_text: str
    output_text: str
    token_count: int | None = None
    model: str | None = None
    cost_rate: float | None = None
```

`extra="forbid"` 로 필드 추가 불가. Span 자체를 확장하는 경로는 SPEC §8 1.1 을 흔든다 — **금지.**

**Q2. Trace 는 확장 가능한가?**

가능. `metadata: dict[str, Any] = Field(default_factory=dict)` (`src/clew/model.py:88`). 어댑터가 이미 `{"source": "claude_code_jsonl", "path": ...}` 를 넣고 있음 (`src/clew/ingest/claude_code.py:232-235`). **이 dict 에 compact 경계 timestamp 리스트를 추가하는 것이 자연스럽고 최소침습이다.**

**Q3. 어디서 감지하나?**

`src/clew/ingest/claude_code.py`. 이미 `_load_jsonl` 이 JSONL 을 라인 단위로 읽고 (§22.11.3 Q3.1), main `for entry in entries` 루프 (line 113) 가 모든 entry 를 순회한다. **이 루프의 앞단 (span 조인 이전) 에 compact 마커 감지 블록을 하나 추가하는 것이 자연스럽다.**

**Q4. 다른 로더는?**

`src/clew/ingest/otel_json.py` — OTel/OpenInference JSON 입력. compact 개념 없음. `Trace.metadata` 에 compact_boundaries 키를 넣지 않는다. `cascade.py` 는 `metadata.get("compact_boundaries", [])` 로 안전 조회 → 빈 리스트 → 게이트가 no-op. **CC 어댑터 산출물이 아닌 Trace 에 대해서는 판정이 §22.10.7 상태 그대로 유지된다.**

**Q5. 판정 경로 (cascade.py)**

```python
# 예상 diff, 사전등록 단계이므로 아직 미적용
if candidate.span_kind == "tool":
    # 신규: compact 창문이면 스킵 (metadata 없는 로더는 no-op)
    boundaries = trace.metadata.get("compact_boundaries", [])
    if any(origin.start_time < b < candidate.start_time for b in boundaries):
        continue
    # 기존: sha256 동일성
    if _sha256_bytes(origin.output_text) == _sha256_bytes(candidate.output_text):
        waste_span_ids.append(candidate.span_id)
        seen_candidates.add(candidate.span_id)
    continue
```

llm 경로 무변. tool 경로에서 sha256 판정 앞에 compact 게이트 삽입.

### §22.11.4 — ExitPlanMode 는 이번에 안 건드린다 (기록)

ExitPlanMode 재검색 (agent=="ToolSearch" AND input 에 "ExitPlanMode") 3 건 (§22.11.1):

| session8 | # | gap(s) | cmp | usr | prev_user[:40] |
|---|---:|---:|---|---:|---|
| 2502fe9a | 1 | 1140.0 | N | 1 | 프로젝트 루트에 진단표.md 파일을 새로 만드는 작업이야. |
| 8228879e | 1 | 2985.4 | N | 14 | Plan 모드. 계획 먼저, 승인 후 실행. SPEC.md §15가 사전 |
| c848299d | 2 | 6172.1 | Y | 12 | Plan 모드. 계획 먼저, 승인 후 실행. SPEC.md §18이 사전 |

- **c848299d #2 는 compact 게이트만으로 자동 제거된다** (cmp=Y).
- 나머지 2 건 (compact 없음) 은 §22.12 별건. **"메타 도구 재검색이 낭비인가" 는 이번 라운드에서 판정하지 않는다.**

### §22.11.5 — 재실행 전 예측 (결과 보기 전)

**대상**: `~/.claude/projects/**/*.jsonl` 20 세션 전수 (scan_all_cc_sessions.py 와 동일 집합).

| 지표 | §22.10 게이트 실측 | 예측 (§22.11.5) |
|---|---|---|
| 총 waste (21건) | 21 | **5** (16 compact 제거) |
| compact 세션 waste | 16 | **0** |
| ExitPlanMode ToolSearch (3건) | 3 | **2** (c848299d #2 는 compact 게이트에서 제거) |
| 나머지 (3건, compact 없음) | 3 | **3** (게이트 범위 밖 유지) |

**계산**: 21 − 16 (compact) = 5. 5 = 2 (ExitPlanMode w/o compact) + 3 (나머지, cmp=N usr≥2).

**틀리면 틀렸다고 기록한다.**

#### 음성 결과 정의

- **waste 가 5 아래로 더 떨어지면**: 예상 밖 감소. 원인 규명 (compact 감지 로직이 §22.11.1 근거의 16 건보다 더 많이 매칭). 게이트 정의 안 바꾼다.
- **waste 가 5 위로 남으면**: compact 감지 누락. 어느 waste 가 왜 잡히지 않았는지 raw 로 기록 (session, timestamp, 마커 라인 유무). 정의 안 바꾼다.
- **compact 세션 waste 가 0 이 안 나오면**: 감지 로직 결함. 사전등록 정의를 위반한 것이 아니라 구현이 정의를 못 따라간 것 — 구현 수정, 정의 유지.

#### 중단 조건

1. **기존 198 테스트 회귀** → 즉시 멈춤. **테스트를 고쳐서 통과시키지 마라.** 무엇을 의도한 테스트인지 확인 후 보고.
2. **OTel/OpenInference (llm 스팬 · non-CC Trace) 결과 변화** → 즉시 멈춤. 이 개정은 CC 어댑터 산출물의 tool 스팬만 대상. 다른 로더에서 Trace.metadata 에 compact_boundaries 키가 안 들어가는지 확인.
3. **φ / N / model / sha256 로직 변경 필요** → 즉시 멈춤. **frozen.**
4. **Span 자료구조 확장 필요** → 즉시 멈춤. `extra="forbid"` (§22.11.3 Q1). Trace.metadata 로 처리 안 되면 설계 재검.

### §22.11.6 — 규칙 8 커밋 체인 (사전등록 시각 증명)

| 커밋 | 목적 | 결과 산출 이전/이후 |
|---|---|---|
| (예정 A) | §22.11.1 근거 스크립트 3건 커밋 (규칙 7 부칙, 사전등록과 함께) | 이전 |
| (예정 B) | §22.11 사전등록 (본문 · 예측 · 중단조건) | 이전 |
| (그 다음) | `claude_code.py` / `cascade.py` 수정 (§22.11.2 게이트) | 이전 |
| (그 다음) | 재실행 결과 + 관찰 → §22.11.7 신설 | 이후 |

- 사전등록 커밋은 코드 수정 전에 push 되어 PR 오픈 시각으로 외부 타임스탬프 확정.
- §22.11 본문은 사전등록 커밋 이후 무수정. 관찰은 §22.11.7 로 별도.
- 병합은 반드시 merge commit (§19 규칙 8 부칙).
- **규칙 7 부칙 (근거 스크립트 커밋) 이번엔 사전에 적용**: §22.8/§22.10 사전등록에서 각각 1건씩 누락되었던 계열 오류를 이번 라운드에서 예방.

### §22.11.7 — 재실행 결과 (2026-07-18)

**커밋**: `42c3439` (`src/clew/ingest/claude_code.py` + `src/clew/detect/cascade.py` + `tests/test_cascade.py` compact 창문 게이트).
**테스트**: `python -m pytest -q` → **204 passed, 1 warning in 22.54s** (기존 198 + 신규 6, 회귀 0).
**대상**: `~/.claude/projects/**/*.jsonl` 20 세션 전수 (§22.11.5 동일 집합).
**실행 명령**: `python field_test/diagnostics/scan_all_cc_sessions.py`.

**§22.11.5 예측 vs §22.11.7 실측**:

| 지표 | §22.10 실측 | 예측 (§22.11.5) | 실측 (§22.11.7) | 판정 |
|---|---|---|---|---|
| 총 waste | 21 | 5 | **5** | 적중 |
| compact 세션 waste | 16 | 0 | **0** | 적중 |
| ExitPlanMode ToolSearch | 3 | 2 | **2** | 적중 |
| 나머지 (cmp=N, usr≥2) | 3 | 3 | **3** | 적중 |

**세션별 waste 변화 (compact 제거 내역)**:

| session (앞8) | §22.10 waste | §22.11.7 waste | compact 제거 | compact_boundaries 수 |
|---|---:|---:|---:|---:|
| 07f97584 (self) | 13 | 0 | −13 | 12 (6 compact × 2 마커) |
| 72015129 | 2 | 0 | −2 | 2 (1 compact) |
| c848299d | 3 | 2 | −1 | 2 (1 compact, #2 ToolSearch 창문 안) |
| 2502fe9a | 1 | 1 | 0 | 0 (compact 없음) |
| 8228879e | 2 | 2 | 0 | 2 (compact 07:58:09Z, 원조회 07:58:22Z 이전 — 창문 밖) |
| **합계** | **21** | **5** | **−16** | — |

**남는 5건 상세**:

```
1. 2502fe9a #1 ToolSearch target=None gap=1140.0s   (ExitPlanMode 재검색, cmp=N)
2. 8228879e #1 ToolSearch target=None gap=2985.4s   (ExitPlanMode 재검색, cmp=N)
3. 8228879e #2 Bash       target=None gap=2998.8s   ('(Bash completed with no output)' 재실행, cmp=N)
4. c848299d #1 Read       target=run_e3_diagnosis.py gap=3830.1s (cmp=N, usr=9)
5. c848299d #4 Bash       target=None gap=1505.0s   ('(Bash completed with no output)' 재실행, cmp=N)
```

- 5 건 전부 **compact_in_win == False** (§22.11.5 예측 정확). §22.11 게이트는 정의대로 작동.
- 2 건 (1, 2) 은 §22.11.4 대로 ExitPlanMode 재검색 — §22.12 별건.
- 3 건 (3, 4, 5) 은 소유자 판정 대기 (Bash 빈 출력 · Read 재조회 with 창문 편집 없음). **이번 라운드 정의로는 waste, 소유자가 별도 축으로 재판정할 수 있음.**

**중단 조건 발동 여부**:
- 회귀 (조건 1): **없음** (198 전부 통과 + 신규 6 통과 = 204).
- OTel/OpenInference 결과 변화 (조건 2): **없음** (`test_compact_gate_no_op_when_metadata_missing` 로 non-CC Trace no-op 검증).
- φ/N/model/sha256 로직 변경 (조건 3): **없음** — 상수 그대로, sha256 로직 그대로.
- Span 자료구조 확장 (조건 4): **없음** — `Trace.metadata` 만 확장 (기존 dict[str, Any] 슬롯 재사용).

**정직 경계**:
- 20세션 전수 실측. 다음 라운드에서 새 세션 추가 시 compact 감지 재검. `compact_boundaries` 는 두 마커 필드에 대해서만 반응하므로 벤더 포맷 변경 시 재확인 필요.
- 5 건 waste 는 이번 게이트 통과분이지 "진짜 낭비 5 건 확증" 이 아니다. 판정은 소유자 별건.
- §22.10.3 정직 경계 유지 (F1 0.857 합성 데이터, 실데이터 tool output φ 판별력 부재).
