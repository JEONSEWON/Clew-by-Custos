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
