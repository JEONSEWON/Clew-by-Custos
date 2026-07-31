# OpenInference adapter — Pre-registration (2026-07-31)

**작성 시각 (UTC)**: 2026-07-31T00:00:00Z
**HEAD 해시**: `prereg/openinference-adapter` (main 기준으로 컷)
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**선행**: `field_test/diagnostics/langchain_dump.md` + `field_test/diagnostics/crewai_dump.md` (2026-07-31 dump 실측).

---

## §0 — 이 사전등록이 하는 것 · 하지 않는 것

**하는 것.** 이미 존재하는 OpenInference/OTel 어댑터 (`src/clew/ingest/langgraph.py` + `src/clew/ingest/otel_json.py`) 의 매핑을 실측 두 dump (LangChain, CrewAI) 에 맞게 조정. 도구 output 봉투 shim 을 방어적으로 추가.

**하지 않는 것.**
- 신규 어댑터 파일 신설. 기존 파일을 수정한다 (§2, Q1 확정).
- LLM span 의 `agent_or_node_id` 매핑 변경. `s.name` 그대로 (§2, Q3 확정).
- Pingpong detector 재설계. `collapse_llm_spans` 가 LLM span 을 제거하므로 어댑터로는 pingpong 이 열리지 않는다 (§3, Q2 확정).
- `waste_span_ids`, `between_window_counts`, `coverage_stats`, `id_bridge_candidates` 어느 것도 값이 변하지 않아야 한다 (§7).
- OpenAI Agents SDK dump 재확인. 어댑터 착수 후 fixture 추가로 병행 검증 (§10).
- 사용자 정의 도구 매핑 (`clew.yaml`). 이 어댑터가 열리는 순간 커버리지 0% 문제가 심해지지만 별도 사전등록 (§10).
- 파일명 rename (`langgraph.py` → 더 정확한 이름). CrewAI/AutoGen 등도 다루므로 이름이 부정확하나 import·test 재작성 churn 이 크다. 백로그.

---

## §1 — 배경 · dump 실측 발견

### §1.1 어댑터 재발견

`src/clew/ingest/langgraph.py` 는 이미 존재하고 docstring 이 다음을 명시:

> "Accepts spans from any framework using OpenInference instrumentation (CrewAI, AutoGen, LlamaIndex, etc.)."

`_KIND_MAP` 도 이미 `{"LLM":"llm", "TOOL":"tool", "CHAIN":"chain", "RUNNABLE":"chain", "AGENT":"agent"}` 로 존재.

`src/clew/ingest/otel_json.py` 는 dump 된 JSON 파일 두 포맷 (Format A · Format C) 을 받아 내부에서 `ingest_otel_spans` 를 호출.

즉 어댑터의 "뼈대" 는 이미 완성. 이 사전등록은 실측 두 프레임워크에 맞춘 **매핑 조정 + 봉투 shim 추가** 만 담는다.

### §1.2 LangChain dump 관찰 (§1.1, langchain_dump.md)

| 축 | 값 |
|---|---|
| `openinference.span.kind` | `TOOL` (동일) |
| span `s.name` | `"search_web"` |
| `tool.name` attribute | `"search_web"` (동일 값) |
| `input.value` | `"Claude Opus 4.7 release"` (args 원문) |
| `output.value` | `{"type":"tool","data":{"content":"Result 1: …","tool_call_id":"call_N"}}` **(JSON 봉투)** |
| `output.mime_type` | `"application/json"` |
| `start_time` / `end_time` | nanosecond epoch (OTel 표준) |

같은 도구 · 같은 args 두 번 호출 시:
- raw `output.value` sha256 → 서로 다름 (`tool_call_id: call_1` vs `call_2` 봉투 차이).
- 봉투 `data.content` 만 뽑으면 sha256 완전 일치.

### §1.3 CrewAI dump 관찰 (§1.2, crewai_dump.md)

