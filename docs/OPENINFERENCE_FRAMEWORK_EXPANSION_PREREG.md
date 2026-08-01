# OpenInference framework expansion — Pre-registration (2026-08-01)

**작성 시각 (UTC)**: 2026-08-01T00:00:00Z
**HEAD 해시**: `main @ ad32d87` (Merge PR #52, `feat/raw-output-text` merged) 기준으로 컷.
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**선행**:
- `docs/OPENINFERENCE_ADAPTER_PREREG.md` — 어댑터 뼈대 (LangChain·CrewAI 2 개 fixture 근거).
- `field_test/diagnostics/openinference_output_text_fix_PREREG.md` v3 (로컬) — `raw_output_text` 신 필드 · 안전망.
- `field_test/diagnostics/probe_h.py` — preprocess 호출 위상 실측.
- 커밋 `ce0996c` / `a40f3a7` / `c4222cf` (PR #52 merge `ad32d87`) — `raw_output_text` 도입.

---

## §0 — 이 사전등록이 하는 것 · 하지 않는 것

**하는 것.**
- OpenInference 계측을 지원한다고 주장하는 여러 프레임워크가 실제로 우리 어댑터로 무수정 통과하는지 실측.
- **결과를 보기 전에** 동형 판정 축, 3분류 (PASS / PARTIAL / FAIL) 정의, 공개 표현 임계를 확정.
- 각 프레임워크에 대해 dump-first 로 최소 트레이스 확보 → 분류.
- 조사이지 수정이 아니다. 확대 중 결함이 나오면 별도 커밋 · 별도 사전등록.

**하지 않는 것.**
- 어댑터 코드 수정. 결함이 확인되면 별건 (§10).
- 신규 프레임워크에 특화된 shim 추가. 위와 동일.
- `clew.yaml` 확장 · 도구 매핑 확대.
- Pingpong 탐지기 재정의. `preprocess_trace` 가 LLM span 을 제거하므로 데이터가 있어도 탐지기는 별건 (§7).
- 새 결함 fix (안전망 `raw_output_text` 가 작동하는지만 관찰).
- `waste_span_ids` / `between_window_counts` / `id_bridge_candidates` / `eval/set_manifest.json` sha 어느 것도 값이 변하지 않아야 한다 (§9).

---

## §1 — 배경 · 문제 진술

### §1.1 표본 크기 문제

현재 OpenInference 계측 실측 확인 = **LangChain + CrewAI 2 개**. 이 2 개 는 `docs/OPENINFERENCE_ADAPTER_PREREG.md` 근거로 어댑터 매핑을 잡아 fixture 로 회귀했다. 하지만 OpenInference 공식 목록에는 **20 개 이상 프레임워크가 존재**. "어댑터 하나로 여러 프레임워크 커버" 라는 주장의 실측 근거는 **2 개** 뿐이다.

### §1.2 확대의 위험

`field_test/diagnostics/openinference_output_text_fix_PREREG.md` v3 §7 한계에서 이미 명시: "신규 fixture 는 `ux_agent.py` (LangChain) 실측이므로, 이 수정이 다른 프레임워크의 봉투 형태에서도 성립하는지는 미확인." 새 프레임워크의 봉투 형태·필드 위치가 다를 수 있고, 그 결함이 조용히 waste 미탐지로 이어질 수 있다.

### §1.3 안전망 도입 상태 (2026-08-01)

`Span.raw_output_text` 가 optional 필드로 존재 (PR #52 merge). tool span 은 preprocess 가 원본 payload 를 보존하므로 어댑터가 봉투를 못 벗겨도 id_bridge 는 fallback 로 동작. 이 안전망이 새 프레임워크에서도 실제로 작동하는지 확인이 이번 스코프에 포함.

---

## §2 — ★ 동형 판정 축 (결과 보기 전 확정, 불가침)

프레임워크가 우리 어댑터를 무수정 통과하려면 span attribute 가 다음 축들에서 특정 값을 가져야 한다. 결과 보고 임계를 바꾸지 않기 위해 여기서 필수/선택을 확정한다.

### §2.1 필수 축 (하나라도 어긋나면 어댑터 수정 필요)

| # | 축 | 조건 | 근거 |
|---|---|---|---|
| R1 | `openinference.span.kind` | 존재 · 값 ∈ {`LLM`, `TOOL`, `CHAIN`, `AGENT`, `RUNNABLE`} | `langgraph.py::_KIND_MAP` 이 이 다섯만 매핑. 없거나 다른 값이면 span 이 제거되거나 kind 판정 실패. |
| R2 | `output.value` | 존재 · 비어 있지 않음 (strip 후 len ≥ 1) | `Span.output_text` 검증기가 요구 (`model.py:38-43`). 없으면 어댑터가 raise. |
| R3 | tool span 에서 도구 식별 가능 | `tool.name` attribute 존재 **또는** `span.name` 이 도구명과 일치 | `_agent_or_node_id_of` fallback 순서 (`tool.name` → `span.name`) 로 이미 처리. 둘 다 없으면 도구별 waste 탐지 불가. |
| R4 | timestamp | `start_time` · `end_time` 존재 · UTC-aware · `end ≥ start` | `Span` 검증기 (`model.py:45-50, 66-70`). |
| R5 | trace/span/parent ID 3 축 | trace_id · span_id 필수, parent_span_id 는 root 에서 None | `Trace._validate_tree` 가 요구 (root 1 개, cycle 없음, orphan 없음). |

### §2.2 선택 축 (없어도 부분 동작 — PARTIAL 원인)

| # | 축 | 없을 때 영향 |
|---|---|---|
| O1 | `graph.node.id` (agent span) | agent 식별이 `span.name` fallback. LangGraph 특유 축이라 대부분 프레임워크에서 없음 예상. |
| O2 | `output.mime_type` | 봉투 분기 없이 raw 로 시도. `_extract_tool_output` 이 mime 없으면 raw 반환. |
| O3 | `input.value` | 진단·문맥 정보만 손실. 탐지 자체엔 영향 없음. |
| O4 | `token_count` / `model` / `cost_rate` | amplification 추정만 못 함 (approx flag). cascade 판정 무영향. |
| O5 | `tool.name` (span.name 만으로 도구 식별 가능한 경우) | R3 fallback 이 커버. |

### §2.3 봉투 형태 — 판정 대상 아니라 관찰 대상

**봉투 형태는 PASS/PARTIAL/FAIL 판정 축이 아니다. 관찰·기록 대상이다.**

원 draft 는 봉투 형태를 sha256 일치로 판정 축에 넣었으나 순환이었다: 같은 인자 2회 호출은 봉투 해제와 무관하게 sha256 이 일치할 수 있으므로, sha256 일치는 봉투 해제 여부를 증명하지 못한다.

#### [관찰 — primary, 필수]

각 프레임워크 dump 에서 tool span 의 `output.value` 원문을 그대로 결과 리포트에 기록한다:
- `output.mime_type` 값.
- 봉투 유무. 있으면 그 구조 (키 경로, 예: `data.content` / `results[0].text` / …).
- `_extract_tool_output` 이 인식하는 형태인가.

**★ 판정하지 말고 원문을 기록한다. 이 기록 자체가 누적 자산이다** — 도구별 응답 구조 매핑은 이 프로젝트의 실질 해자이므로, 조사 절차에서 이 기록을 빠뜨리면 안 된다.

#### [확인 — secondary]

sha256 일치 여부는 **결과 확인이지 봉투 판정 근거가 아니다.** 같은 인자 2 회 호출은 봉투 해제 여부와 무관하게 응답 자체가 같아 sha256 이 일치할 수 있다. 참고 지표로만 결과 리포트에 병기한다.

#### [판정에 미치는 영향]

봉투가 모르는 형태여도 §2.1 R1-R5 만족 시 **PASS**.
- 근거: 모르는 봉투는 `output_text` 에 raw JSON 으로 남고, `raw_output_text` 안전망이 id_bridge 를 커버한다.
- cascade recall 손실 가능성은 §7 한계에 별도 기록 (판정에는 미반영).

**★ 봉투 차이를 PARTIAL 사유로 쓰지 않는다.** 그러면 판정이 "우리가 이미 아는 봉투인가" 에 좌우되어 순환한다 (원 draft 결함).

### §2.4 pingpong 축 (별도, §7 로 분리)

- `LLM` span 이 agent 서브트리 안에 있는가 (pingpong 축 발동 조건).
- 실제 A→B→A 왕복이 트레이스에 존재하는가.

**이 두 축은 §2 필수/선택에 포함하지 않는다.** 데이터 존재 여부만 §7 에 별도 기록.

---

## §3 — ★ 프레임워크별 3분류 (결과 보기 전 확정, 불가침)

각 프레임워크는 dump 후 다음 셋 중 하나로 분류:

### §3.1 PASS 조건

- §2.1 필수 축 R1-R5 **전부 일치**.
- §2.2 선택 축 O1-O5 는 **관측·기록만 한다. 부재 자체는 PASS 를 막지 않는다.**

봉투 형태 (§2.3) 도 판정 축이 아니다. 관찰 결과는 결과 리포트에 별도 기록.

### §3.2 PARTIAL 조건

- §2.1 필수 축 R1-R5 **전부 일치**.
- 단, 선택 축 부재로 인해 **어댑터 기능이 실제로 저하되는 경우**.

**★ "축이 없다" 가 아니라 "무엇을 못 하게 되는가" 로 판정한다.**

기능 저하 여부 판정 예:
- `token_count` / `model` / `cost_rate` 부재 → amplification 추정 불가. **저하 (PARTIAL 사유).**
- `graph.node.id` 부재 → `span.name` fallback 으로 정상 동작. **저하 아님 (PASS 유지).**
- `output.mime_type` 부재 → `_extract_tool_output` 이 raw 반환, `raw_output_text` 안전망 정상. **저하 아님 (PASS 유지).**
- `input.value` 부재 → 진단·문맥 정보만 손실. **저하 아님 (PASS 유지).**

무엇이 저하되는지 결과 리포트에 명시. 봉투 sha256 불일치도 PARTIAL 사유가 아니다 (§2.3). recall 손실 가능성은 §7 한계에 별도 기록.

**★ 이 기준을 결과 보기 전에 확정한다. 결과를 보고 완화·강화하지 않는다.**

### §3.3 FAIL 조건

- §2.1 필수 축 R1-R5 **하나라도 불일치**.
- 어댑터가 예외를 던지거나 Span 생성 실패.
- 무엇이 없거나 무엇이 다른지 명시 기록.

### §3.4 판정 규칙

- 각 프레임워크 dump 는 **같은 tool · 같은 args 2 회 호출** 을 반드시 포함해야 함 (§6). §2.3 봉투 관찰과 recall 참고용 sha256 확인의 근거.
- 판정은 dump 하나당 1 회. 프레임워크 여러 dump 가 있으면 최악 등급 채택 (예: 두 dump 중 하나 FAIL → 전체 FAIL).
- **PARTIAL / FAIL 판정 시 근거 축과 관찰 값을 결과 리포트에 반드시 인용**. "약간 다름" 같은 서술 금지.
- **PARTIAL 판정 시 저하된 기능을 명시하는 문장 필수** ("무엇을 못 하게 되는가"). "축이 없다" 만으로는 PARTIAL 사유 성립 안 함.

---

## §4 — ★ 공개 표현 임계 (결과 보기 전 확정, 불가침)

이번 조사 결과 몇 개가 PASS 여야 어떤 표현을 쓸 수 있나. **결과 보고 임계를 바꾸지 않기 위해 여기서 확정.**

### §4.1 이름 나열 규약 — 개수 등급 폐지

**PASS 개수와 무관하게 항상 실측 확인된 이름만 나열한다.**

허용 템플릿:

> "OpenInference 계측 N 개 프레임워크에서 실측 확인 — LangChain, CrewAI, `<추가된 이름>`."

**금지 표현 (개수 무관):**
- "여러 프레임워크"
- "다양한 프레임워크"
- "OpenInference 지원" (이름 병기 없이)
- "20 개 이상" 또는 이름 없는 개수만의 언급

**근거**: 요약어가 실측보다 커지는 것을 막는다. 이 프로젝트의 선례 계열과 같다 — "5.7배" 금지 (회색지대 포함값), "멀티에이전트 검증 완료" 금지 (사례 확인까지만), "X% 절감" 금지 (측정 0 건). 공식 목록에 20 개 이상이 있는 상황에서 "여러" 를 쓰면 인용 시 확대 해석된다. "여러 프레임워크 지원 (A, B, C)" 는 앞부분만 잘려서 인용된다. 이름 나열만 있으면 잘라도 실측 이름만 남는다.

**PASS = 0 새로 늘어남 (2 유지)**: `openinference_output_text_fix_PREREG.md` v3 §7 한계 문면 유지 — 실측 확인은 여전히 LangChain / CrewAI 2 개.

### §4.2 PARTIAL 표기 규칙

- 지원 목록에 **넣지 않는다**. "지원" 은 PASS 만.
- 별도 섹션에 "실측했으나 부분 동작 — 다음 축이 다름" 으로 기록. 사유 축 함께 명시.
- 임계 계산 (§4.1) 에는 PARTIAL 을 포함하지 않는다.

### §4.3 FAIL 표기 규칙

- 지원 목록에 명시적으로 **미지원** 으로 기록. 무엇이 없거나 다른지 함께 명시.
- 임계 계산 (§4.1) 에는 포함하지 않는다.

### §4.4 표현 이월 금지

- README · 홍보문 · PR 설명 어디서든 §4.1 이름 나열 규약을 벗어난 표현 사용 금지.
- 판정 근거 없이 프레임워크 이름을 나열하는 것도 금지 (예: "LlamaIndex 도 됩니다" 를 확인 없이 쓰는 것).

---

## §5 — 대상 프레임워크 · 우선순위

### §5.1 Tier 1 — 필수 시도 (최소 4 개)

| # | 프레임워크 | 근거 |
|---|---|---|
| T1.1 | **LlamaIndex** | 인기 상위, tool-use / agent 지원 성숙, OpenInference 공식 instrumentor 존재. |
| T1.2 | **OpenAI Agents SDK** | 2025-2026 급성장, tool-워크플로우 중심, 공식 OpenInference 계측. |
| T1.3 | **Anthropic (SDK direct)** | tool_use 지원 확실. Claude Code 사용자 근접 표본 (인접성). |
| T1.4 | **AutoGen** | multi-agent — pingpong 데이터 후보. §7 로도 관측 가치. |

### §5.2 Tier 2 — 여유 시 (Tier 1 결과 보고 선별)

| # | 프레임워크 | 근거 |
|---|---|---|
| T2.1 | Pydantic AI | 신규 인기. |
| T2.2 | Google GenAI | 커버리지 확장. |
| T2.3 | Haystack | 검색 / RAG 중심. |
| T2.4 | Smolagents (HuggingFace) | 최소 agent. |
| T2.5 | MCP | 프로토콜 레벨. instrumentation 가능 여부 자체 미확인. |

### §5.3 시도 순서 · 예산

Tier 1 T1.1 → T1.2 → T1.3 → T1.4 순차. Tier 1 완료 후 결과를 보고 승인자가 Tier 2 진행 여부를 결정한다.

**★ 이건 조사 예산 규칙이지 판정 기준이 아니다.** §4.1 표현 규약과 무관하며, **PASS 개수로 조사를 조기 종료하지 않는다.** 근거: 조기 종료하면 나머지 프레임워크에서 나올 결함을 못 본다 (`raw_output_text` 도입이 정확히 이 시나리오였음 — 2 개 fixture 만 봤을 때 결함을 못 봄).

### §5.4 우선순위 근거 노트

- 인지도 · 사용자 밀접도 우선.
- 공식 OpenInference instrumentor 존재하는 것 우선 (설치·설정 비용 절감).
- Multi-agent 프레임워크 (AutoGen) 는 pingpong 데이터 존재 여부 관측 부산물 목적 포함.
- MCP 는 우선순위 마지막 — instrumentation 접근 방식이 다른 프레임워크와 이질적일 가능성 (검증 후 별건 여지).

---

## §6 — 방법 — dump-first

### §6.1 원칙

- **어댑터 코드를 건드리기 전에** 각 프레임워크를 실제 돌려 span dump 를 뜬다 (`memory/feedback_dump_before_shim`).
- **FakeChatModel / stub LLM** 사용으로 LLM 비용 0 유지. `field_test/diagnostics/ux_agent.py` 스타일 참고 (LangGraph + `@tool` 두 번 호출).
- 실제 프레임워크 API 로 계측 · exporter (`InMemorySpanExporter`) 로 캡쳐 → `to_json()` 리스트를 JSON 배열로 파일 저장.

### §6.2 최소 시나리오 (프레임워크당 1 개 dump)

- **동일 tool 2 회 호출** — 같은 args, 다른 raw payload 반환 (예: `create_ticket` × 2 → `T-1`, `T-2`).
- **가능하면** side-effect tool 1 개 · read-only tool 1 개 포함.
- LLM 호출 자체는 FakeChatModel 또는 stub 로 대체.

### §6.3 dump 저장 위치

- **로컬 (커밋 금지)**: `field_test/diagnostics/framework_expansion_dumps/<framework>.json`.
- 결과 리포트에 요약만 인용. 원본 dump 는 로컬 유지 (진단 스크립트 정책).
- 예외: PASS 판정된 프레임워크 dump 는 fixture 후보 (별도 사전등록 · 이번 스코프 밖).

### §6.4 분류 절차 (프레임워크당)

**★ 원문 기록 없이 sha256 만 보는 절차는 금지.** 봉투 관찰이 판정보다 앞에 온다.

1. dump 생성.
2. **봉투 원문 관찰 (§2.3 primary)** — tool span 의 `output.value` 원문을 그대로 결과 리포트에 기록:
   - `output.mime_type` 값.
   - 봉투 유무 및 구조 (키 경로).
   - `_extract_tool_output` 이 인식하는 형태인가.
   판정하지 말고 원문을 표로 정리한다.
3. `clew.io.load_trace` / `ingest_from_otel_json` 으로 로드 시도. 예외 발생 → **FAIL**, 예외 메시지 기록.
4. 로드 성공 → §2.1 R1-R5 축 값 확인. 하나라도 부재 → **FAIL**.
5. §2.2 선택 축 O1-O5 관측. 전부 채움 → **PASS**. 하나 이상 부재 → **PARTIAL** (사유 축 기록).
6. **sha256 참고 지표 (§2.3 secondary)** — 같은 tool 2 회 호출의 `Span.output_text` sha256 비교 결과를 결과 리포트에 병기. 판정에는 반영하지 않는다 (§3.2).
7. `raw_output_text` 안전망 관측: tool span 에 payload 원본이 담겼는지 확인. 안 담긴 경우 사유 기록.

---

## §7 — pingpong — 부산물

### §7.1 스코프

**이번 사전등록에서 pingpong 은 목표가 아니다.** 다음만 관측:

- 각 프레임워크 dump 에서 **LLM span 이 agent 서브트리 안에 존재하는가**.
- multi-agent 프레임워크 (AutoGen 등) dump 에서 **A→B→A 왕복 패턴이 관측되는가**.

관측 결과는 결과 리포트에 별도 섹션으로 기록하되 **동형 판정에는 반영하지 않는다**.

### §7.2 BLOCKED 재개 조건 (memory 준수)

- `memory/project_pingpong_blocked.md` 위상 정정 (2026-08-01) 준수:
  - BLOCKED = 측정할 외부 코퍼스가 없음. KILL 아님.
  - **재개 조건**: 외부 저작 코퍼스에서 A→B→A 왕복 실존 확인.
  - **★ 우리가 만든 예제에서 찾으면 증거가 아니다** (자기충족). 외부 저작만.
- 이번 조사에서 pingpong 데이터가 관측되어도, **탐지기 재정의는 별건 사전등록** 이다. 데이터 존재 여부까지가 이번 스코프.

### §7.3 preprocess 로 인한 구조적 한계 (기록)

- `preprocess_trace` (`langgraph.py:225` 유일 호출) 는 LLM span 을 제거 (`collapse_llm_spans`).
- pingpong 은 LLM span 왕복이 축이므로, **데이터가 있어도 preprocess 이후 관측 불가**.
- 탐지기가 pingpong 을 열려면 preprocess 를 우회하거나 preprocess 전 트리에서 판정해야 함. 이 재설계는 이번 사전등록에서 다루지 않는다.

---

## §8 — 새 결함 처리 방침

### §8.1 발견 시 처리

확대 중 다음이 관측되면:

- **새 봉투 형태** (`_extract_tool_output` 미인식): 결과 리포트에 봉투 shape 기록. 어댑터 수정은 별건.
- **필수 축 부재** (R1-R5 중 하나): FAIL 판정. 어떤 축이 어떻게 부재한지 기록. 어댑터 확장은 별건.
- **`raw_output_text` 안전망 미작동**: 원본 payload 접근 불가. 결과 리포트에 근거 기록. `Span.model` 자체 수정 필요할 수 있으나 이번 스코프 밖.

### §8.2 이번 사전등록의 한계

- **조사이지 수정이 아니다.**
- 결과 리포트 (`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md`) 작성이 최종 산출물.
- 수정이 필요한 항목은 결과 리포트에 별도 "후속 사전등록 후보" 섹션으로 열거하되, 이번 커밋에서 수정 자체는 하지 않는다.

---

## §9 — 불가침 게이트

### §9.1 값 무변

- `waste_span_ids sha256`: `cand=5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4`, `pair=742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0`.
- `between_window_counts`: `1226/888/405/248/1024`.
- `id_bridge_candidates`: `differ/same/no_id = 159/76/3197`.
- `eval/set_manifest.json` sha256: `a205a3d62e8310f67f0ab1a7faa957504b9f486a8c5a68cebeadf010aff42952` (2026-08-01 재동결본).
- `coverage_stats` 6 필드.

### §9.2 탐지 로직 · 동결 파라미터

- φ = 0.514345, N = 2, model `paraphrase-multilingual-MiniLM-L12-v2` @ rev `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
- `cascade` / `structural` / `semantic` 로직.
- `_ID_BRIDGE_MAPPING` 26 도구.
- `raw_output_text` fallback 규약 (`_enrich.py::scan_id_bridge_candidates`).

### §9.3 어댑터 · preprocess 무변

- 이번 사전등록은 조사. `src/clew/ingest/*` · `src/clew/model.py` 어느 파일도 수정하지 않는다.
- `preprocess_trace` 호출 위상 무변 (`langgraph.py:225` 유일).

### §9.4 산출물이 아닌 것

- 이번 사전등록에서는 새 fixture 를 `tests/fixtures/` 에 커밋하지 않는다. 그건 후속 사전등록 (PASS 확인된 프레임워크 개별 · 회귀 fixture 추가).

---

## §10 — 범위 밖

| 항목 | 이유 · 후속 |
|---|---|
| 어댑터 코드 수정 (`_extract_tool_output` shim 확장 등) | 결함 확인 후 별건 사전등록. |
| 신규 봉투 unwrap 로직 | 위와 동일. |
| Pingpong 탐지기 재정의 | 데이터 존재 확인 후 별건. `preprocess_trace` 우회 설계도 별건. |
| `clew.yaml` 도구 매핑 확장 | Phase 3+ 이월. |
| PASS 프레임워크의 회귀 fixture 커밋 | 프레임워크당 별건 (LangChain·CrewAI 선례). |
| README 지원 프레임워크 목록 갱신 | §4.1 임계 확인 후 별건. **결과 리포트만 이번 스코프.** |
| Tier 2 프레임워크 전수 조사 | Tier 1 결과 보고 결정 (§5.3). |
| Anthropic beta features (extended thinking 등) | tool_use 만 대상. beta feature 는 별건. |
| v0.4.0 릴리스 자체 | 확대 결과 + `raw_output_text` 합류 후 별건 릴리스 (v3 draft §8.1 참조). |

---

## §11 — 산출물

### §11.1 이번 사전등록 커밋

- **이 파일** (`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md`). 사전등록 커밋.
- 이 사전등록에는 코드·테스트 변경 없음. **PR 필요 없음 · docs-only commit**.
- 사용자 승인 후 별도 branch (`prereg/framework-expansion`) 로 커밋 · PR 개설 → merge.

### §11.2 조사 실행 커밋 (사전등록 승인 후 별도)

- `field_test/diagnostics/framework_expansion_dumps/*.json` (로컬, 커밋 금지).
- 각 프레임워크 dump 스크립트 (`framework_expansion_probe_<name>.py`, 로컬).

### §11.3 결과 리포트 (별도 사전등록 · docs/ 커밋)

**`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md`** — 별도 커밋. 다음 표 형식으로 채운다:

| 프레임워크 | R1-R5 | O1-O5 | 봉투 sha 일치 | 안전망 작동 | 3분류 | 관찰 노트 |
|---|---|---|---|---|---|---|
| LlamaIndex | ✓ | … | … | … | PASS/PARTIAL/FAIL | … |
| OpenAI Agents SDK | … | … | … | … | … | … |
| Anthropic | … | … | … | … | … | … |
| AutoGen | … | … | … | … | … | … |
| (Tier 2 …) | … | … | … | … | … | … |

+ **pingpong 관측 별도 섹션** (§7).
+ **§4.1 임계 대조 · 허용 공개 표현 명시**.
+ **후속 사전등록 후보 열거**.

---

## §12 — 확정 답 (승인 완료)

| # | 질문 | 확정 |
|---|---|---|
| Q1 | §2.1 필수 축 R1-R5 목록 · 조건 | **동의** — 유지. |
| Q2 | §3 3분류 기준 · PARTIAL / FAIL 경계 | **§2.3 개정 반영** — 봉투 형태는 PARTIAL 사유에서 제거. **§3.1/§3.2 재개정** — 선택 축 부재 자체는 PASS 를 막지 않는다. PARTIAL 은 "축이 없다" 가 아니라 "무엇을 못 하게 되는가" 로 판정. 새 기준으로 기존 2 개 (LangChain / CrewAI) 재판정 시 둘 다 PASS 유지 확인. |
| Q3 | §4.1 공개 표현 임계 | **개정** — 개수 등급 폐지, 이름 나열 규약 채택 (§4.1). "여러 프레임워크" / "다양한" / 이름 없는 개수만의 언급 전면 금지. |
| Q4 | §5 Tier 1 4 개 순서 | **초안 유지 (T1.4 = AutoGen)** — pingpong 은 부산물이지 목표가 아니다. 순서를 올리면 부산물이 목표가 되어 없는 것을 찾는 데 시간을 쓴다. 또한 T1.1-T1.3 에서 봉투 형태 3 종을 먼저 관찰하면 AutoGen 관찰 시 비교 기준이 생긴다. |
| Q5 | §6 dump-first · FakeChatModel · 2 회 동일 호출 | **동의** — §6.4 에 봉투 원문 관찰 단계를 sha256 앞에 명시적으로 추가. |
| Q6 | §7 pingpong 스코프 (데이터 존재 여부까지) | **동의** — 탐지기 재정의는 별건 (§10). |
| Q7 | §11.3 결과 리포트 포맷 · 별도 사전등록 · docs/ 커밋 | **동의** — 유지. |

---

## §13 — 참조

- `docs/OPENINFERENCE_ADAPTER_PREREG.md` — 어댑터 뼈대 사전등록 (2026-07-31).
- `field_test/diagnostics/openinference_output_text_fix_PREREG.md` v3 — `raw_output_text` 안전망 (로컬).
- `field_test/diagnostics/probe_h.py` — preprocess 호출 위상 실측.
- `field_test/diagnostics/ux_agent.py` — LangChain dump-first 참조 스타일.
- `memory/project_pingpong_blocked.md` — BLOCKED / KILL 위상 정정 (2026-08-01).
- `memory/feedback_dump_before_shim.md` — dump-first 원칙.
- `memory/feedback_prereg_vs_local_design.md` — docs/ vs 로컬 정책.
- `memory/feedback_no_hypothetical_case_judgment.md` — 결과 없이 원리-판정 금지.
- PR #52 (`ad32d87`) — `raw_output_text` 도입.
