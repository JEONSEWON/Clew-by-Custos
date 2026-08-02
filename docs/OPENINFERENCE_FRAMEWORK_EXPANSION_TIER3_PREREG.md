# OpenInference framework expansion — Tier 3 Pre-registration (2026-08-02, DRAFT)

**작성 시각 (UTC)**: 2026-08-02T00:00:00Z
**HEAD 기준**: `main @ c6fb007` — Tier 2 결과 리포트 (PR #64) merge 이후 컷.
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**상태**: **DRAFT — 커밋 전 확인. 조사 실행 금지.**

**선행**:
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (Tier 1 원 사전등록).
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` (Tier 1 결과 리포트).
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` · `docs/ADAPTER_R2_RELAXATION_PART2_PREREG.md` (Part 1/2).
- **`docs/OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`** (개정 판정 축 — **★ 이 사전등록의 판정 기준**).
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md` (Tier 2 결과 · §2 유형 A/B/C · §3 방법론).

---

## §0 — 이 사전등록이 하는 것 · 하지 않는 것

**하는 것.**
- **미조사 Python instrumentation 26 개 전수 조사** 범위 확정.
- 개정 사전등록 판정 축 (R1 필수 · R2 tool 만 · R3 PARTIAL 편입 · R5 확인·기록만) **그대로** 적용.
- 조사 순서 (1차 에이전트 → 2차 LLM 클라이언트 → 3차 특수) 확정 · 근거.
- 세팅 규약 확정 (Tier 2 교훈: instrumentor `_instrument()` 소스 실측 우선).
- 유형 처리 규약 확정 (기존 A/B/C · 새 유형 = D 신설 · **유형은 관찰 축 · 판정 축 아님**).
- 비용 관리 · 중단 조건 확정 (결과 보기 전).
- **VertexAI vs Google GenAI 관계 · JS/TS scope 배제 근거** 명시.

**하지 않는 것.**
- 조사 실행 (승인 후 별건).
- 판정 축 완화·강화 (개정 사전등록 그대로).
- 코드 변경 일체.
- 유형 신설이 판정에 영향 미침 (§4.3 순환 방지 규칙).
- 결과 리포트 사후 수정 (Tier 1/2 §7 원칙 준수).
- 릴리스 (범위 밖).

---

## §1 — 범위 확정 (웹 실측 근거)

### §1.1 OpenInference Python instrumentation 전수 인벤토리

**출처**:
- Arize 모노레포: https://github.com/Arize-ai/openinference/tree/main/python/instrumentation (33 개 dir).
- PyPI simple index: `openinference-instrumentation-*` prefix (2026-08-02 기준).

**총 37 개 package** (모노레포 33 + PyPI-only 4 `agentminds`/`baml`/`codex`/`monkai-agent` − 모노레포-only 1 `promptflow` = PyPI 배포 36 + 모노레포-only 1).

### §1.2 이미 조사 완료 11 개 (Tier 1 + Tier 2)

- **Tier 1 (6)**: `langchain`, `crewai`, `llama-index`, `openai-agents`, `anthropic`, `autogen-agentchat`.
- **Tier 2 (5)**: `pydantic-ai`, `google-genai`, `haystack`, `smolagents`, `mcp`.

**★ 주의: 이름 유사한 별도 package 는 미조사**:
- `openinference-instrumentation-autogen` (v0.2 legacy stack) ≠ `openinference-instrumentation-autogen-agentchat` (v0.4+). ★ **legacy 는 미조사 · Tier 3 대상**.
- `openinference-instrumentation-openai` (base OpenAI SDK 클라이언트) ≠ `openinference-instrumentation-openai-agents` (Agents SDK). ★ **base 는 미조사 · Tier 3 대상**.

### §1.3 VertexAI vs Google GenAI — **disjoint (별도 대상)**

**실측 (`pyproject.toml` 직접 확인)**:
- `openinference-instrumentation-vertexai` → `google-cloud-aiplatform ≥ 1.63.0` (`vertexai`, `vertexai.generative_models` 네임스페이스). 출처: https://raw.githubusercontent.com/Arize-ai/openinference/main/python/instrumentation/openinference-instrumentation-vertexai/pyproject.toml
- `openinference-instrumentation-google-genai` → `google-genai ≥ 2.0.0` (`google.genai` 통합 SDK). 출처: https://raw.githubusercontent.com/Arize-ai/openinference/main/python/instrumentation/openinference-instrumentation-google-genai/pyproject.toml

**★ 코드 경로 수준에서 disjoint**: 대상 SDK 자체가 서로 다른 Python 패키지 (`google-cloud-aiplatform` vs `google-genai`). Gemini `generate_content` intent 는 겹치지만 wrap 대상 클래스가 다름. → **vertexai 는 별도 Tier 3 대상**.

### §1.4 JS/TS scope — **배제**

**실측 근거**:
- `@arizeai/openinference-instrumentation-*` npm 패키지 11 개 존재. 출처: https://registry.npmjs.org/-/v1/search?text=%40arizeai · 모노레포: https://github.com/Arize-ai/openinference/tree/main/js/packages
- **우리 어댑터는 Python 전용**:
  - `src/clew/ingest/langgraph.py:1` docstring: `"""OTel/OpenInference span adapter - ReadableSpan list -> canonical Trace.`
  - line 29-30: `if TYPE_CHECKING: from opentelemetry.sdk.trace import ReadableSpan`
  - line 139: `def otel_spans_to_trace(spans: Sequence["ReadableSpan"], ...)`.
- 어댑터가 in-process Python `ReadableSpan` 객체를 소비. JS OTel SDK 는 다른 객체 타입 · OTLP JSON 직렬화 형태도 다름 · 우리는 JS ingest 경로가 없음.

**★ 배제 근거 명시**: JS 대상 조사 시 어댑터에 새 ingest 경로 필요 (별건 · Tier 3 밖). **Tier 3 = Python only.**

### §1.5 Tier 3 대상 확정 — **26 개 전수**

| # | Package | Latest | 카테고리 (§2 순서) |
|---|---|---|---|
| 01 | openinference-instrumentation-agent-framework | 0.1.6 | 1차 에이전트 |
| 02 | openinference-instrumentation-agentminds | 0.1.0 | 1차 에이전트 (PyPI-only) |
| 03 | openinference-instrumentation-agentspec | 0.1.4 | 1차 에이전트 |
| 04 | openinference-instrumentation-agno | 1.0.1 | 1차 에이전트 |
| 05 | openinference-instrumentation-autogen | 0.1.14 | 1차 에이전트 (legacy v0.2) |
| 06 | openinference-instrumentation-beeai | 0.1.20 | 1차 에이전트 |
| 07 | openinference-instrumentation-claude-agent-sdk | 0.1.8 | 1차 에이전트 |
| 08 | openinference-instrumentation-dspy | 0.1.38 | 1차 에이전트 |
| 09 | openinference-instrumentation-google-adk | 0.1.18 | 1차 에이전트 |
| 10 | openinference-instrumentation-monkai-agent | 0.0.1 | 1차 에이전트 (stale, 2025-05) |
| 11 | openinference-instrumentation-strands-agents | 0.1.4 | 1차 에이전트 |
| 12 | openinference-instrumentation-codex | 0.5.2 | 1차 에이전트 (★ 이름 충돌 flag — OpenAI Codex vs. 다른 codex? 조사 시 확인) |
| 13 | openinference-instrumentation-openai | 0.1.53 | 2차 LLM 클라이언트 |
| 14 | openinference-instrumentation-bedrock | 0.1.44 | 2차 LLM 클라이언트 |
| 15 | openinference-instrumentation-groq | 0.1.17 | 2차 LLM 클라이언트 |
| 16 | openinference-instrumentation-mistralai | 2.0.5 | 2차 LLM 클라이언트 |
| 17 | openinference-instrumentation-vertexai | 0.1.17 | 2차 LLM 클라이언트 (§1.3 근거) |
| 18 | openinference-instrumentation-guardrails | 0.1.15 | 3차 특수 |
| 19 | openinference-instrumentation-instructor | 0.1.19 | 3차 특수 (structured output helper) |
| 20 | openinference-instrumentation-baml | 0.2.0 | 3차 특수 (compiled prompts) |
| 21 | openinference-instrumentation-litellm | 0.1.35 | 3차 특수 (multi-provider proxy) |
| 22 | openinference-instrumentation-openlit | 0.1.8 | 3차 특수 (semconv bridge) |
| 23 | openinference-instrumentation-openllmetry | 0.1.12 | 3차 특수 (semconv bridge) |
| 24 | openinference-instrumentation-pipecat | 2.0.1 | 3차 특수 (voice agent) |
| 25 | openinference-instrumentation-portkey | 0.1.11 | 3차 특수 (LLM gateway) |
| 26 | openinference-instrumentation-promptflow | (PyPI 미배포) | 3차 특수 (★ PyPI 미배포, 소스 설치 필요) |

**★ 26 개 전수. 조기 종료 없음 (범위 밖 사유는 §5 중단 조건 참조).**

---

## §2 — 조사 순서 (정보 밀도 기준)

**★ 순서 근거**:
- **1차 (에이전트, 12 개)**: 우리 대상 (agentic waste) 에 가깝고 **새 유형 가능성 높음**. Tier 2 에서 나온 유형 A/B/C 는 에이전트 프레임워크에서 발견됨.
- **2차 (LLM 클라이언트, 5 개)**: **유형 A 예상** (Anthropic direct SDK 형: 계측이 client 호출 1개 span 만 emit). 정보 밀도 낮음.
- **3차 (특수, 9 개)**: 각각 특수 목적 (voice / gateway / structured output / semconv bridge). 우리 대상과 유사도 낮음.
- **★ 에이전트 조사에서 새 유형 (D) 이 나오면 2차·3차 조사 방식이 달라질 수 있음** — 1차 → 2차 사이에 유형 재검토 지점 있음.

### §2.1 1차 — 에이전트 계열 (12 개, T3.1-T3.12)

**순서 (재조사 위험 순, 오래된 것부터 최신 순)**:

1. T3.1 `dspy` — Stanford framework, 성숙도 높음.
2. T3.2 `agno` — 최근 활발 (v1.0.1).
3. T3.3 `beeai` — IBM.
4. T3.4 `google-adk` — Google Agent Development Kit.
5. T3.5 `claude-agent-sdk` — Anthropic 공식 agent SDK.
6. T3.6 `agent-framework` — Microsoft.
7. T3.7 `strands-agents` — AWS.
8. T3.8 `autogen` (v0.2 legacy) — Microsoft legacy stack.
9. T3.9 `agentspec` — 조사 필요 (제작자·목적 확인).
10. T3.10 `agentminds` — PyPI-only, 조사 필요.
11. T3.11 `monkai-agent` — 2025-05 마지막 릴리스 (stale), 최우선순위 낮음.
12. T3.12 `codex` — ★ **이름 충돌 확인 필요** (OpenAI Codex vs. 별도 codex?).

### §2.2 2차 — LLM 클라이언트 계열 (5 개, T3.13-T3.17)

**Tier 1 Anthropic (#3392) · Tier 2 Google GenAI 선례로 유형 A 예상**. 다만 각 프레임워크가 tool_calls 를 어떻게 emit 하는지는 실측 필요.

13. T3.13 `openai` — base OpenAI SDK 클라이언트.
14. T3.14 `bedrock` — AWS Bedrock.
15. T3.15 `mistralai` — Mistral.
16. T3.16 `groq` — Groq.
17. T3.17 `vertexai` — Google Vertex AI legacy SDK (§1.3).

### §2.3 3차 — 특수 계열 (9 개, T3.18-T3.26)

**우리 대상과 유사도 낮음. 최소 실측 · 유형 관측만**.

18. T3.18 `guardrails` — 출력 검증.
19. T3.19 `instructor` — structured output helper.
20. T3.20 `baml` — compiled prompt language.
21. T3.21 `litellm` — multi-provider proxy.
22. T3.22 `portkey` — LLM gateway.
23. T3.23 `openlit` — semconv bridge (meta-instrumentor).
24. T3.24 `openllmetry` — semconv bridge (meta-instrumentor).
25. T3.25 `pipecat` — voice agent.
26. T3.26 `promptflow` — Azure ML prompt orchestration (PyPI 미배포).

**★ 유형 A 예상**: `litellm` / `portkey` / `openlit` / `openllmetry` — 이들은 다른 프레임워크를 감싸므로 자체적으로 TOOL span 을 emit 안 할 가능성 높음.

---

## §3 — 세팅 규약 (Tier 2 교훈)

### §3.1 규칙: instrumentor 소스 우선 (§3.2 Tier 2 §3.2 그대로)

**Tier 2 §3.2 규칙 채택**: "**예측 근거 우선순위 = instrumentor `_instrument()` 코드 실측 > dump 원문 관찰 > upstream 이슈 목록.**"

**Tier 3 적용 절차** (프레임워크당):
1. **`_instrument()` 소스 읽기** — 무엇을 wrap 하는지 명시적으로 확인.
2. **wrap 대상 명시** — Agent / Model / Tool / Pipeline / etc. 중 무엇을 hook 하는지.
3. **세팅 결정** — stub 이 wrap 을 탈지 판단.
4. **PREDICTION.md 작성** — 세팅 근거 + R1-R5 예측 + 유형 예상.
5. **probe 실행 · dump 관찰 · ingest · 판정**.

### §3.2 근거

**T2.3 Haystack (반례)**: upstream 이슈 목록 기반 예측 → 뒤집힘. stub `ChatGenerator` 를 만들었으나 instrumentor 가 Pipeline 컴포넌트만 wrap 해서 무효.

**T2.4 Smolagents (성공례)**: `_instrument()` 소스 실측 → `Tool.__call__` 직접 wrap 확인 → **TOOL span emit 예상 · 적중**.

### §3.3 세팅 방침 원칙

- **네트워크 0** (실 API 호출 유발 금지).
- Upstream VCR 카세트: 있으면 참고. **새 카세트 record 금지**.
- Stub 방식: `_instrument()` 소스에서 wrap 대상이 stub 을 탈지 사전 확인.
- 대체 방식: 실제 SDK 클라이언트 (예: `OpenAIChatGenerator`) + SDK 내부 client 를 monkey-patch (T2.3 Haystack 선례).

---

## §4 — 판정 축 · 유형 처리 규약

### §4.1 판정 축 — 개정 사전등록 그대로

**개정 판정 축**: `docs/OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md` §2/§3.
- R1 필수 (`openinference.span.kind` 값 ∈ {LLM, TOOL, CHAIN, AGENT, RUNNABLE}).
- R2 개정 (tool span 만 non-empty).
- R3 PARTIAL 편입 (tool 식별 실패 시 기능 저하).
- R4 timestamp.
- R5 single trace_id · single root (확인·기록만).

**★ 완화·강화 금지.** Tier 3 결과 보고 판정 축을 손대지 않는다.

### §4.2 유형 처리 규약 (Tier 3 신설)

**현재 유형 (Tier 2)**: A (TOOL span 미emit) · B (R5 multi-trace) · C (사일런트 실패).

**Tier 3 처리**:
1. **기존 유형에 들어가면** — 그 유형으로 기록.
2. **새 유형이 나오면** — **유형 D 신설** · Tier 3 결과 리포트에 정의 · 관찰 근거 명시.
3. 새 유형이 여러 프레임워크에서 반복 관측될 때만 유형으로 승격 · **1 프레임워크 특이 관측은 K1-K5 로 기록** (Tier 2 관례 준용).

### §4.3 ★ 유형은 관찰 축 · 판정 축 아님 (Tier 1 선례 준수)

**★ 규칙**: **판정은 R1-R5 로만 한다. 유형 신설이 판정을 바꾸지 않는다.**

**근거**: Tier 1 원 사전등록에서 §2.3 봉투 shape 을 판정 축에 넣었다가 **순환 (봉투 판정 → 결과 → 판정 축 수정)** 이 발생했다. 개정 사전등록 §2 는 봉투를 판정 축에서 뺐다.

**Tier 3 적용**:
- **유형 D 를 신설하더라도** R1-R5 판정은 개정 사전등록 그대로.
- 유형은 "왜 실패했는가" 를 관찰·분류하는 축이지 "실패했는가" 를 결정하는 축 아님.
- **★ 이 원칙을 어기면 결과 리포트가 판정 문서를 사후 수정하는 셈**이 된다.

### §4.4 결과 리포트 사후 수정 금지 (Tier 1/2 §7 원칙)

- Tier 1 · Tier 2 결과 리포트 · 개정 사전등록 어느 것도 사후 수정 안 함.
- Tier 3 결과는 별건 문서 (`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER3_RESULTS.md`).
- Tier 2 addendum 필요 시 참조 링크 한 줄만 (Tier 1 §3.4 addendum 선례).

---

## §5 — 비용 관리 · 중단 조건

### §5.1 프레임워크당 예상 소요

**측정 기준** (Tier 2 실측 평균 기반):
- 세팅 (설치 · `_instrument()` 소스 확인 · stub 결정): **20-40 분**.
- probe 스크립트 작성: **20-30 분**.
- dump 관찰 · ingest · cascade: **10-20 분**.
- 결과 문서 (`.md`) 작성: **20-30 분**.
- **프레임워크당 기본**: **70-120 분** (평균 90 분).

**26 프레임워크 합계**: 30-52 시간 (평균 39 시간).

**분산 요인**:
- 1차 에이전트 12 개: 평균 90 분/개 · 18 시간.
- 2차 LLM 클라이언트 5 개: 평균 60 분/개 (Anthropic 유사 · 세팅 단순) · 5 시간.
- 3차 특수 9 개: 평균 60-120 분/개 (baml/promptflow 등 소스 설치 시 편차 큼) · 10-18 시간.

### §5.2 ★ 중단 조건 — 결과 보기 전에 정한다

**중단 = "조사 불가" 기록 후 다음 프레임워크로 넘어감**. 판정 아님. Tier 3 결과 리포트에 별도 카테고리로 기록.

**"과도하게 복잡"의 기준 (결과 보기 전 확정)**:

| # | 조건 | 판단 |
|---|---|---|
| C1 | 세팅에 실 네트워크 호출 필요 · 대체 없음 | **조사 불가** (실 API 호출 금지) |
| C2 | Stub 3 회 시도 실패 · 새 방식 필요 시 | **조사 불가** (Tier 1 선례: stub 이 과하면 멈춤) |
| C3 | 소스 설치 필요 + `_instrument()` 소스 자체가 명확한 wrap 대상 없음 (`promptflow` 후보) | **조사 불가** |
| C4 | 프레임워크 자체 설치가 heavy 의존성 (예: 5GB+ · 로컬 모델 필수) | **조사 불가** |
| C5 | Instrumentor 문서상 "context propagation only" 명시 (MCP 형) | **out-of-scope** (T2.5 선례) |
| C6 | 세팅 단계에서 probe 실행 시도가 **5회 초과** | **조사 불가**. ★ "시도" 정의: probe 스크립트를 실행해 dump 를 얻으려다 실패한 횟수. 소스 읽기·검색·설치는 시도에 포함하지 않는다. ★ 근거: 횟수는 셀 수 있고 시간은 못 센다. C2 가 이미 "stub 3회 실패" 로 횟수 기준을 쓰므로 일관된다. |

**★ C1-C6 는 결과 보고 정하지 않는다. 이번 사전등록에서 확정.**

**중단 시 기록 방식**:
- Tier 3 결과 리포트에 "조사 불가" 섹션 · 각 프레임워크당 중단 조건 (C1-C6) 명시 · dump 없음.
- 판정 표에 "판정 불가 — 세팅 불가 (C_N)" 로 기록.
- FAIL 이 아님. 판정 대상 미확립.

### §5.3 배치 처리 · 재현성

- 프레임워크당 별건 세션 아님 · Tier 2 처럼 연속 세션에서 순서대로 처리.
- **각 프레임워크 종료 시 전체 pytest 1 회** (Tier 2 관례) — 어댑터·설정 무변 확인.
- 결과 문서 (`.md`) 및 dump 는 **미커밋 로컬** (Tier 2 관례).
- Tier 3 완료 후 결과 리포트만 커밋 (별건 사전등록 후 별건 PR).

### §5.4 ★ 릴리스 지점 — 1차 완료 시점

**★ 1차 (에이전트 12 개) 완료 시점이 릴리스 지점이다.**

**근거**:
- §2 가 이미 "1차 → 2차 사이에 유형 재검토 지점" 을 두었다.
- 정보 밀도가 1차에 몰려 있다 (새 유형 가능성 · 우리 대상 근접).
- 2·3차는 유형 A 예상이므로 PASS 가 늘지 않을 가능성이 높고, 그러면 공개 표현 (§4.1 목록) 이 바뀌지 않는다.
- **★ 전수 조사를 포기하는 것이 아니다. 26 개 전부 조사한다. 릴리스가 조사 완료를 기다릴 이유가 없다는 것뿐이다.**

**릴리스 시점 스코프**: Tier 3 1차 결과 + 그때까지의 별건.

**릴리스 후 이어지는 작업**:
- 2차 LLM 클라이언트 5 개 조사 (릴리스 이후).
- 3차 특수 9 개 조사 (릴리스 이후).
- 필요 시 후속 릴리스에서 목록 갱신.

---

## §6 — 산출물

### §6.1 이번 사전등록 커밋 (승인 후)

- **이 파일** (`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER3_PREREG.md`).
- **docs-only commit.**
- Rule 8 — 별건 branch (`prereg/framework-expansion-tier3` 등) · 승인 후 PR 개설.

### §6.2 조사 실행 시 생성될 산출물 (승인 후 별건)

- 프레임워크당 (26 개):
  - `field_test/diagnostics/framework_probe_<name>.py` (미커밋)
  - `field_test/diagnostics/framework_probe_<name>_PREDICTION.md` (미커밋)
  - `field_test/diagnostics/framework_probe_<name>.md` (미커밋 · 결과)
  - `field_test/diagnostics/framework_expansion_dumps/<name>.json` (미커밋 · dump)
  - Multi-run 필요 시: `framework_probe_<name>_multirun.py` + dump.
- Tier 3 완료 후: `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER3_RESULTS.md` (별건 PR).

### §6.3 승인 후 이어질 작업 순서

1. 이 사전등록 merge → 조사 실행 시작 (별건).
2. 1차 에이전트 12 개 순서대로 조사 · 새 유형 (D) 발견 시 규약 (§4.2) 적용.
3. **1차 종료 후 짧은 정지 지점** — 새 유형 발견 여부에 따라 2차 방식 재검토.
4. 2차 LLM 클라이언트 5 개.
5. 3차 특수 9 개.
6. Tier 3 결과 리포트 별건 사전등록 · 별건 PR.

---

## §7 — 불가침

### §7.1 값 무변

- `waste_span_ids sha256`: `cand=5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4`, `pair=742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0`.
- `between_window_counts`: `1226/888/405/248/1024`.
- `id_bridge_candidates`: `differ/same/no_id = 159/76/3197`.
- `eval/set_manifest.json` sha256: `a205a3d62e8310f67f0ab1a7faa957504b9f486a8c5a68cebeadf010aff42952`.
- `coverage_stats` 6 필드.

### §7.2 탐지 로직 · 동결 파라미터

- φ = 0.514345, N = 2, model `paraphrase-multilingual-MiniLM-L12-v2` @ rev `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
- `cascade` / `structural` / `semantic` 로직.
- `_ID_BRIDGE_MAPPING` 26 도구.
- `raw_output_text` fallback 규약.

### §7.3 어댑터 · preprocess · 코드 무변

- **★ Tier 3 은 조사다. 코드 변경 없음.** `src/clew/*` 어느 파일도 수정하지 않는다.
- 어댑터 확장 (예: attr-only tool_calls → pseudo-TOOL span shim) 은 별건 (§8).

### §7.4 원 문서 사후 수정 금지

- Tier 1 · Tier 2 결과 리포트 · Tier 1/Part 1/Part 2/개정 사전등록 어느 것도 사후 수정 안 함.
- 이 사전등록도 이후 결과 보고 사후 수정 안 함 · addendum 만 허용 (참조 링크 한 줄).

---

## §8 — 범위 밖

| 항목 | 이유 · 후속 |
|---|---|
| 어댑터 수정 (attr-only tool_calls shim 등) | 결과 보고 별건. Tier 2 결과 §8 B7/B9 계열. |
| R5 개정 (별건 B1) | Tier 2 결과 §8 B1. Tier 3 완료 후 판단. |
| 유형 C 대응 · 사일런트 실패 신호 (별건 B2) | Tier 2 결과 §8 B2. |
| Part 3 (Format C R2 정합, 별건 B3) | Tier 2 결과 §8 B3. |
| Format A `_kind_of` fallback (별건 B4) | Tier 2 결과 §8 B4. |
| 릴리스 | Tier 다 완료 후 별건. |
| JS/TS instrumentation | §1.4 근거 — 어댑터가 Python `ReadableSpan` 전용. 별건 (어댑터 확장 필요). |
| 새 프레임워크 fixture 커밋 | 조사는 로컬 (미커밋). 프레임워크 fixture 정식 커밋은 별건. |

---

## §9 — 확인 질의 (승인자 확정 답 기록)

| # | 질의 | 확정 답 |
|---|---|---|
| Q1 | §1.5 Tier 3 대상 26 개 전수 조사 확정 | **동의** — 26 개 전수 · 조기 종료 없음 |
| Q2 | §2 조사 순서 (1차 에이전트 12 → 2차 LLM 5 → 3차 특수 9) 확정 | **동의** — 정보 밀도 근거 그대로 |
| Q3 | §3 세팅 규약 (`_instrument()` 소스 우선) 확정 | **동의** — Tier 2 §3.2 규칙 채택 |
| Q4 | §4.2 유형 D 신설 규약 · §4.3 유형이 판정 축 아님 규칙 확정 | **동의** — 판정은 R1-R5 로만 |
| Q5 | §5.2 중단 조건 C1-C6 확정 | **★ C6 교체 후 동의** — C6 를 "probe 실행 시도 5회 초과" (횟수 기준) 로 교체. C2 와 일관. 시간 기준은 프레임워크별 난이도 편차로 애매. |
| Q6 | §5.1 예상 소요 (프레임워크당 70-120 분 · 총 30-52 시간) 수용 가능한가 | **★ 1차 뒤 릴리스로 분리** — §5.4 신설. 1차 (에이전트 12) 완료 시점이 릴리스 지점. 전수 조사는 계속 (2·3차 릴리스 이후). |
| Q7 | §7.3 코드 변경 없음 · §8 어댑터 수정은 별건 확정 | **동의** — 그대로 |

---

## §10 — 참조

### 사전등록 · 결과 리포트
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (Tier 1 원 사전등록).
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` (Tier 1 결과 + §3.4 addendum).
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` · `docs/ADAPTER_R2_RELAXATION_PART2_PREREG.md` (Part 1/2).
- **`docs/OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`** (개정 판정 축).
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_TIER2_RESULTS.md` (Tier 2 결과 · 유형 A/B/C · 방법론 §).

### 웹 실측 앵커
- [Arize openinference 모노레포 python/instrumentation](https://github.com/Arize-ai/openinference/tree/main/python/instrumentation) — 33 개 dir.
- [PyPI simple index](https://pypi.org/simple/) — `openinference-instrumentation-` prefix 검색.
- [openinference-instrumentation-vertexai pyproject.toml](https://raw.githubusercontent.com/Arize-ai/openinference/main/python/instrumentation/openinference-instrumentation-vertexai/pyproject.toml).
- [openinference-instrumentation-google-genai pyproject.toml](https://raw.githubusercontent.com/Arize-ai/openinference/main/python/instrumentation/openinference-instrumentation-google-genai/pyproject.toml).
- [Google GenAI migration guide](https://cloud.google.com/vertex-ai/generative-ai/docs/migrate/migrate-google-genai) (§1.3 근거).
- [Arize openinference JS packages](https://github.com/Arize-ai/openinference/tree/main/js/packages) (§1.4 배제 근거).

### 코드
- `src/clew/ingest/langgraph.py:29-30, 139` — Python `ReadableSpan` 전용 (§1.4 근거).
- `src/clew/model.py`, `src/clew/detect/`, `src/clew/report/_enrich.py` — 판정 로직.

### Memory
- `memory/feedback_prereg_vs_local_design.md`.
- `memory/feedback_dump_before_shim.md`.
- `memory/feedback_thorough_investigation.md`.

---

**★ 이 문서는 DRAFT. 승인자 확인 · 질의 Q1-Q7 답변 후 최종 문안 확정 · 커밋.**