| 축 | 값 | LangChain 대비 |
|---|---|---|
| `openinference.span.kind` | `TOOL` / `AGENT` / `CHAIN` | 동일 (스키마 정합) |
| span `s.name` (TOOL) | `"search_web.run"` **(.run suffix)** | LangChain 은 `"search_web"` — **suffix 차이** |
| `tool.name` attribute (TOOL) | `"search_web"` | 동일 |
| span `s.name` (AGENT) | `"Web Researcher._execute_core"` **(._execute_core suffix)** | LangChain 은 AGENT span 없음 (단일 노드) |
| `graph.node.id` attribute (AGENT) | `"Web Researcher"` / `"Fact Verifier"` (에이전트 이름) | (LangChain 은 미제공) |
| `input.value` (TOOL) | `"{\"query\": \"Claude Opus 4.7 release\"}"` (JSON 문자열) | LangChain 은 `"Claude Opus 4.7 release"` (raw) — **형식 차이는 있으나 매핑 대상 아님** |
| `output.value` (TOOL) | `"Result 1: …"` (raw 문자열, **봉투 없음**) | 봉투 있음 |
| `output.mime_type` (TOOL) | `"text/plain"` | `"application/json"` |
| `crew_id` / `task_id` / `graph.node.parent_id` | 있음 | 없음 |

같은 도구 · 같은 args 두 번 호출 시: raw `output.value` sha256 **즉시 일치** (봉투 없어 call_id 안 실림).

### §1.4 결론 — 스키마 동형, 매핑 조정 필요

두 프레임워크 모두 OpenInference schema 로 방출 (`openinference.span.kind` 축과 `input.value` / `output.value` 축 정합). 어댑터 하나로 커버 가능 — 다만:
- TOOL span 의 `agent_or_node_id` 는 `s.name` 대신 `tool.name` 우선.
- AGENT span 의 `agent_or_node_id` 는 `s.name` 대신 `graph.node.id` 우선.
- 도구 output 봉투는 `mime_type` 기준으로 분기 후 JSON envelope 만 unwrap.

---

## §2 — 2026-07-30 판단 정정 (기록 필수)

2026-07-30 대화에서 다음과 같이 판단했다:

> "CrewAI AGENT 식별자 (graph.node.id) 확보로 pingpong 이 실데이터에서 발동 가능해졌다."

**이 판단은 부정확했다.**

`src/clew/ingest/preprocess.py::preprocess_trace` 의 `collapse_llm_spans` 단계가 **LLM span 을 통째로 제거**하고 `token_count` 만 부모 chain 에 rollup 한다 (참조: `CLAUDE.md` 사실 §2). Pingpong (`src/clew/detect/structural.py::find_pingpong_candidates`) 은 4-window 4개 span 전부 `span_kind == "llm"` 을 요구한다 (line 90-95). 즉 detector 가 보는 트레이스에는 매칭 대상이 없다.

`tests/test_otel_json_ingest.py:142` 가 이를 assert 로 명시:
```python
assert "llm" not in kinds  # verify collapse
```

**정정**: 어댑터는 pingpong 을 열지 않는다 (강한 표현 유지: "즉시 열지 않는다" 는 시간이 지나면 저절로 열린다는 함의가 있으나 실제로는 탐지기 재설계가 별도로 필요하다). `graph.node.id` 확보는 별개 데이터 축을 준비할 뿐. Pingpong 실데이터 발동은 **detector 재설계** 가 필요하며, 이는 별도 사전등록 대상.

**유력 방향** (§8.2 상세): `collapse_llm_spans` 는 llm 만 제거하고 agent 는 보존하므로, pingpong 을 AGENT 스팬 대상으로 재정의하는 것이 preprocess 를 건드리지 않는 경로다. 별도 사전등록에서 다룬다.

