# OpenInference framework expansion — Results (2026-08-01, Tier 1)

**작성 시각 (UTC)**: 2026-08-01T00:00:00Z
**HEAD 해시**: `main @ 009be0c` (Merge PR #53 `prereg/framework-expansion` merged) 기준으로 컷.
**저자**: 클로드 (측정자) / 사용자 (승인자)
**선행 사전등록**: `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (`0b619c5`, PR #53 merge `009be0c` 2026-08-01).
**조사 실행일**: 2026-08-01 (사전등록 커밋 이후, 동일 세션).
**어댑터 코드 변경**: 없음 (§8 준수).
**§3 판정 기준**: 사전등록 §3 그대로. **결과 보고 완화·강화하지 않았다.**

---

## §0 — 이 리포트가 하는 것 · 하지 않는 것

**하는 것.**
- Tier 1 4 프레임워크 (LlamaIndex / OpenAI Agents SDK / Anthropic / AutoGen) probe 결과 기록.
- 사전등록 §3 기준으로 판정 (PASS / PARTIAL / FAIL).
- **FAIL 원인 3층 분해** — 우리 어댑터 정책 / instrumentor 상태 / SDK 자체.
- **★ 사전등록 자체의 결함 명시** — §2.1 R2 가 OpenInference 스펙과 비정합.
- §4.1 이름 나열 규약 준수 공개 표현 산출.
- Tier 2 진행 여부 판단 자료 제공.

**하지 않는 것.**
- 판정 기준 완화·강화 (§2/§3 그대로).
- 어댑터 코드 수정 (§8 — 결과 보고 별건 대상).
- upstream 이슈 관여 (링크 인용만).
- Tier 2 실행 (승인 대기).

---

## §1 — 판정 요약

### §1.1 사전등록 §3 기준 그대로

| # | 프레임워크 | 판정 (사전등록 시점) | Part 1 재판정 (2026-08-01) | Part 2 재판정 (2026-08-01) | 핵심 사유 |
|---|---|---|---|---|---|
| 기존 (fixture) | LangChain | PASS | PASS 유지 | PASS 유지 | 봉투 `{"type":"tool","data":{"content":…}}` — `_extract_tool_output` 인식. |
| 기존 (fixture) | CrewAI | PASS | PASS 유지 | PASS 유지 | 봉투 없음, text/plain raw. |
| T1.1 | LlamaIndex | **PASS** | PASS 유지 | PASS 유지 | R1-R5 일치. `raw_output_text` 안전망 실전 작동. O1 부재이나 저하 아님. |
| T1.2 | OpenAI Agents SDK | **FAIL** | FAIL 유지 (어댑터 층 gate) | **★ PASS** | Part 2 로 `langgraph.py:169` empty-check 제거 → non-TOOL AGENT/CHAIN 통과. R1-R5 재판정 모두 일치 (OA-primitive 5 spans · OA-Runner 7 spans, single trace_id, 1 root). |
| T1.3 | Anthropic (direct SDK) | **FAIL** | FAIL 유지 (R2 무관) | **FAIL 유지** | R5 위반 — 3 개 별도 trace_id. instrumentor 가 TOOL span 자체 미emit. R2 완화 무관 지점 (예상대로). |
| T1.4 | AutoGen | **FAIL** | FAIL 유지 (어댑터 층 gate) | **★ PASS** | Part 2 로 non-TOOL AGENT 5 개 통과. R1-R5 재판정 모두 일치 (9 spans, single trace_id, 1 root). ★ **cascade non-tool skip 이 실 데이터에서 처음 발동** (Part 1 §11.4 확증 축 해소, 2 개 candidate pair 가 empty side 로 skip). |

**Part 2 완화 후 최종**: **PASS 5 / FAIL 1.** (T1.3 만 FAIL 유지 · R5 원인, R2 무관.)

**★ 원 판정 (사전등록 시점) 은 덮어쓰지 않았다.** 컬럼 병기.
**★ Part 1 재판정 유지**. Part 2 재판정 결과만 새 컬럼 추가.
**★ 사전등록 §3 판정 기준 그대로 · 완화·강화 없음** (`ADAPTER_R2_RELAXATION_PART2_PREREG.md` §5, §11).

### §1.2 Part 1 §11.4 미확증 축 — 이번에 해소

Part 1 §11.4 는 실측으로 dev-7 / Toolathlon / CC 세 코퍼스에서 빈 non-tool span 카운트 0 임을 확증했으나, **"skip 로직이 실 데이터로 발동했다" 는 확증이 없었다** (합성 test 3 개만이 유효성 보장).

Part 2 재판정 실행 시:
- T1.2 OA-Runner: **1 개 non-tool candidate pair 가 empty side** → cascade non-tool skip 발동.
- T1.4 AutoGen: **2 개 non-tool candidate pair 가 empty side** → skip 발동.
- 즉 Part 2 재판정이 Part 1 skip 유효성의 **첫 실 데이터 실증**.

### §1.2 판정 규칙 자기 검증 (§3.2 재적용)

새 §3 기준 (§2.3 봉투 판정 제거 · 선택 축 부재 자체는 PASS 를 막지 않음) 은 사전등록 커밋 이전 확정. 이 규칙으로 기존 2 개 재판정 시 LangChain / CrewAI 모두 PASS 유지 (§2 사전등록 자기 검증). 새로 조사한 T1.1-T1.4 도 이 기준 그대로 적용, **완화·강화 없음**.

---

## §2 — ★ FAIL 원인 3층 분해

★ 이 표가 리포트의 핵심이다. 세 층을 구분해서 기록한다: (1) 우리 어댑터 정책, (2) instrumentor 상태, (3) SDK 자체.

### §2.1 원인 매트릭스

| FAIL | (1) 우리 어댑터 정책 | (2) instrumentor 상태 | (3) SDK 자체 |
|---|---|---|---|
| **T1.2 OpenAI Agents** | R2 (`output.value` non-empty) 가 OpenInference 스펙보다 엄격 | ★ **[Issue #3337](https://github.com/Arize-ai/openinference/issues/3337) — parent AGENT/CHAIN span 에 output.value 미채움. bug 라벨 · 2026-07-02 open, 2026-07-27 최종 업데이트, 우리 버전 1.6.2 도 미fix.** 독립 재현 존재 ([jimbobbennett/openai-agents-openinference-span-gaps](https://github.com/jimbobbennett/openai-agents-openinference-span-gaps)). | **문제 없음.** SDK 자체는 tracing primitive · Runner API 정상 제공. |
| **T1.4 AutoGen** | R2 (동일) | non-TOOL span (`on_messages_stream` AGENT) `output.value` 부재. 관련 이슈 조사 15 건 내에 **동일 매치 없음** (미확인 — 더 깊은 검색 시 나올 가능성). T1.2 와 원인 코드 경로 다름 · 증상 동일. | **문제 없음.** RoundRobinGroupChat 등 workflow API 정상. |
| **T1.3 Anthropic** | R5 (single trace_id) 가 이 프레임워크 사용 패턴을 수용 못 함 | ★ **[Issue #3392](https://github.com/Arize-ai/openinference/issues/3392) — Anthropic tool helpers 미계측. TOOL span 자체가 emit 되지 않음. enhancement 라벨 · open, 2026-07-14 업데이트.** "At the moment using this just gives you a set of traces each with one LLM span for each LLM call" — 우리 관측과 완전 일치. | **문제 없음.** SDK 자체는 Message API 정상, tool_use/tool_result 정확히 반환. |

### §2.2 ★ 정확한 표현

**틀린 표현 (사용 금지)**: "OpenAI Agents SDK 를 쓰면 Clew 못 쓴다" · "Anthropic 은 Clew 지원 안 함" · "AutoGen 은 호환 안 됨".

**맞는 표현**: 
- "**현재 이 instrumentor 로는 읽을 수 없다.**"
- "**instrumentor 가 이 프레임워크의 non-TOOL span 에 output 을 채우지 않아** 우리 어댑터가 R2 로 거부한다."
- "**Anthropic instrumentor 가 tool 실행을 계측하지 않아** waste 탐지 대상 span 이 생성되지 않는다."

**차이가 왜 중요한가**:
- FAIL 은 프레임워크 능력 부재 아니라 **계측 툴체인의 현재 상태** 에 대한 관측.
- upstream (Arize 측) 이 fix 하거나 우리 §2.1 R2 를 완화하면 재판정 가능한 케이스.
- 3 층 분해 없이 "FAIL = 이 SDK 지원 안 함" 이라 인용되면 잘못된 정보 전파.

---

## §3 — ★ 우리 쪽 결함 명시 (신설)

### §3.1 §2.1 R2 는 OpenInference 스펙과 정합하지 않는다

**우리 §2.1 R2 (사전등록)**: "`output.value` 존재 · 비어있지 않음 (strip 후 len ≥ 1)".

**OpenInference 스펙 (실측 확인)**:
- 유일한 필수 속성은 `openinference.span.kind` (스펙 원문: "required for all OpenInference spans"). 출처: [spec/semantic_conventions.md](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md).
- `output.value` 는 Reserved Attributes 표 등재 · MUST/SHOULD 언어 **없음** ("`output.value` | String | `"Hello, World!"` | The output value of an operation").
- span kind 별 mandatory 속성 표 자체 없음. LLM / CHAIN / AGENT / TOOL 어느 kind 에도 output.value 를 강제하는 스펙 문면 없음.
- Python semantic-conventions 모듈에서 `OUTPUT_VALUE`, `INPUT_VALUE` 상수는 **docstring 조차 없음**. 출처: [python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py](https://github.com/Arize-ai/openinference/blob/main/python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py).
- Arize Phoenix 자체가 수동 계측 시 `span.set_output(...)` 를 채우는 사례 문서화 — 즉 자동 계측이 채우지 않는 경우 존재를 문서 자체가 전제. 출처: [Phoenix — Using Tracing Helpers](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrument).

**결론**: **R2 는 스펙보다 엄격**. 우리 R2 근거를 `src/clew/model.py:38-43` 의 `Span.output_text` non-empty 검증기에서 가져왔고, 사전등록 작성 시 스펙 대조를 하지 않았다.

### §3.2 이번 조사에서 드러난 사전등록 자체의 결함

- §2.1 R2 는 "output.value 가 span 의 정보 가치 근거" 라는 우리 어댑터 내부 관행을 스펙 규범으로 잘못 승격.
- FAIL 3 건 중 **T1.2 · T1.4** 가 이 결함으로 인해 FAIL 로 분류됨. Instrumentor 가 스펙을 준수하는 emit 을 우리가 스펙보다 엄격하게 거부한 결과.
- T1.3 은 별개 (R5 · trace_id 분리) 이라 §3.2 결함과 무관.

### §3.3 이번 판정에 반영하지 않는 이유

**★ 사전등록 기준을 사후에 손대지 않는다.** §3.1 결함을 알아도 이번 판정은 사전등록 §3 그대로 유지 (T1.2 · T1.4 FAIL). 근거:

1. 사전등록의 목적은 결과 보기 전에 기준을 확정하는 것. 결과 보고 R2 완화하면 사전등록 자체가 무의미해짐.
2. R2 를 완화하려면 **빈 output_text 가 cascade sha256 · 임베딩 · 리포트에 미치는 영향이 미측정**. 완화가 안전한지 검증 필요.
3. 이 리포트의 역할은 결함을 **드러내는 것**. 수정은 별건 사전등록 대상.

### §3.4 R2 완화 별건 사전등록 후보 (제안, 이번 스코프 밖)

**제안 명칭**: `docs/ADAPTER_R2_RELAXATION_PREREG.md` (or similar).

**범위 (제안)**:
- Span 검증기 `_output_text_non_empty` 를 relaxed 로 조정 (예: root/wrapper span 에 대해 placeholder 허용, 또는 optional 로 변경).
- 완화 시 downstream 영향 실측:
  - cascade sha256: 빈 문자열 두 개는 동일 sha 로 매치 → false positive 위험.
  - 임베딩: 빈 문자열 임베딩 결과 확인.
  - 리포트 렌더: 빈 span 이 스니펫에 어떻게 표시되는지.
- 완화 후 T1.2 · T1.4 재판정 (upstream 무변경 시).

★ 이번 리포트는 이 별건의 **필요성만 명시**. 실제 수정은 별도 승인 필요.

---

## §4 — Upstream 상태 기록

### §4.1 T1.2 OpenAI Agents — [#3337 open bug](https://github.com/Arize-ai/openinference/issues/3337)

- **상태**: open, bug + instrumentation 라벨.
- **최초 개설**: 2026-07-02. **최종 업데이트**: 2026-07-27.
- **우리 버전 (1.6.2, 2026-07-30 release)**: 미fix. PR [#3391](https://github.com/Arize-ai/openinference/pull/3391) (1.6.2 changes) 는 다른 이슈 (LLM span message.content 평면화) 대상.
- **독립 재현**: [jimbobbennett/openai-agents-openinference-span-gaps](https://github.com/jimbobbennett/openai-agents-openinference-span-gaps) — 최소 repro (~40 lines).
- **원인 소스 분석** (issue 댓글에서 인용): `_processor.py` 의 `on_trace_start` 이 root 에 span-kind 만 세팅. `AgentSpanData` 분기 는 `graph.node.*` 만, `CustomSpanData`/fallback (CHAIN) 은 input/output 세팅 브랜치 자체 없음.
- **upstream fix 시**: 우리 어댑터 무변경으로 재판정 가능. **모니터 대상**.

### §4.2 T1.3 Anthropic — [#3392 enhancement](https://github.com/Arize-ai/openinference/issues/3392)

- **상태**: open, enhancement 라벨.
- **최종 업데이트**: 2026-07-14.
- **성격**: fix 아니라 **신규 기능 요청**. Anthropic beta tool helpers SDK 를 계측 대상에 포함.
- 이슈 body: "At the moment using this just gives you a set of traces each with **one LLM span for each LLM call made to handle the tool call**" — 우리 T1.3 관측 완전 일치.
- **시간 프레임**: fix bug 와 다름. enhancement 는 일반적으로 우선순위 낮음. 대기 시간 예측 불가.
- 관련 open bug: [#3342](https://github.com/Arize-ai/openinference/issues/3342) (Anthropic tool definition metadata 미채움) — 우리 이슈와 다름 (tool 정의 스키마 표시).

### §4.3 T1.4 AutoGen — 관련 이슈 미등록

- 조사한 15 건 (repo:Arize-ai/openinference + autogen 키워드) 안에 우리 관측 (AGENT `on_messages_stream` output 부재) **정확 매치 없음**.
- **미확인**: 더 깊은 검색 · 라벨 필터 · Slack thread 확인 시 나올 가능성.
- 관련 있는 open bug: [#2258](https://github.com/Arize-ai/openinference/issues/2258) — streaming LLM client 에서 token count / cost 못 얻는 문제. T1.4 O4 부재와 부분 관련.
- **upstream fix 예측 불가.** 이슈 미등록 상태.

---

## §5 — 관찰 자산 (§4.1 규약 준수)

### §5.1 봉투 shape 5 종 비교

★ 이 표가 이번 조사의 **누적 자산 primary** — 도구별 응답 구조 매핑은 프로젝트 해자.

| 프레임워크 | TOOL span emit | mime | 봉투 shape | `_extract_tool_output` 인식 |
|---|---|---|---|---|
| LangChain | ✓ | application/json | `{"type":"tool","data":{"content":"<orig>"}}` | ✓ (unwrap `data.content`) |
| CrewAI | ✓ | text/plain | 없음 (raw string) | ✓ (raw 반환) |
| **LlamaIndex** (T1.1) | ✓ | application/json | `{"blocks":[{"text":"<rendered>"}], "tool_name":..., "raw_input":..., "raw_output":<orig>, "is_error":...}` | ✗ (미인식 · raw 반환, preprocess 가 leaf 추출) |
| **OpenAI Agents** (T1.2) | ✓ | application/json (dict) / None (str) | **없음 — 반환값 직행 (유효 JSON)** | ✓ (raw 반환, 봉투 자체 없음) |
| Anthropic (direct SDK) (T1.3) | ✗ (tool span 자체 없음) | — | **적용 불가** | — |
| **AutoGen** (T1.4) | ✓ | text/plain | **없음 — Python `str(dict)` 렌더링 (invalid JSON)** | ✓ (text/plain 분기, raw 반환) |

**패턴 관찰**:
- 봉투 종류 다양: 있음 (LangChain, LlamaIndex) / 없음 · 유효 JSON (OpenAI Agents) / 없음 · Python repr (AutoGen) / text/plain raw (CrewAI) / 적용 불가 (Anthropic).
- LlamaIndex 는 봉투 안에 `raw_output` 필드로 유효 JSON 을 보존 → `raw_output_text` 안전망 유효.
- AutoGen 은 `str(dict)` 렌더링으로 **유효 JSON 아님** → 안전망 원리적 커버 못 함.

### §5.2 entity_id path — 프레임워크 의존 (이번 조사의 미예상 발견)

`create_ticket` 이 `{"ticket": {"id": "..."}}` 반환 시 `clew.yaml entity_id` 등록에 필요한 path:

| 프레임워크 | path | 근거 |
|---|---|---|
| LangChain | `ticket.id` | 봉투 없음 (`@tool` dict 직행) |
| CrewAI | `ticket.id` | 봉투 없음, 원본 dict 유효 JSON. [S] probe 실측 (`crewai 1.15.9`, `field_test/diagnostics/framework_probe_crewai_dict.py` — 이 리포트 작성 시점에는 "미확인" 이었으나 README 표 작성을 위해 사후 실측 후 채움) |
| LlamaIndex | **`raw_output.ticket.id`** | 봉투 prefix 필요 |
| OpenAI Agents | `ticket.id` | 봉투 없음, 유효 JSON |
| Anthropic (direct SDK) | **불가** | TOOL span 자체 없음 (§2.1 (3)) |
| AutoGen | **불가** | Python `str(dict)` 이라 `json.loads` 실패 |

**★ 사전등록 §2 가 예상 못 한 축**: entity_id path 가 프레임워크마다 다르다. "어댑터 하나로 여러 프레임워크" 전제 하에서 사용자가 `clew.yaml` 에 쓸 값이 프레임워크 의존. 이건 사전등록 §2 필수/선택 축에 없는 정보이며 **문서화 대상 (별건)**.

### §5.3 graph.node.id — §2.2 O1 예측 완전 어긋남

**§2.2 원 예측** (`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` § 2.2 O1): "LangGraph 특유 축이라 대부분 프레임워크에서 없음 예상".

**실측 결과**:

| 프레임워크 | 존재 여부 |
|---|---|
| LlamaIndex (T1.1) | 부재 |
| OpenAI Agents primitive (T1.2 첫 dump) | 부재 |
| OpenAI Agents Runner (T1.2 재-dump) | **존재** (`probe_agent` AGENT) |
| Anthropic (T1.3) | 해당 없음 (AGENT span 자체 부재) |
| AutoGen (T1.4) | **존재** (모든 AGENT span 에 populate) |

**정정**: "LangGraph 특유" 서술은 정확하지 않음. **Runner 기반 OpenAI Agents · AutoGen 도 사용**. Tier 2 · 추후 프레임워크에서 재확인 필요. §2.2 원 문면은 **이번 리포트로 실측 정정**.

### §5.4 O4 (token/model/cost) — instrumentor 의존으로 재정의

**사전등록 §2.2 원 문면**: "amplification 추정만 못 함 (approx flag)" — LLM span 유무만 언급.

**실측 결과**:

| 프레임워크 | LLM span 존재 | instrumentor propagate | O4 관측 |
|---|---|---|---|
| T1.1 LlamaIndex | 없음 (Workflow probe 특성) | 확인 불가 | 유보 |
| T1.2 OpenAI Agents (Runner) | Stub Model 이 usage 반환 | ✗ (instrumentor 가 안 옮김) | **부재** |
| T1.3 Anthropic | 있음 (3 개 LLM span) | ✓ | **★ 완전 관측 성공** |
| T1.4 AutoGen | span 자체 미emit | 확인 불가 | 부재 |

**★ 재정의 근거**:
- 원 §2.2 O4 설명은 "LLM span 있어야 관측 가능" 만 언급.
- 실측: T1.2 는 stub 이 usage 를 반환했음에도 **instrumentor 가 propagate 하지 않아** 부재. T1.3 만 완전 propagate.
- 즉 **O4 관측 여부의 진짜 원인**은 "LLM 실행 유무" 가 아니라 **"instrumentor 가 usage 를 span attribute 로 옮기는가"**.
- **재정의 (제안)**: "O4 는 프레임워크 특성이 아니라 instrumentor 특성이다. LLM span 존재 여부와 별개로 각 instrumentor 의 propagate 정책에 따라 관측 가능성이 결정된다."

Tier 2 · 추후 조사에서 이 재정의로 관측 축을 명시적으로 갱신할 필요. 이번 리포트에서는 결과만 기록.

---

## §6 — 공개 표현 (§4.1 이름 나열 규약 준수)

### §6.1 허용 표현 (템플릿 그대로)

> **"OpenInference 계측 3 개 프레임워크에서 실측 확인 — LangChain, CrewAI, LlamaIndex."**

### §6.2 금지 표현 (§4.1 명시)

- "여러 프레임워크"
- "다양한 프레임워크"
- "OpenInference 지원" (이름 병기 없이)
- "20 개 이상"
- 이름 없는 개수만의 언급

### §6.3 FAIL 표기 (§4.3 준수)

지원 목록에 **명시적으로 미지원** 으로 기록:

> **"OpenAI Agents SDK · Anthropic (direct SDK) · AutoGen — 현재 이 instrumentor 로는 읽지 못한다. instrumentor 상태는 §4 upstream 상태 참조."**

★ "SDK 를 쓰면 못 쓴다" 문면 금지. "instrumentor 로는" 문면 필수.

### §6.4 README 반영 (별건, 이번 리포트에서 텍스트만 확정)

- README 지원 프레임워크 목록 갱신은 **별건 사전등록 · 별건 PR**.
- 이번 리포트에서는 §6.1 템플릿 문면만 확정.
- 사용자 승인 후 별건으로 README 반영.

---

## §7 — Pingpong 관측 (§7.1 스코프 준수)

### §7.1 T1.4 AutoGen 에서 A→B→A 구조 emit 확인

**span tree**:

```
run_stream (CHAIN root)
  ├─ TicketAgent.on_messages_stream (AGENT)
  ├─ ReviewAgent.on_messages_stream (AGENT)
  ├─ TicketAgent.on_messages_stream (AGENT)  ← A→B→A 왕복 완성
  ├─ ReviewAgent.on_messages_stream (AGENT)
  └─ TicketAgent.on_messages_stream (AGENT)
```

**★ 증거 판정** (`memory/project_pingpong_blocked` 위상 정정 준수):
- 이 dump 는 **우리가 만든 예제** (RoundRobinGroupChat 로 강제 왕복 시나리오).
- 외부 저작 코퍼스 아님 → **증거 아님**.
- **"구조적으로 발생 가능"** 까지만 사실 기록.

### §7.2 병기 필수 사실

- **T1.4 AutoGen 은 FAIL 판정.** 우리 어댑터가 현재 이 dump 를 R2 로 거부 → **읽지도 못한다.**
- 즉 이 관측은 "AutoGen 이 pingpong 구조를 emit 할 수 있다" 는 사실이지 "우리가 그걸로 pingpong 을 잡을 수 있다" 가 아님.
- 탐지기 재정의는 별건 (`memory/project_pingpong_blocked` §7.3).

### §7.3 LLM span 존재 여부

- T1.4 AutoGen dump 에 **LLM span 자체 부재** (`AutogenAgentChatInstrumentor` 가 model_client.create 미wrap).
- §2.4 pingpong 축 발동 조건 ("LLM span 이 agent 서브트리 안") **성립 안 함**.
- 즉 데이터가 있어도 우리 원 pingpong 정의로는 관측 불가 구조.

---

## §8 — Tier 2 진행 여부 판단 자료

### §8.1 §5.3 (사전등록) 원칙

> "Tier 1 T1.1 → T1.2 → T1.3 → T1.4 순차. Tier 1 완료 후 결과를 보고 승인자가 Tier 2 진행 여부를 결정한다.
> **★ 이건 조사 예산 규칙이지 판정 기준이 아니다.** §4.1 표현 규약과 무관하며, **PASS 개수로 조사를 조기 종료하지 않는다.**"

### §8.2 Tier 2 대상 (제안 우선순위, 사전등록 §5.2 그대로)

| # | 프레임워크 | 근거 · 이번 조사 관점 |
|---|---|---|
| T2.1 | Pydantic AI | 신규 인기. 아직 데이터 없음. |
| T2.2 | Google GenAI | 커버리지 확장. |
| T2.3 | Haystack | 검색 / RAG. |
| T2.4 | Smolagents (HuggingFace) | 최소 agent. |
| T2.5 | MCP | instrumentation 가능 여부 자체 미확인. 마지막 순서. |

### §8.3 Tier 2 결정 지침 (사용자 판단 근거)

**Tier 2 진행 이득 (제안)**:
- 봉투 shape 매핑 자산 확장.
- entity_id path 프레임워크 의존 패턴 확대 검증.
- O4 instrumentor 의존 재정의를 더 많은 데이터로 확증.

**Tier 2 진행 부담 (제안)**:
- 각 프레임워크마다 stub/mock 로 LLM 비용 0 유지하는 probe 설계 필요 (T1.2 처럼 복잡할 수 있음).
- 관찰 자료가 늘어나면서 §4.1 이름 나열 규약대로 PASS 확인된 이름만 추가되므로 표현 자체는 확대되지 않음 (조사 자산 확장 목적).

**결정 대기.** 승인자 판단.

---

## §9 — 산출물

### §9.1 이번 리포트 커밋 (본 파일)

- 위치: `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md`.
- 사전등록 §11.3 대로 별건 사전등록 · docs/ 커밋.
- **PR 필요.** Rule 8 (merge commit, no squash/rebase).

### §9.2 조사 실행 부산물 (로컬 · 미커밋)

- Probe 스크립트 4 개:
  - `field_test/diagnostics/framework_probe_llamaindex.py`
  - `field_test/diagnostics/framework_probe_openai_agents.py`
  - `field_test/diagnostics/framework_probe_openai_agents_runner.py`
  - `field_test/diagnostics/framework_probe_anthropic.py`
  - `field_test/diagnostics/framework_probe_autogen.py`
- Dump 파일 5 개:
  - `field_test/diagnostics/framework_expansion_dumps/llamaindex.json`
  - `field_test/diagnostics/framework_expansion_dumps/openai_agents.json`
  - `field_test/diagnostics/framework_expansion_dumps/openai_agents_runner.json`
  - `field_test/diagnostics/framework_expansion_dumps/anthropic.json`
  - `field_test/diagnostics/framework_expansion_dumps/autogen.json`
- Deliverable md 4 개:
  - `field_test/diagnostics/framework_probe_llamaindex.md`
  - `field_test/diagnostics/framework_probe_openai_agents.md`
  - `field_test/diagnostics/framework_probe_anthropic.md`
  - `field_test/diagnostics/framework_probe_autogen.md`

### §9.3 후속 사전등록 후보 (이번 리포트 이후 검토 대상, 별건)

1. **R2 완화 사전등록** (§3.4) — OpenInference 스펙 정합.
2. **entity_id path 프레임워크 의존 문서화** (§5.2) — README / clew.yaml 예시.
3. **O4 관측 축 재정의** (§5.4) — 사전등록 §2.2 문면 정정.
4. **README 지원 프레임워크 목록 갱신** (§6.4) — §6.1 템플릿 반영.
5. Tier 2 진행 시 별건 결과 리포트 (`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS_TIER2.md` 또는 동일 파일 확장).

---

## §10 — 참조

### 사전등록
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (`0b619c5`, PR #53 merge `009be0c`).

### 코드
- `src/clew/model.py:38-43` — R2 근거 (`_output_text_non_empty` 검증기).
- `src/clew/ingest/langgraph.py:91-125` — `_extract_tool_output` (봉투 shim).
- `src/clew/ingest/langgraph.py:225` — `preprocess_trace` 유일 호출 지점 (`raw_output_text` 안전망 populate).
- `src/clew/report/_enrich.py::scan_id_bridge_candidates` — id_bridge fallback (`raw_output_text or output_text`).

### Probe 파일 (§9.2)
로컬 · 미커밋. 재현 시 참조.

### Upstream 이슈
- OpenAI Agents: [Issue #3337](https://github.com/Arize-ai/openinference/issues/3337) (open bug).
- Anthropic: [Issue #3392](https://github.com/Arize-ai/openinference/issues/3392) (open enhancement).
- Anthropic 부수: [Issue #3342](https://github.com/Arize-ai/openinference/issues/3342) (open bug).
- AutoGen 관련: [Issue #2258](https://github.com/Arize-ai/openinference/issues/2258) (open, streaming O4 이슈).

### OpenInference 스펙 (R2 스펙 비정합 확인 근거)
- [spec/semantic_conventions.md](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md).
- [python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py](https://github.com/Arize-ai/openinference/blob/main/python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py).
- [Phoenix — Using Tracing Helpers](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrument).
- [OpenTelemetry — Context propagation](https://opentelemetry.io/docs/concepts/context-propagation/).

### Memory
- `memory/project_pingpong_blocked.md` — BLOCKED / KILL 위상 정정 (§7.1 준수).
- `memory/feedback_dump_before_shim.md` — probe 방법론 근거.
- `memory/feedback_prereg_vs_local_design.md` — docs/ 커밋 판단 기준.

### 사전등록 §11.3 원 산출물 형식 표 (준수 확인)

사전등록 §11.3 이 요구한 표 형식:

| 프레임워크 | R1-R5 | O1-O5 | 봉투 sha 일치 | 안전망 작동 | 3분류 | 관찰 노트 |

이번 리포트에서 이 형식은 각 probe deliverable md (§9.2) 에 개별로 채워져 있으며, 종합은 §1.1 · §5.1 · §5.2 · §5.3 · §5.4 에 분산 기록. 향후 리팩토링 시 종합 표로 통합 가능.
