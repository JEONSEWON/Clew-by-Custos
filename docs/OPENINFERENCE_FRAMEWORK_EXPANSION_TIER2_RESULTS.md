# OpenInference framework expansion — Results (2026-08-02, Tier 2, DRAFT)

**작성 시각 (UTC)**: 2026-08-02T00:00:00Z
**HEAD 해시**: `main @ d42c2a6` (Merge PR #62 `prereg/judgment-axes-revision` merged 2026-08-02) 기준으로 컷.
**저자**: 클로드 (측정자) / 사용자 (승인자)
**상태**: **DRAFT — 커밋 전 확인.**

**선행 사전등록**:
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (`0b619c5`, PR #53 merge `009be0c`) — Tier 1 원 사전등록.
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` · `docs/ADAPTER_R2_RELAXATION_PART2_PREREG.md` — R2 어댑터 완화 Part 1/2.
- **★ `docs/OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`** (`c568939`, PR #62 merge `d42c2a6`) — **판정 축 개정 (R1 필수 유지 · R2 tool 만 · R3 PARTIAL 편입 · R5 확인·기록만)**. **★ 이 리포트의 판정 기준.**

**선행 결과 리포트**:
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` — Tier 1 결과 리포트 (§3.4 addendum 로 개정 문서 링크).

**조사 실행일**: 2026-08-02 (개정 사전등록 merge 이후, 동일 세션).
**어댑터 코드 변경**: 없음.
**§3 판정 기준**: 개정 사전등록 §2/§3 그대로. **완화·강화 없음.**
**전체 pytest**: 458 passed, 조사 각 단계마다 실행.

---

## §0 — 이 리포트가 하는 것 · 하지 않는 것

**하는 것.**
- Tier 2 5 프레임워크 (Pydantic AI / Google GenAI / Haystack / Smolagents / MCP) probe 결과 기록.
- **개정 사전등록** §2/§3 기준으로 판정 (PASS / PARTIAL / FAIL / out-of-scope).
- **★ 유형 축 신설** — Tier 1 §2 3층 분해 (어댑터 / instrumentor / SDK) 를 이어받되, Tier 2 는 **결함 유형 A/B/C** 로 묶어서 개별 나열 대신 패턴을 드러냄.
- 방법론 § 신설 — 예측 근거 우선순위 규칙 (코드 구조 > upstream 이슈 목록).
- §4.1 이름 나열 규약 준수 공개 표현 산출.
- 후속 별건 사전등록 후보 명시.

**하지 않는 것.**
- 판정 기준 완화·강화 (개정 §2/§3 그대로).
- 어댑터 코드 수정.
- upstream 이슈 관여 (링크 인용만).
- Tier 3 실행 (승인 대기).
- 개정 사전등록 사후 수정 (§7 원칙 준수).

---

## §1 — 판정 요약

### §1.1 개정 사전등록 §2/§3 기준 그대로

| # | 프레임워크 | 판정 | 유형 | 핵심 사유 |
|---|---|---|---|---|
| T2.1 | Pydantic AI | **PARTIAL** | O3 저하 | O3 (TOOL `input.value`) 부재 (#3462 재현). structural subgroup pool 팽창 · 하류 sha256 게이트로 대부분 커버. R2 개정으로 tool-calling LLM `output.value` 부재는 판정 무관. |
| T2.2 | Google GenAI | **FAIL** | **유형 A** | TOOL span 미emit. `automatic_function_calling` 이 SDK 내부, 상위 LLM span 만. tool_calls 는 `message.tool_calls.N.*` attr 로만. |
| T2.3 | Haystack | **FAIL** | **유형 A + 유형 C** | TOOL span 미emit. Haystack instrumentor 아키텍처 제약 (Pipeline 컴포넌트만 wrap, Agent 내부 `_run_tool()` 은 plain function). ★ **사일런트 실패** (예외 없음, waste 0). |
| T2.4 | Smolagents | **PASS** | — | R1-R5 개정 축 전부 통과. `Tool.__call__` 직접 wrap. End-to-end cascade: 1 waste 정상 검출. |
| T2.5 | MCP | **out-of-scope** | 계측 스코프 다름 | `openinference-instrumentation-mcp` README 원문상 "only enables context propagation". LLM/TOOL semantic span 자체 미emit → 판정 대상 span 없음. FAIL 아님. |

**최종**: **PASS 1 / PARTIAL 1 / FAIL 2 / out-of-scope 1.**

### §1.2 원 판정 유지

**★ 개정 사전등록 §2/§3 기준을 사후에 손대지 않는다.** 판정은 개정 축 그대로. 개정 축 자체는 Tier 1 · Part 1/2 결과를 흡수한 정합 축 (개정 사전등록 §3.5 5축 매트릭스 그대로).

---

## §2 — ★ 유형별 분해 (Tier 2 신설 축)

Tier 1 §2 는 FAIL 원인 3층 분해 (어댑터 / instrumentor / SDK). Tier 2 는 **결함 유형 축**을 추가한다. 유형은 개별 프레임워크가 아니라 **여러 프레임워크에서 반복 관측되는 패턴**을 담는다.

### §2.1 유형 A — TOOL span 미emit (우리가 못 고침)

**증상**: instrumentor 가 tool 실행을 계측하지 않음. 우리 어댑터가 읽을 TOOL span 자체가 없다.

**해당**: **T2.2 Google GenAI · T2.3 Haystack** (+ Tier 1: **T1.3 Anthropic**).

**★ 원인이 프레임워크마다 다른데 증상이 같다**:

| 프레임워크 | 원인 (계측 계층) |
|---|---|
| T1.3 Anthropic | [#3392](https://github.com/Arize-ai/openinference/issues/3392) enhancement — instrumentor 가 Anthropic beta tool helpers 를 계측 대상에 안 넣음. tool call 이 있어도 LLM span 만 emit. |
| T2.2 Google GenAI | `automatic_function_calling=True` 로 SDK 가 tool 을 내부 실행 · 상위 `generate_content` LLM span 만 계측 · tool 실행 자체는 span 밖. tool_calls 는 LLM span `message.tool_calls.N.*` attr 로만 표현. |
| T2.3 Haystack | `HaystackInstrumentor` 는 `Pipeline.run` + `Pipeline._run_component` 만 wrap. Agent 는 pipeline 컴포넌트이지만 그 내부 `_run_tool()` 은 plain function → wrap 계층이 도달 못 함. |

**★ 이는 개별 결함이 아니라 계측기 생태계의 공통 한계다**:
- 프레임워크 자체는 정상 (tool 을 실제로 실행).
- SDK 도 정상 (function calling API 정상 제공).
- **instrumentor 가 tool 실행 지점에 wrap 을 못 걸었을 뿐**.
- 원인 계층이 다르니 한 번의 upstream fix 로는 못 고침 (각각 별도 fix 필요).
- **★ 우리 어댑터 문제 아님** — 계측기가 안 만드는 span 을 읽을 수 없다.

**대조 (Smolagents PASS)**: `SmolagentsInstrumentor` 는 `Tool.__call__` 을 **직접 wrap**. Agent 가 어떻게 tool 을 부르든 tool 실행이 계측됨. 이 wrap 지점 하나가 판정을 갈랐다.

**개정 판정 축에서의 위치**:
- 개정 R2 는 "tool 만 non-empty" — TOOL span 이 있어야 적용.
- TOOL span 자체가 없으면 R2 는 **N/A** (판정 대상 없음).
- 별건 결함으로 FAIL.

### §2.2 유형 B — R5 multi-trace (우리 제약)

**증상**: 프레임워크가 사용자 호출 1회를 1 trace_id 로 emit. 여러 번 호출하면 여러 trace_id. 우리 어댑터는 single trace_id 요구 → `ValueError: adapter expects single trace_id, got N`.

**해당**: **Tier 2 조사 완료 4 개 전부** (+ Tier 1: **T1.3 Anthropic**).

**5 프레임워크 다중 호출 = 다중 trace 매트릭스**:

| 프레임워크 | 사용자 호출 단위 = trace boundary |
|---|---|
| T1.3 Anthropic (direct SDK) | `client.messages.create()` |
| T2.1 Pydantic AI | `agent.run_sync()` |
| T2.2 Google GenAI | `client.models.generate_content()` |
| T2.3 Haystack | `Pipeline.run()` |
| T2.4 Smolagents | `agent.run()` |

**★ 예외 없음. Tier 2 조사 완료 4개 전부 + Tier 1 Anthropic = 5/5**.

**★ 이는 "우리 요구가 현실과 맞지 않는다" 를 5개 실측으로 뒷받침한다**:
- 개정 사전등록 §3.4 는 R5 를 "확인·기록만" 처리 (개정 X).
- 후보 (α) multi-trace 허용 (synthetic root 삽입) — Format C 가 이미 이 방향.
- 후보 (β) R5 유지 · 사용자 wrap 요구.
- Tier 1 시점: Anthropic 1 프레임워크만 발생 → 별건 후속.
- **Tier 2 완료 시점: 5 프레임워크 재현 → R5 개정 별건 사전등록의 근거 데이터**.

**판정 처리** (개정 §3.4 준수, 사용 규약으로 커버):
- Anthropic: SDK 계층에 trace scope 없음 → 사용자 wrap 필요. 지원 목록 배제 (개정 사전등록 §5.3).
- Pydantic AI · Smolagents: SDK 자체에 명확한 turn boundary → **"1 call per trace" 사용 규약** 명시로 커버.
- Google GenAI · Haystack: 유형 A 로 인해 이미 FAIL, R5 논점 부차적.

### §2.3 유형 C — 사일런트 실패 (우리 UX 문제 · 고칠 수 있음)

**증상**: 판정 실패인데 사용자에게 실패 신호가 없음. "no waste detected" 로 오인 가능.

**해당**: **T2.3 Haystack single-run**.

**★ 신호 품질 3단계 표** (Anthropic → Google GenAI → Haystack):

| 프레임워크 | 실패 시 사용자에게 보이는 것 | 신호 품질 |
|---|---|---|
| T1.3 Anthropic (direct) | `ValueError: adapter expects single trace_id, got 3` | **명시 예외 · 원인 힌트 있음** ("3개 trace_id 라 뭔가 잘못됐구나") |
| T2.2 Google GenAI | `ValidationError: trace must contain at least one span (the root)` | **예외 있음 · 원인 불명** ("0 spans 라는데 왜?") |
| **T2.3 Haystack single-run** | ★ **예외 없음. `waste_span_ids = []`.** | ★ **사일런트** ("waste 없음" 으로 오인) |

**Anthropic multi-run · Pydantic AI multi-run · Smolagents multi-run**: 모두 `ValueError: adapter expects single trace_id, got 2` — 명시 예외.

**★ 유형 C 는 우리 UX 문제이고 우리가 고칠 수 있다**:
- 유형 A (계측기 미emit) 는 우리가 못 고침 (upstream 대기).
- 유형 B (R5 제약) 는 개정 별건 필요.
- **유형 C 는 우리 어댑터가 "TOOL span 개수 0 + LLM span 있음" 같은 조건 감지 후 사용자에게 caveat 를 반환하는 방식으로 대응 가능**.
- 개정 사전등록 축 밖. 별건 사전등록 후보 (§8).

---

## §3 — ★ 방법론 § (신설)

### §3.1 예측 근거 우선순위

Tier 2 조사에서 두 개의 반례가 나왔다:

**T2.3 Haystack — upstream 이슈 기반 예측 뒤집힘**:
- 예측 근거: "upstream 이슈 목록에 Tier 1 계열 (output.value 미채움 · tool 미emit · trace 분산) 미표면 → PASS 가능성 높음".
- 실제 결과: **FAIL** — 유형 A. Haystack instrumentor 아키텍처 제약 (Agent tool 실행이 pipeline 밖) 은 upstream 이슈 목록에 안 올라옴.
- **★ upstream 이슈가 조용해도 문제가 없는 게 아니다**. 아키텍처 제약은 이슈로 안 올라오는 카테고리.

**T2.4 Smolagents — instrumentor 코드 실측 기반 예측 적중**:
- 예측 근거: `SmolagentsInstrumentor._instrument()` 소스 확인 → `Tool.__call__` 을 **직접 wrap** 하는 것 실측 → **TOOL span emit 확률 높음** 예측.
- 실제 결과: **PASS** — 예측대로.

### §3.2 규칙

**★ 예측 근거 우선순위**:
1. **instrumentor `_instrument()` 코드 실측** (무엇을 wrap 하는지) — **primary**.
2. **dump 원문 관찰** — probe 실행 후 primary evidence.
3. upstream 이슈 목록 — **secondary** (조용해도 안전을 보장 못 함).

**★ Tier 3 이 있다면 이 규칙을 따른다**:
- 첫 세팅 전에 instrumentor 소스에서 wrap 대상을 명시적으로 확인.
- upstream 이슈 목록은 "알려진 문제" 목록이지 "안전 목록" 아님.

### §3.3 이 규칙이 Tier 1 판정에도 소급 적용되는가

- Tier 1 판정은 이미 완료 · merge 됨. 소급 재검토 안 함 (개정 사전등록 §7.4 원칙).
- 다만 Tier 1 판정도 사후에 dump 원문을 primary 로 사용한 방식이라 실질 이번 규칙과 정합.
- 이 규칙은 **Tier 3 이후에 적용**.

---

## §4 — ★ 공개 표현 (§4.1 규약 준수)

### §4.1 실측 확인 목록 갱신

**Tier 1 시점 목록** (Part 2 재판정 후): "OpenInference 계측 5개 프레임워크에서 실측 확인 — LangChain, CrewAI, LlamaIndex, OpenAI Agents SDK, AutoGen."

**Tier 2 완료 후 목록**:

> **"OpenInference 계측 6개 프레임워크에서 실측 확인 — LangChain, CrewAI, LlamaIndex, OpenAI Agents SDK, AutoGen, Smolagents."**

**규약 준수 (§4.1)**:
- "실측 확인" 정확 정의 (개정 사전등록 §5.1): 프레임워크 A 를 그 프레임워크의 공식 instrumentor 로 계측 → 우리 어댑터 통과 → **판정 PASS**.
- **PARTIAL 은 지원 목록에 넣지 않음** (Tier 1 §4.2 규약): T2.1 Pydantic AI 배제.
- **FAIL 은 "이 instrumentor 로는 현재 읽을 수 없다"** (Tier 1 §2.2 규약): T2.2 Google GenAI, T2.3 Haystack.
- **out-of-scope 는 별개 카테고리**: T2.5 MCP — "지원 안 함" 이 아니라 "계측 스코프가 다름".

### §4.2 금지 표현

- "여러 프레임워크" · "다양한 프레임워크" · "OpenInference 지원" (이름 병기 없이).
- "N 개 프레임워크에서 실측 확인" 중 N 이 이름 나열 개수와 다름.
- FAIL 을 "이 프레임워크 지원 안 함" 이라 축약.

### §4.3 FAIL / out-of-scope 표현 (사용 안내용, 지원 목록 아님)

- **T2.2 Google GenAI / T2.3 Haystack**: "현재 이 instrumentor 로는 tool 실행이 계측되지 않아 waste 탐지 대상 span 이 생성되지 않는다." (Tier 1 Anthropic 표현과 동종.)
- **T2.5 MCP**: "MCP instrumentor 는 context propagation 만 담당하며 자체적으로 LLM/TOOL semantic span 을 emit 하지 않는다. host framework instrumentor 와 조합해서 사용."
- **T2.1 Pydantic AI (PARTIAL, 사용 안내 별건)**: "1 run per trace 규약 준수 시 R1-R5 통과. TOOL `input.value` 부재 (#3462) 로 structural candidate pool 팽창 · 하류 게이트로 대부분 커버되나 두 tool call output 이 우연히 같으면 false positive 가능."

---

## §5 — 관찰 자산 (§4.1 규약 준수)

### §5.1 봉투 shape 10-프레임워크 비교표 (Tier 1 표에 이어서 확장)

★ 이 표는 Tier 1 §5.1 5-프레임워크 표에서 확장. 도구별 응답 구조 매핑은 프로젝트 누적 자산.

| 프레임워크 | TOOL span emit | mime | 봉투 shape | `_extract_tool_output` 인식 | entity_id path |
|---|---|---|---|---|---|
| LangChain (fixture) | ✓ | application/json | `{"type":"tool","data":{"content":"<orig>"}}` | ✓ unwrap `data.content` | `ticket.id` (봉투 내부) |
| CrewAI (fixture) | ✓ | text/plain | 없음 (raw string) | ✓ raw 반환 | 미확인 (fixture 없음) |
| T1.1 LlamaIndex | ✓ | application/json | `{"blocks":[{"text":...}], "raw_output":<orig>, ...}` | ✗ (raw · preprocess leaf 추출) | `raw_output.ticket.id` |
| T1.2 OpenAI Agents | ✓ | application/json (dict) / None (str) | 없음 (반환값 직행 · 유효 JSON) | ✓ raw 반환 | `ticket.id` |
| T1.3 Anthropic (direct) | ✗ | — | 적용 불가 (유형 A) | — | — |
| T1.4 AutoGen | ✓ | text/plain | 없음 · **Python `str(dict)` 렌더링 (invalid JSON)** | ✓ raw 반환 | 불가 (json.loads 실패) |
| T2.1 Pydantic AI | ✓ | 부재 | 없음 · 유효 JSON 직행 | ✓ raw 반환 | `ticket.id` |
| T2.2 Google GenAI | **✗ (attr-only)** | — (LLM span 은 application/json) | 적용 불가 (유형 A) | — | 불가 |
| T2.3 Haystack | **✗ (attr-only)** | — (LLM/CHAIN 은 application/json) | 적용 불가 (유형 A) | — | 불가 |
| **T2.4 Smolagents** | **✓** | text/plain | **output 봉투 없음** (raw JSON string) · **input 봉투 `{"args":[],"kwargs":{...}}`** | ✓ raw 반환 | `ticket.id` (봉투 없음) |

**관측 갱신**:
- 봉투 방식 스펙트럼: 완전 봉투 (LangChain / LlamaIndex) → 부분 봉투 (Smolagents input) → 봉투 없음 (CrewAI / OpenAI Agents / Pydantic AI) → attr-only (Google GenAI / Haystack) → 계측 불가 (Anthropic direct).
- entity_id 추출 가능 4 / 미확인 1 / 불가 4 / 적용 불가 1.
- **8 프레임워크 output 렌더링 규약이 서로 다름** — 봉투 shape 표 자체가 계측기 생태계 지도.

### §5.2 O4 관측 8 프레임워크 요약 (Tier 1 표에서 확장)

| 프레임워크 | LLM span 존재 | usage propagate | O4 관측 |
|---|---|---|---|
| T1.1 LlamaIndex | 없음 (LLM 미실행) | 확인 불가 | 유보 |
| T1.2 OpenAI Agents (Runner) | Stub usage 반환 | ✗ | 부재 |
| T1.3 Anthropic | 있음 | ✓ | 성공 |
| T1.4 AutoGen | span 없음 | ✗ | 부재 |
| T2.1 Pydantic AI | 있음 | ✓ | 성공 (177 tok rollup) |
| T2.2 Google GenAI | 있음 | ✓ | 성공 (57 tok) |
| T2.3 Haystack | 있음 | ✓ | 성공 (28+57 tok) |
| **T2.4 Smolagents** | ★ **stub wrap 밖 (실 usage 는 Agent monitoring 자체 rollup)** | Agent monitoring 자체 집계 | **성공 (125 tok on AGENT root)** |

**관측 갱신**:
- LLM span 존재 + usage propagate 5 / 부재 2 / 특이 (agent 층 자체 집계) 1.
- **Smolagents 특이**: LLM span 없어도 Agent monitoring 이 root 에 rollup — 우리 어댑터 정상 인식.

---

## §6 — Tier 1 § 재검토 자산

### §6.1 Tier 1 §3.4 addendum 확인

Tier 1 결과 리포트 §3.4 하단에 이미 addendum 추가됨 (2026-08-02, PR merge d42c2a6 준거):
> "이 결함은 후속 사전등록으로 개정됨 → `docs/OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`."

Tier 2 결과는 이 개정 사전등록 기준으로 판정 (§1.1 표). 참조 체인 정합.

### §6.2 Part 2 재판정 실증 계열

Tier 1 §1.2 는 Part 1 skip 유효성의 첫 실 데이터 실증 (T1.2 OA-Runner + T1.4 AutoGen 의 non-tool candidate pair). Tier 2 는 다른 계열 실증:
- T2.1 Pydantic AI: **개정 R2 (tool 만 non-empty)** 가 실 데이터에서 처음 흡수 — tool-calling LLM `output.value` 부재를 개정 축이 정상 통과.
- T2.4 Smolagents: **End-to-end cascade 정상 waste 검출** (Tier 2 유일).

---

## §7 — ★ 우리 쪽 결함 명시 (Tier 2 추가)

### §7.1 유형 C (사일런트 실패) 는 우리 UX 결함

- 판정 실패인데 사용자에게 신호 없음.
- Tier 1 §3 은 사전등록 자체 결함 명시 (R2 스펙 비정합). Tier 2 §7 은 **런타임 신호 결함** 을 명시.
- 이번 판정에 반영하지 않음 (개정 축 §3 범위 밖).
- 별건 사전등록 후보 (§8).

### §7.2 O3 부재 저하 서술 정밀화 (T2.1 관련)

- T2.1 원 리포트가 "false positive 위험" 이라고 서술.
- 다른 인자 실측 (`framework_probe_pydantic_ai_diff_args.py`) 결과:
  - structural candidate pool 팽창 (실측 확인).
  - 하류 sha256 게이트가 대부분 걸러냄 (waste = 0).
- 정확 서술: **"structural pool 팽창 · 두 tool call output 이 우연히 같으면 통과"**.
- PARTIAL 판정 유지 · 저하 크기가 원 서술보다 작다는 것 실측 반영.
- 리포트 정정 완료 (framework_probe_pydantic_ai.md).

---

## §8 — 후속 별건 사전등록 후보

이 리포트가 지적한 것 중 별건으로 처리할 항목:

| # | 별건 | 근거 |
|---|---|---|
| B1 | **R5 개정** | 유형 B — 5 프레임워크 실측 근거. 개정 사전등록 §3.4 (α) synthetic root / (β) 사용자 wrap 규약 중 결정. |
| B2 | **유형 C 대응 (사일런트 실패 신호)** | Haystack single-run 이 waste 0 을 리턴하지만 원인은 tool 계측 없음. 어댑터가 "TOOL span 개수 0 + LLM span 있음" 조건 감지 시 caveat 반환. |
| B3 | **Part 3 (Format C R2 정합)** | 개정 사전등록 §8 · Part 2 §13 이월. `otel_json.py:239-254` (Format C `warn+skip`) 이 개정 R2 문면과 부분 일치 상태. |
| B4 | **Format A `_kind_of` fallback** | 개정 사전등록 §3.1 (g) 이월. 스펙 필수 속성 부재 시 chain 으로 삼키지 말고 경고/거부. |
| B5 | R2 개정 Format C 적용 | B3 과 관련 · 별건. |
| B6 | Google GenAI ADK 경로 재조사 (#3426) | 우리 probe 시나리오에서 미재현. `gen_ai.agent.*` attr 이 있는 ADK 경로에서 재현 가능성. 판정에는 영향 없음 (관측 별건). |
| B7 | Pydantic AI 어댑터 shim (`tool.parameters` → `input_text`) | O3 부재 대응. 별건 (다른 프레임워크 일관성 검토 필요). |
| B8 | MCP + host framework composition 축 | 개정 사전등록 §5.4 계열. host framework 축에 귀속하는 규약. |
| B9 | Smolagents user Model subclass LLM span 손실 대응 | Instrumentor exports 시점 wrap 이라 사용자 subclass 미wrap. 별건 (판정 영향 없음). |
| B10 | Tier 2 결과 리포트 개정 필요 시 addendum 규약 | Tier 1 결과 리포트 §3.4 addendum 선례 준용. |
| B11 | **Tier 3 — 미조사 프레임워크 13개** | 범위 · 조기종료 조건은 별건 사전등록에서 확정. |

**★ 이 리포트는 필요성만 명시**. 실제 별건 사전등록은 각각 승인 필요.

---

## §9 — 산출물

### §9.1 이번 리포트 커밋 (승인 후)

- **이 파일** (`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md`).
- **docs-only commit.**
- Rule 8 — 별건 branch (`results/framework-expansion-tier2` 등) · 승인 후 PR 개설.

### §9.2 미커밋 산출물 (로컬)

- `field_test/diagnostics/framework_probe_pydantic_ai.py` + `.md` + `_PREDICTION.md` + dump.
- `field_test/diagnostics/framework_probe_pydantic_ai_diff_args.py` + dump.
- `field_test/diagnostics/framework_probe_pydantic_ai_multirun.py` + dump.
- `field_test/diagnostics/framework_probe_pydantic_ai_observations_addendum.md`.
- `field_test/diagnostics/framework_probe_google_genai.py` + `.md` + `_PREDICTION.md` + dump.
- `field_test/diagnostics/framework_probe_google_genai_multirun.py` + dump.
- `field_test/diagnostics/framework_probe_haystack.py` + `.md` + `_PREDICTION.md` + dump.
- `field_test/diagnostics/framework_probe_haystack_multirun.py` + dump.
- `field_test/diagnostics/framework_probe_smolagents.py` + `.md` + `_PREDICTION.md` + dump.
- `field_test/diagnostics/framework_probe_smolagents_multirun.py` + dump.
- `field_test/diagnostics/framework_probe_mcp_EXCLUDED.md`.

---

## §10 — 확인 질의 (승인자 확정 답 기록)

| # | 질의 | 확정 답 |
|---|---|---|
| Q1 | §1.1 판정 표 (PASS 1 / PARTIAL 1 / FAIL 2 / out-of-scope 1) 확정 여부 | **동의** — 개정 축 그대로 · 완화 없음 |
| Q2 | §2 유형 A/B/C 분해 형식 확정 | **동의** — 3 유형 · 유형 A 는 계측기 공통 한계 · 유형 B 는 R5 개정 근거 · 유형 C 는 우리 UX 결함 |
| Q3 | §3 방법론 § 신설 · 예측 근거 우선순위 규칙 확정 | **동의** — 코드 구조 > upstream 이슈 목록 · Tier 3 에 적용 |
| Q4 | §4 공개 표현 6개 프레임워크 목록 확정 | **동의** — "LangChain, CrewAI, LlamaIndex, OpenAI Agents SDK, AutoGen, Smolagents" |
| Q5 | §8 후속 별건 우선순위 | **동의** — B1 (R5 개정) 최우선, B2 (사일런트) 차선, B3-B4 그 다음 |

---

## §11 — 참조

### 사전등록 · 결과 리포트
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (Tier 1 원 사전등록).
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` (Tier 1 결과, §3.4 addendum 포함).
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` (Part 1).
- `docs/ADAPTER_R2_RELAXATION_PART2_PREREG.md` (Part 2).
- **`docs/OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`** (개정 사전등록 · 이 리포트 판정 축).

### 코드
- `src/clew/ingest/langgraph.py` (Format A 어댑터).
- `src/clew/ingest/otel_json.py` (Format C 어댑터).
- `src/clew/model.py` (Span 검증기).
- `src/clew/detect/cascade.py`, `structural.py`, `semantic.py` (탐지).
- `src/clew/report/_enrich.py` (id_bridge).

### Upstream 이슈
- [#3392](https://github.com/Arize-ai/openinference/issues/3392) — Anthropic tool helpers 미계측 (유형 A · 재확인).
- [#3462](https://github.com/Arize-ai/openinference/issues/3462) — Pydantic AI TOOL input.value + LLM output.value 미채움 (T2.1 재현).
- [#3426](https://github.com/Arize-ai/openinference/issues/3426) — Google GenAI mapSpanKind 오라벨 (우리 시나리오 미재현, 관측 별건 B6).
- [#3337](https://github.com/Arize-ai/openinference/issues/3337) — OpenAI Agents parent AGENT/CHAIN output 미채움 (Tier 1 · Part 2 흡수 완료).

### 실측 dump 및 관측 파일
- 모든 dump 및 probe 스크립트는 `field_test/diagnostics/framework_expansion_dumps/` 및 `field_test/diagnostics/framework_probe_*.md` (로컬, 미커밋).

### Memory
- `memory/feedback_prereg_vs_local_design.md`.
- `memory/feedback_frozen_absolutes.md`.
- `memory/feedback_observed_not_confirmed.md`.

---

**★ 이 문서는 DRAFT. 승인자 확인 · 질의 Q1-Q6 답변 후 최종 문안 확정 · 커밋.**