이 정정을 기록으로 남기는 이유: 근거 없이 넘겨짚어 판단한 사례. 코드 확인이 판단에 선행해야 한다는 원칙 (`memory/feedback_thorough_investigation.md`, `feedback_no_hypothetical_case_judgment.md`) 재확인.

---

## §3 — 범위

**이 사전등록의 스코프**:
1. `_kind_of` 매핑 축은 변경 없음 (`_KIND_MAP` 유지).
2. `agent_or_node_id` 매핑을 span_kind 별로 정교화:
   - TOOL: `attrs["tool.name"]` 우선 → 없으면 `s.name`.
   - AGENT: `attrs["graph.node.id"]` 우선 → 없으면 `s.name`.
   - LLM / CHAIN / 그 외: `s.name` 유지 (변경 없음).
3. `output_text` 추출을 방어적 shim 으로 교체 — mime_type + JSON parse fallback + raw fallback 3 겹.
4. Fixture 2개 회귀 락 — LangChain / CrewAI dump 각각.
5. **기존 LangGraph 트레이스 fallback 게이트** — 수정 전/후로 fixture 처리 결과 `(span_id, span_kind, agent_or_node_id)` 집합이 완전 동일해야 함 (§7.1).

**스코프 밖 (§9 에서 재정리)**:
- Pingpong 재설계 (§8).
- OpenAI Agents SDK 동형성 재확인 (별도 dump probe).
- 사용자 정의 도구 매핑 (`clew.yaml`).
- 파일명 rename.

---

## §4 — 매핑 스펙 (frozen)

### §4.1 `_kind_of` — 변경 없음

`_KIND_MAP = {"LLM":"llm", "TOOL":"tool", "CHAIN":"chain", "RUNNABLE":"chain", "AGENT":"agent"}` 그대로.

### §4.2 `agent_or_node_id` — span_kind 별 우선순위

```python
def _agent_or_node_id_of(span_kind: SpanKind, span_name: str, attrs: dict[str, Any]) -> str:
    """OpenInference span 에서 Clew 의 agent_or_node_id 추출.

    우선순위 (span_kind 별):
      tool   → attrs["tool.name"] → span_name → "anonymous"
      agent  → attrs["graph.node.id"] → span_name → "anonymous"
      llm    → span_name → "anonymous"   (변경 없음)
      chain  → span_name → "anonymous"   (변경 없음)

    fallback 로 span_name 을 유지하는 이유:
      기존 LangGraph fixture 는 tool.name · graph.node.id 를 안 실을 수 있음.
      fallback 이 있어야 out-of-band 동작 보존.
    """
```

**pingpong 이 요구하는 A ≠ B 판정에 미치는 영향**:
- Pingpong 은 LLM span 대상 → LLM 매핑 유지 결정과 정합.
- AGENT span 대상 재설계 시에는 `graph.node.id` 로 A ≠ B 판정 가능 (§8 참조).

**§5 게이트 실패 시 대응 (사전 확정)**: §5.2 참조. LangGraph 트레이스에도 `graph.node.id` 가 존재해 매핑 결과가 바뀌면 source 판별로 분기해 LangGraph 경로는 기존 매핑을 유지한다. 결과 보고 정하지 않는다.

### §4.3 `output_text` 추출 shim

```python
def _extract_tool_output(attrs: dict[str, Any]) -> str:
    """OpenInference span 의 output.value 에서 도구 반환 원문 추출.

    관측 사례 (langchain_dump.md §2, crewai_dump.md §2):
      - LangChain: mime "application/json", value = {"type":"tool","data":{"content":"<원문>"}}
      - CrewAI:    mime "text/plain",       value = "<원문>"

    실패 방향은 안전 (false negative, 잘못 잡는 쪽 아님):
      envelope 를 못 벗기면 raw 그대로 → 두 호출이 같은 raw 면 cascade 는
      그대로 waste 판정. 다른 raw 면 waste 아님. 관측 유지.
    """
    raw = attrs.get("output.value", "")
    if not isinstance(raw, str):
        return str(raw) if raw is not None else ""
    mime = attrs.get("output.mime_type", "")

    if mime == "text/plain":
        return raw

    if mime == "application/json":
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if (
            isinstance(obj, dict)
            and obj.get("type") == "tool"
            and isinstance(obj.get("data"), dict)
            and "content" in obj["data"]
        ):
            content = obj["data"]["content"]
            return str(content) if not isinstance(content, str) else content
        return raw

    return raw
```

**적용 지점**: `otel_spans_to_trace` 안의 `output_text = _coerce_text(attrs.get("output.value"))` 를 `output_text = _extract_tool_output(attrs) if _kind_of(attrs) == "tool" else _coerce_text(attrs.get("output.value"))` 로 교체. **TOOL 이 아닌 span 의 output 추출은 변경 없음.**

### §4.4 `input_text` — 변경 없음

`input_text = _coerce_text(attrs.get("input.value"))` 그대로. LangChain 은 raw 문자열, CrewAI 는 JSON 문자열. 두 형식 모두 `_normalize_input` 이 strip + casefold 로 처리하므로 subgroup key 매칭에 무리 없음. 정규화 강화는 데이터 축 별개 사전등록 대상.

---

## §5 — 게이트: 기존 LangGraph fixture 무영향 (필수)

`§4.2` 매핑 우선순위 변경이 기존 트레이스 동작을 보존하는지 실증 필수.

### §5.1 게이트 사양

- 기존 `tests/test_otel_json_ingest.py::MINIMAL_SDK_JSON` fixture (LangGraph pipeline / researcher / claude 스팬) 를 수정 전 · 후 두 버전으로 ingest.
- 두 Trace 의 span 집합 `(span_id, span_kind, agent_or_node_id)` 이 **완전 동일** 해야 통과.

### §5.2 실패 시 대응 (사전 확정)

**★ 결과 보고 정하지 않는다. 아래 대응을 지금 사전등록에 확정한다.**

- 게이트 실패 시나리오 = LangGraph 트레이스에도 `graph.node.id` 가 존재해 새 매핑이 기존 결과를 바꾸는 경우.
- 대응: **기존 동작 보존을 채택** (option (가)). `otel_spans_to_trace` 안에서 source 판별로 분기해 LangGraph 경로는 기존 매핑 (`s.name` 우선) 을 유지한다.
- 근거: 이번 스코프는 CrewAI/LangChain 지원이지 기존 매핑 개선이 아니다. 기존 결과가 바뀌면 그것이 개선인지 회귀인지 판정할 근거가 없다. 매핑 개선은 별도 사전등록에서 다룬다 (§9 참조).
- **판별식 선택은 구현 시 실측 판단**. 사전등록이 막는 것은 판정 기준을 결과 보고 바꾸는 것이다. 대응(기존 동작 보존)은 이미 확정됐고, 어느 필드로 분기하느냐는 구현 세부다. 게이트 자체가 판별식의 검증이므로 자기교정된다.
- 단 다음 제약은 사전등록에 명시:
  - **★ `graph.node.id` 는 판별식으로 사용 불가** — 게이트 실패 조건 자체가 그 필드가 LangGraph 트레이스에도 존재하는 것이므로 순환.
  - 판별식 선택의 통과 조건은 **§5.1 게이트** (기존 LangGraph fixture 출력 `(span_id, span_kind, agent_or_node_id)` 집합 완전 동일).
  - 게이트 통과 없이는 어댑터 매핑 변경 merge 금지.
- 실측 후보 (참고, 확정 아님): OTel resource attribute `service.name`, span attribute `crew_id` 등 실패 시나리오와 독립인 필드.

### §5.3 신규 테스트

```python
def test_langgraph_fixture_stable_under_new_mapping(tmp_path):
    """§5.1 gate: existing LangGraph fixture must produce byte-identical
    (span_id, span_kind, agent_or_node_id) set under the new mapping."""
    from clew.ingest.otel_json import ingest_from_otel_json
    p = tmp_path / "trace.json"
    p.write_text(json.dumps(MINIMAL_SDK_JSON), encoding="utf-8")
    trace = ingest_from_otel_json(p)
    observed = {(s.span_id, s.span_kind, s.agent_or_node_id) for s in trace.spans}
    expected = <frozen from pre-change run>
    assert observed == expected
```

`expected` 는 수정 전 코드로 한 번 돌려 캡처 → literal 로 락.

---

## §6 — Frozen 축 (모두 무변)

새 어댑터 매핑이 **직접 영향을 주는 지점** 은 OpenInference JSON 을 통해 들어오는 트레이스뿐. 기존 Toolathlon (`src/clew/ingest/toolathlon.py`) 와 Claude Code (`src/clew/ingest/claude_code.py`) 는 langgraph.py 를 경유하지 않는다 (실측: `grep "langgraph"` 결과 두 파일에 references 없음). 따라서:

- `waste_span_ids` sha256 (`cand=5c0c94d6…`, `pair=742b51a7…`) — **불변 게이트**.
- `between_window_counts` (`declarative`, `no_side_effect`, `payload_dependent`, `targeted_writes`, `high_volume` 5 카운트) — **불변 게이트**.
- `coverage_stats` (6 필드 전체 — `unique_tools_in_trace`, `recognized_tools`, `coverage_ratio`, `idempotent_pairs_total`, `pairs_with_unrecognized_in_between`, `unrecognized_tool_names`) — **불변 게이트**.
- `id_bridge_candidates` — **불변 게이트**.

**모든 게이트는 `field_test/diagnostics/greyzone_expansion_baseline.py` 재실행 + 전체 pytest 통과로 확증**.

---

## §7 — Fixture 락

### §7.1 두 신규 fixture

- `tests/fixtures/openinference_langchain.json` — 본 사전등록 근거 dump.
  Source: `field_test/diagnostics/langchain_dump_openinference.json`. 개인정보 · 로컬 경로 없는지 정리 후 commit.
- `tests/fixtures/openinference_crewai.json` — 본 사전등록 근거 dump.
  Source: `field_test/diagnostics/crewai_dump_openinference.json`. 동일 정리.

### §7.2 회귀 테스트 (신규)

```python
def test_ingest_openinference_langchain_fixture():
    trace = ingest_from_otel_json(FIXTURE_LC)
    # (a) 스키마
    tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
    assert all(s.agent_or_node_id == "search_web" for s in tool_spans)  # tool.name 반영
    # (b) 봉투 unwrap
    assert all("Result 1:" in s.output_text for s in tool_spans)         # data.content
    assert all("tool_call_id" not in s.output_text for s in tool_spans)  # envelope 벗겨짐
    # (c) 두 호출 sha256 동일 → cascade 통과 가능
    outs = sorted(s.output_text for s in tool_spans)
    assert hashlib.sha256(outs[0].encode()).digest() == hashlib.sha256(outs[1].encode()).digest()


def test_ingest_openinference_crewai_fixture():
    trace = ingest_from_otel_json(FIXTURE_CA)
    tool_spans = [s for s in trace.spans if s.span_kind == "tool"]
    agent_spans = [s for s in trace.spans if s.span_kind == "agent"]
    # tool.name 반영
    assert all(s.agent_or_node_id == "search_web" for s in tool_spans)
    # graph.node.id 반영
    agent_ids = {s.agent_or_node_id for s in agent_spans}
    assert agent_ids == {"Web Researcher", "Fact Verifier"}
    # raw output 그대로
    assert all(s.output_text.startswith("Result 1:") for s in tool_spans)
```

### §7.3 fixture sanitize 범위 (frozen)

**제거 대상**:
- 절대 경로 (`C:/Users/User/...` 등) → `/PATH/` placeholder.
- OTel resource attributes: `service.name`, `host.name`, `process.command_line`.
- 자격증명 · API 키 · 실 사용자 email (FakeChatModel 기반이라 없을 것으로 예상하나 **가정이므로 기계 검사 필수**).

**유지 대상 (필수)**:
- 타임스탬프 (`start_time`, `end_time`) — `between_window_counts` 가 요구.
- `openinference.span.kind`, `input.value`, `output.value`, `output.mime_type`, `tool.name`, `graph.node.id`.

**★ 타임스탬프는 유지한다.** 삭제 시 between_window 계산 축이 무너진다.

### §7.4 기계 sanitize 스캔 (필수)

fixture 커밋 전에 아래를 자동 스캔한다. **검출 0건이어도 결과를 사전등록 검증
재료로 함께 보고한다** (검출 0건 = 통과 확증, 미보고 = 확증 없음).

**자격증명 패턴** (grep -Ei):
- `sk-` (OpenAI-style key prefix)
- `Bearer ` (Authorization header)
- `api[_-]?key` (case-insensitive)
- `token=` (query string / env)
- `secret` (환경변수 · 헤더)
- `password`

**OTel resource attributes 전량 나열**:
- fixture JSON 을 파싱해 resource block 내 attribute 를 전부 dump → 육안 확인.
- 근거: OTel exporter endpoint URL 에 토큰이 붙거나 환경변수가 새어 들어가는 경로가 존재.

**절대 경로 패턴** (grep):
- `C:/Users/`, `C:\Users\`
- `/home/`
- `/Users/`

**보고 형식**: `field_test/diagnostics/openinference_fixture_sanitize_scan.md` (uncommitted, 규칙: 진단 스크립트 커밋 금지) 에 각 패턴별 검출 라인 + resource attribute 전량 dump. 검출 0건이면 "0 hits" 명시.

---

## §8 — Pingpong blocker (스코프 밖, 방향만 기록)

### §8.1 왜 어댑터로 안 열리는가

- `preprocess_trace::collapse_llm_spans` 는 LLM span 을 트레이스에서 제거하고 token_count 를 부모 chain 에 rollup.
- `find_pingpong_candidates` 는 4-window 4개 span 전부 `span_kind == "llm"` 을 요구.
- 결과: detector 가 보는 트레이스에 매칭 대상 zero.

### §8.2 유력 방향 — pingpong 을 AGENT 대상으로 재정의

- `collapse_llm_spans` 는 llm 만 제거. agent 는 보존.
- CrewAI dump 에서 AGENT span 은 `graph.node.id` 로 A ≠ B 판정 가능 (실측: `"Web Researcher"` / `"Fact Verifier"`).
- 즉 pingpong 조건을 `span_kind == "agent"` + `agent_or_node_id != ` 로 재정의하면 preprocess 를 안 건드리고 진행 가능.
- **주의**: 이는 detector 스펙 변경. SPEC §22.8.2 재검토 · 별도 사전등록 필요. 이 어댑터 사전등록 스코프 밖.

### §8.3 대안 방향 (참고)

- (b) `collapse_llm_spans` 를 pingpong 시나리오에서 스킵 — preprocess 조건 분기 필요. 복잡.
- (c) AGENT ancestor 정보를 tool/chain span 의 새 필드로 저장 — 스키마 변경. Backward compat 부담.

**§8.2 우선 검토**. 별도 사전등록 대상.

---

## §9 — 스코프 밖 · 후속 작업

| 항목 | 위치 | 이유 |
|---|---|---|
| OpenAI Agents SDK dump probe | 어댑터 착수 후 fixture 3번째 추가로 병행 | 두 프레임워크 동형 확증됨. 세 번째 게이트 두면 지연 손실 큼 |
| Pingpong 재설계 (§8) | 별도 사전등록 | Detector 스펙 변경 · preprocess 상호작용 검토 필요 |
| 사용자 정의 도구 매핑 (`clew.yaml`) | 별도 작업 | 어댑터가 열리면 커버리지 0% 문제 심화 (사용자 정의 도구가 매핑에 없음). UX 설계 별도 |
| 파일명 rename (`langgraph.py` → 정확한 이름) | 백로그 | Import · test churn 큼. 커버리지가 실제 CrewAI/AutoGen 로 확장된 후 판단 |
| Reddit · Slack 알림 통합 | 별도 사전등록 | 웹앱 방향과 연결 |
| LangChain 내장 dedup middleware 모니터링 (#38708) | 지속 관찰 | 프레임워크가 provable duplicate 를 흡수하면 Clew 각도 축소 |

---

## §10 — 검증 게이트

**① 무영향 축** (§6):
- `waste_span_ids` sha256 baseline 재현 (`greyzone_expansion_baseline.py`).
- `between_window_counts` 무변.
- `coverage_stats` 6 필드 무변.
- `id_bridge_candidates` 무변.

**② §5 fixture 무영향 게이트**:
- 기존 LangGraph fixture 를 수정 전 · 후 처리 결과 `(span_id, span_kind, agent_or_node_id)` 집합 완전 동일.

**③ 신규 fixture 회귀** (§7.2):
- LangChain / CrewAI fixture 각각 스키마 · 봉투 · sha256 정합.

**④ 문면 게이트**:
- 금지어 7종 + `provable` 미사용 유지.

**⑤ 전체 pytest 통과**:
- 기존 288 tests + 신규 3~5 tests. 실패 zero.

---

## §11 — 커밋 체인 (Rule 8)

승인 후 4 커밋 체인:
1. `docs(prereg): openinference adapter — mapping + shim` — 본 문서 확정판 (판정 반영).
2. `feat(ingest): agent_or_node_id per span_kind + defensive output shim` — `src/clew/ingest/langgraph.py` 수정 만.
3. `test(ingest): fixture regression + backward compat gate` — `tests/fixtures/openinference_{langchain,crewai}.json` 추가 + §5.3 + §7.2 신규 테스트.
4. `docs(readme): openinference framework coverage` — README 에 OpenInference 로 커버하는 프레임워크 목록과 검증 상태 (LangChain · CrewAI 두 개 확증, 나머지 26개는 추정) 서브섹션 추가.

**4 커밋 유지 근거**: README 가 현재 "프레임워크별 실측 검증은 진행 중" 으로 hedge 중. LangChain · CrewAI 실측 후 미갱신 시 낡은 채 남음. v0.3.2 · (b-2-1) 에서 README 낡음 사고 두 번 재발 이력.

**★ 판정 없이 코드 작성 금지.** 이 draft 는 사전등록 · 판정 재료 제출까지.

---

## §12 — 참조

- `field_test/diagnostics/langchain_dump.md` (2026-07-31 실측).
- `field_test/diagnostics/crewai_dump.md` (2026-07-31 실측).
- `src/clew/ingest/langgraph.py` — 기존 어댑터.
- `src/clew/ingest/otel_json.py` — dumped JSON 어댑터.
- `src/clew/ingest/preprocess.py::collapse_llm_spans` — §8 blocker 근거.
- `src/clew/detect/structural.py::find_pingpong_candidates` — pingpong 요구 조건.
- `docs/COVERAGE_TRANSPARENCY_PREREG.md` — coverage_stats 축.
- `docs/ID_BRIDGE_PRODUCTION_PREREG.md` — waste_span_ids sha256 baseline.
- `docs/ID_BRIDGE_SCOPE_PRINCIPLE.md` — 매핑 확대 원칙 (사용자 정의 도구 확대 시 참조).
- `memory/feedback_thorough_investigation.md` — 코드 확인 선행 원칙.
- `memory/feedback_dump_before_shim.md` — dump-first 원칙.
- `memory/feedback_no_hypothetical_case_judgment.md` — §2 정정 근거.
