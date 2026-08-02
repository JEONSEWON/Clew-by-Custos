# OpenInference judgment axes — Revision Pre-registration (2026-08-01, DRAFT)

**작성 시각 (UTC)**: 2026-08-01T00:00:00Z
**HEAD 기준**: `main @ 51a02f9` — Part 2 (ADAPTER_R2_RELAXATION_PART2, PR #61) merge 이후 컷.
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**상태**: **DRAFT — 커밋 전 확인. 구현 금지. Tier 2 시작 금지.**

**선행**:
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (`0b619c5`, PR #53 merge `009be0c`) — Tier 1 사전등록. §2.1 R2 문면이 사후 코드 완화와 어긋난 원본.
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` — Tier 1 결과 리포트. §3 에서 R2 스펙 비정합을 이미 자기공개.
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` (Part 1) — model.py 검증기 · cascade non-tool skip 완화.
- `docs/ADAPTER_R2_RELAXATION_PART2_PREREG.md` (Part 2) — `langgraph.py:169` empty-check 제거. **§12 선례** (Part 1 문면 오류를 별건 사후 문서로만 정정).
- `field_test/diagnostics/framework_probe_anthropic_wrapped.py` — [2] Anthropic OTel context propagation 실측.

---

## §0 — 이 사전등록이 하는 것 · 하지 않는 것

**하는 것.**
- Tier 1 §2.1 R2 문면을 **Part 1/2 완화 후 코드에 정합하도록 개정.** 개정은 이 새 문서에서 확정하고, Tier 1 원 문서는 사후 수정하지 않는다.
- **R1 / R3 / R4 / R5 도 같은 종류의 검사** — 사전등록 문면 vs OpenInference 스펙 vs 실제 코드 요구. 어긋나면 개정안 · R5 는 확인·기록만.
- Part 2 재판정 (T1.2 · T1.4 PASS) 이 개정된 R2 기준으로도 유지되는지 소급 정합 확인 · 결과 리포트에 근거를 남기는 방식 확정.
- Anthropic 표기 결정 — "지원 목록에 넣지 않음" 유지 · 사용 안내 별건으로 명시.
- Tier 2 는 이 개정된 축으로 판정한다는 것을 명시.

**하지 않는 것.**
- Tier 1 사전등록 · Part 1 · Part 2 원 문서 사후 수정 (Part 2 §12 선례 준수).
- 코드 변경 일체 — 이번 사전등록은 **기준 문서 개정만**.
- **R5 실제 개정** — 이 사전등록에서는 확인·기록. 개정하려면 별건.
- Tier 2 조사 실행 · 새 프레임워크 probe.
- 어댑터 · preprocess · cascade · id_bridge 로직 변경.
- `waste_span_ids` / `between_window` / `id_bridge` / `manifest sha` 값 변화 — 이번 커밋은 기준 문서만이므로 원리적으로 무변.

---

## §1 — 배경 · 이미 발생한 모순

### §1.1 R2 문면과 코드의 어긋남 (사실)

**Tier 1 §2.1 R2 원 문면**: "`output.value` 존재 · 비어있지 않음 (strip 후 len ≥ 1)".

**Part 1/2 이후 현재 코드**:
- `src/clew/model.py:80-93` — `_output_text_non_empty_on_tool` 는 **tool span 만** non-empty 요구. 비-tool span 은 빈 값 허용.
- `src/clew/detect/cascade.py:66-73` — non-tool 분기가 빈 output 을 skip. 판정 대상에서 제외하지만 어댑터가 예외를 던지진 않음.
- `src/clew/ingest/langgraph.py:169-173` — Part 2 로 삭제됨. Format A 어댑터가 non-tool 빈 span 을 통과시킴.

즉 R2 문면은 "존재 · 비어있지 않음" 인데, 코드는 "tool 만 non-empty, 비-tool 은 허용" 이다.

### §1.2 이미 발생한 실질적 모순

Tier 1 결과 리포트 §1.1 Part 2 재판정:
- **T1.2 OpenAI Agents (Runner)**: PASS 판정. 그러나 dump 에 **1 pair 의 empty side non-tool candidate** 존재 (§1.2 Part 1 §11.4 미확증 축 해소).
- **T1.4 AutoGen**: PASS 판정. 그러나 dump 에 **2 pair 의 empty side non-tool candidate** 존재.

Tier 1 §2.1 R2 문면 그대로 읽으면 두 케이스 모두 FAIL 이어야 한다. Part 2 는 결론적으로 옳지만 **판정 근거가 사전등록 문서에 없다.**

### §1.3 사후 수정 금지 원칙 (Part 2 §12 선례)

Part 2 §12 는 Part 1 §2.4 근거 문면 오류 ("structural invariant: a tool call with no output is invalid data" — PageDownTool 실측으로 반증) 를 **Part 2 문서 안에서만 정정**했다. Part 1 문서 자체는 사후 수정하지 않았다.

이 사전등록도 같은 방식 — Tier 1 § 2.1 을 이 문서 안에서 개정하고, Tier 1 원 문서는 사후 수정하지 않는다.

### §1.4 [2] Anthropic 실측이 R5 에 대해 드러낸 사실

`field_test/diagnostics/framework_probe_anthropic_wrapped.py` 실측 (2026-08-01):

| 조건 | trace_id 개수 | root 개수 | R5 (adapter) | TOOL span |
|---|---|---|---|---|
| instrumentor 만 (T1.3 원본) | 3 | 3 | FAIL | 0 (#3392) |
| `start_as_current_span` wrap + 수동 tool 계측 | 1 | 1 | PASS | 2 (수동) |

**관찰**: wrap 하면 R5 통과. 하지만 그건 프레임워크가 R5 를 만족시킨 게 아니라 **사용자 code 가 OTel context 를 만들어준 결과**. 이건 모든 OTel 트레이스에 해당하는 말이며 프레임워크 지원 목록의 근거로 쓸 수 없다 (§4 참조).

---

## §2 — ★ R2 개정

### §2.1 새 문면 (개정 후)

Tier 1 §2.1 R2 를 다음으로 **대체** (이 문서 안에서만 대체 · Tier 1 원 문서 수정 금지):

> | # | 축 | 조건 | 근거 |
> |---|---|---|---|
> | R2 | `output.value` | **tool span 에서 존재 · strip 후 len ≥ 1.** 비-tool span (chain/agent/llm) 은 부재/빈 값 허용. | `Span._output_text_non_empty_on_tool` 검증기 (`model.py:80-93`, `ADAPTER_R2_RELAXATION_PREREG.md` Part 1 §2.4-2.5). 어댑터 층 empty-check 제거 (`langgraph.py:169-173` Part 2 삭제). cascade 는 비-tool 분기에서 빈 output 을 skip (`cascade.py:66-73`). |

### §2.2 개정 근거 (스펙 · 커밋 인용)

**스펙 근거 (Tier 1 결과 리포트 §3.1 재인용)**:
- OpenInference `spec/semantic_conventions.md` 는 `output.value` 에 대해 MUST/SHOULD 언어 없음. Reserved Attributes 표 등재만.
- 유일한 필수 속성은 `openinference.span.kind` ("required for all OpenInference spans").
- 즉 원 R2 문면은 **스펙보다 엄격했다**.

**커밋 근거 (Part 1/2)**:
- Part 1 (`421bfbf` + `65ca396`) — `_output_text_non_empty` field validator 를 `_output_text_non_empty_on_tool` model validator 로 축소. cascade 비-tool skip 추가.
- Part 2 (Part 2 merge commit, TBD) — `langgraph.py:169-173` any-kind empty-check 완전 제거.

### §2.3 개정 후 코드 정합성 (재확인)

| 지점 | 개정 R2 문면과 코드 일치 여부 |
|---|---|
| `model.py:80-93` `_output_text_non_empty_on_tool` | ✓ 일치 (tool 만 non-empty) |
| `cascade.py:66-73` non-tool 빈 skip | ✓ 일치 (판정에 넣지 않음) |
| `langgraph.py:169-173` (Part 2 삭제) | ✓ 일치 (empty non-tool 통과) |
| `otel_json.py:239-254` (Format C `warn+skip`) | **부분 일치** — Format C 는 여전히 빈 output.value OI span 을 스킵 (any-kind). R2 개정 문면 그대로면 tool 은 skip 되어야 하지 않고 raise 되어야 한다. **Part 3 이월** (§8 범위 밖 참조). |

**★ 결론**: 개정된 R2 는 Format A 어댑터 경로 (Part 1/2 대상) 와 완전 정합. Format C 경로는 Part 3 대상 · 이번 개정 범위 밖.

---

## §3 — ★ R1 / R3 / R4 / R5 재확인

각 축에 대해 (a) 사전등록 문면, (b) 근거가 스펙인가 코드인가, (c) 코드가 실제로 무엇을 요구하는가, (d) 어긋나면 개정안.

### §3.1 R1 — `openinference.span.kind` (★ 필수 축 유지 · 격하 기각)

- **(a) 사전등록 문면**: "존재 · 값 ∈ {`LLM`, `TOOL`, `CHAIN`, `AGENT`, `RUNNABLE`}".
- **(b) 근거**: **스펙 근거 있음.** OpenInference `spec/semantic_conventions.md` 원문: `openinference.span.kind` 는 "required for all OpenInference spans" — **스펙이 필수로 명시한 유일한 속성**.
- **(c) 코드가 실제로 요구하는 것**:
  - `langgraph.py:62-66` `_kind_of` — **속성이 없거나 알 수 없는 값이면 "chain" 으로 fallback.** 실측 (2026-08-01): `_kind_of({})` → `"chain"`, `_kind_of({"openinference.span.kind": "FOO"})` → `"chain"`.
  - `otel_json.py:227-236` (Format C) — **`openinference.span.kind` 없는 span 을 필터로 제거.** 없으면 raise ("OpenInference 스팬(openinference.span.kind 보유)이 없음").
- **(d) 어긋남 방향 · R2 와의 대칭 비교**:

  | | 스펙 | 우리 문면 | 어긋남 방향 | 조치 |
  |---|---|---|---|---|
  | R2 | optional (MUST/SHOULD 없음) | 필수 | 문면이 스펙보다 엄격 | **문면을 완화** (§2) |
  | R1 | **필수** ("required for all OpenInference spans") | 필수 | 문면·스펙 정합 · **Format A 코드만 관대** | **문면 유지 · 코드 관대함이 문제** |

  방향이 정반대다. R2 는 우리가 과했고, R1 은 스펙과 문면이 맞고 **코드가 스펙 위반 데이터를 조용히 삼키는 것**이 문제.

- **(e) 격하 기각 근거 (실질 손실)**:
  - kind 부재 시 span 종류 구분 불가 → `cascade` 가 tool 분기 (sha256 게이트) 와 non-tool 분기 (φ) 중 어느 쪽을 탈지 결정할 수 없다.
  - Format A fallback 이 전부 "chain" 으로 삼키면 sha256 게이트를 건너뛰고 φ 만 탄다 → **탐지 결과 자체가 무의미**.
  - 판정 축에서 격하하면 이 실질 손실이 판정에 반영되지 않는다.

- **(f) R1 문면 (개정 · 축은 필수 유지)**:

  > | # | 축 | 조건 | 근거 |
  > |---|---|---|---|
  > | R1 | `openinference.span.kind` | 존재 · 값 ∈ {`LLM`, `TOOL`, `CHAIN`, `AGENT`, `RUNNABLE`} | 스펙상 유일한 필수 속성 ("required for all OpenInference spans"). ★ 어댑터 코드는 Format A 에서 부재/미지값을 chain 으로 fallback 하나, 이는 스펙 위반 데이터를 조용히 받는 것이다. 판정 기준은 스펙을 따른다. ★ kind 부재 시 cascade 분기 결정 불가 → 탐지 자체가 무의미. ★ Format A fallback 처리 (경고 또는 거부) 는 별건 (§8). |

- **(g) 별건 이월**: Format A `_kind_of` fallback 을 유지할지 · 경고/거부로 바꿀지는 별건 사전등록. Format C 처럼 raise 하는 방향이 스펙 정합.

### §3.2 R3 — tool span 도구 식별

- **(a) 사전등록 문면**: "`tool.name` attribute 존재 **또는** `span.name` 이 도구명과 일치".
- **(b) 근거**: **우리 코드 관행.** OpenInference 스펙에는 `tool.name` 필수 언명 없음 (Reserved Attributes 표 등재만).
- **(c) 코드가 실제로 요구하는 것**:
  - `langgraph.py:69-88` `_agent_or_node_id_of` — tool span 에서 `attrs["tool.name"]` → `span_name` → `"anonymous"` 3단계 fallback.
  - 즉 **아무것도 없어도 "anonymous" 로 accept.** 어댑터는 raise 하지 않는다.
- **(d) 어긋남 · 개정안**:
  - 원 R3 문면 "존재 또는 span.name 일치" 는 **코드보다 엄격**. 코드는 셋 다 없어도 accept.
  - 그러나 셋 다 없으면 도구별 waste 탐지 실패 (모든 tool 이 `"anonymous"` 로 뭉침 → 오탐/미탐).
  - **판정 축 R3 개정안**: "tool span 에서 `tool.name` 또는 `span_name` 중 하나 이상이 도구를 유일하게 식별. **어댑터는 부재도 accept 하지만, 도구별 판정이 무너진다** — 이 경우 PARTIAL (기능 저하) 로 분류."
  - PARTIAL 사유로 명시 편입 · 근거는 §3.2 Tier 1 원 문면 ("무엇을 못 하게 되는가" 규칙) 그대로.

### §3.3 R4 — timestamp

- **(a) 사전등록 문면**: "`start_time` · `end_time` 존재 · UTC-aware · `end ≥ start`".
- **(b) 근거**: **우리 코드 + OTel 원시 요구.** OTel Span 스펙 자체가 start/end 시각을 요구. OpenInference 는 별도 언명 없음.
- **(c) 코드가 실제로 요구하는 것**:
  - `model.py:53-58` `_tz_aware_utc` — timezone-aware 요구. naive datetime raise.
  - `model.py:74-78` `_end_after_start` — `end < start` raise.
  - `langgraph.py:50-51` `_ns_to_utc` — ns → UTC aware datetime 생성.
- **(d) 어긋남 · 개정안**: **없음.** R4 문면과 코드 · OTel 스펙 모두 일치. **개정 없음.**

### §3.4 R5 — trace/span/parent ID (★ 확인·기록만, 개정 X)

- **(a) 사전등록 문면**: "trace_id · span_id 필수, parent_span_id 는 root 에서 None". 근거 컬럼: "`Trace._validate_tree` 가 요구 (root 1 개, cycle 없음, orphan 없음)".
- **(b) 근거**: **우리 코드 관행.** OTel 은 trace_id/span_id 를 원시 요구. 하지만 "단일 trace_id 당 정확히 1 root" · "한 ingest 호출 = 단일 trace" 는 우리 시스템 경계.
- **(c) 코드가 실제로 요구하는 것**:
  - `langgraph.py:159-163` — spans 의 trace_id 집합 크기 == 1 요구, 아니면 raise.
  - `langgraph.py:201-207` — parent 없는 span 개수 == 1 요구, 아니면 raise (주석: "multi-root traces indicate instrumentation misconfiguration").
  - `model.py:128-132` `Trace._validate_tree` — 루트 개수 == 1 요구.
- **(d) 어긋남 여부 (확인 · 기록만)**:
  - R5 문면 "trace_id/span_id 필수" 는 **OTel 스펙 · OpenInference 스펙 모두 원시 요구** → 일치.
  - "root 1 개" 조건은 **spec 원문에서 정확 대응 문면 확인 못 함**. OTel 트레이스의 실질 관례 (parentless span = root) 는 있으나 "단일 root 강제" 는 아님.
  - "한 ingest 호출 = 단일 trace_id" 는 **우리 어댑터 층 경계** — 스펙에는 없음. OpenInference 는 프레임워크가 여러 독립 trace 를 emit 할 수 있음을 배제하지 않음 (Anthropic 실측 §1.4 근거).
  - **결론**: R5 문면 자체는 스펙과 대체로 정합하되, **근거 컬럼이 시사하는 "single trace + single root" 요구는 우리 어댑터 층 제약**. Anthropic direct SDK 케이스 (§1.4) 가 정확히 이 지점에서 FAIL.
- **★ 이번 사전등록에서는 개정하지 않는다.** 확인 · 기록만.
- **후속 (범위 밖 · §8)**: R5 를 개정하려면 별건 사전등록. 방향은 두 가지 후보:
  - (α) R5 문면을 스펙 정합으로 완화 (multi-trace 허용 · synthetic root 삽입) — Format C 가 이미 이 방향 (`otel_json.py:261-289` synthetic root).
  - (β) R5 유지 · Anthropic 같은 케이스는 사용자 wrap 요구 (사용 안내로 커버) — [2] 실측이 wrap 하면 통과함을 확인.
  - **★ 어느 쪽이든 이번 사전등록 밖.**

### §3.5 R1-R5 재확인 요약

| # | 어긋남 방향 | 이번 개정 여부 |
|---|---|---|
| R1 | 문면·스펙 정합 · Format A 코드가 스펙보다 관대 (chain fallback) | **필수 축 유지** · 코드 fallback 처리는 별건 |
| R2 | 원 문면이 스펙보다 엄격 · Part 1/2 로 코드는 완화됨 | **개정** (§2) |
| R3 | 원 문면이 코드보다 엄격 · fallback 3단계 존재 | PARTIAL 사유로 편입 (기능 저하 규칙) |
| R4 | 정합 | 개정 없음 |
| R5 | 문면은 대체로 정합 · 근거 컬럼이 시사하는 "single trace/root" 는 우리 층 제약 | **확인·기록만** (별건 후속) |

---

## §4 — ★ Part 2 재판정 소급 정합

### §4.1 T1.2 · T1.4 PASS 재확인

개정된 §2 R2 기준 ("tool 만 non-empty, 비-tool 은 부재/빈 값 허용") 으로 Part 2 재판정을 다시 읽으면:

| 프레임워크 | dump 관찰 | 개정 R2 판정 | Part 2 실제 판정 | 정합 여부 |
|---|---|---|---|---|
| T1.2 OA-Runner | non-tool candidate pair 중 1 pair 가 empty side | R2 통과 (비-tool 은 부재 허용) · cascade non-tool skip 발동 | **PASS** | ✓ 정합 |
| T1.4 AutoGen | non-tool candidate pair 중 2 pair 가 empty side | R2 통과 · skip 발동 | **PASS** | ✓ 정합 |
| T1.3 Anthropic | 3 개 별도 trace_id | R2 무관 · R5 FAIL | **FAIL** | ✓ 정합 (R5 지점) |

**결론**: Part 2 재판정은 개정 R2 기준으로도 **완전 유지**. 판정을 바꾸는 게 아니라 근거를 명시하는 정합.

### §4.2 결과 리포트에 근거를 남기는 방식 (★ (b) 채택)

근거는 이 사전등록에서 남긴다:
- 이 문서 §4.1 표 → Tier 1 결과 리포트 §1.1 Part 2 재판정 컬럼과 대조 가능.
- Tier 1 결과 리포트 §3 ("우리 쪽 결함 명시") 이 이미 R2 스펙 비정합을 자기공개했으므로, "결함을 열거만 하고 판정 근거는 어디에 있는지 불분명" 상태를 이 사전등록으로 해소.
- Tier 2 결과 리포트 (별건) 는 개정 R2 기준을 명시 인용해 판정한다.

**★ Tier 1 결과 리포트 처리 방식 — (b) 채택.**

| 방식 | 장점 | 단점 |
|---|---|---|
| (a) Tier 1 결과 리포트 그대로 · 이 사전등록이 references 로 인용됨 | 결과 문서 사후 수정 무 · 참조 체인만 성장 | 독자가 Tier 1 결과만 읽으면 판정 근거 문서를 놓칠 수 있음 |
| **(b) Tier 1 결과 리포트 §3.4 에 "이 결함은 후속 사전등록으로 개정됨 → `OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`" 한 줄 addendum** | 독자가 결과 리포트에서 개정 문서 링크로 즉시 이동 | 결과 리포트 사후 수정 — 판정을 바꾸는 게 아니라 참조만 추가하는 형태로만 허용될 수 있음 |

**★ (b) 채택 근거**:
- §12.4 원칙 ("merge 된 판정 문서 사후 수정 금지") 의 취지는 **틀린 것을 고쳐서 처음부터 맞았던 것처럼 보이게 하지 말라**는 것이다. 참조 링크 한 줄 추가는 여기에 해당하지 않는다.
- (a) 를 택하면 Tier 1 결과 리포트만 읽는 독자가 낡은 기준을 본다. 그것이 더 큰 실질 위험이다.

**★ 단 조건**:
- addendum 은 "이 결함은 후속 사전등록으로 개정됨 → `OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`" **한 줄만**.
- Tier 1 결과 리포트의 **원 문면과 판정은 한 글자도 수정하지 않는다.**
- 위치는 §3.4 (자기공개 결함 목록) 하단. 원 문면 뒤에 addendum 블록으로 부기.

---

## §5 — ★ Anthropic 표기 결정

### §5.1 §4.1 이름 나열 규약과의 정합 확인

Tier 1 §4.1 이 요구하는 것:
- "실측 확인된 이름만 나열".
- **금지**: "여러 프레임워크" · "다양한 프레임워크" · "OpenInference 지원" (이름 병기 없이).

**"실측 확인" 의 정확한 의미**:
- 프레임워크 A 를 OpenInference instrumentor 로 계측 → 그 결과가 우리 어댑터를 통과 → PASS.
- 실측 확인 대상은 **프레임워크 + 그 프레임워크의 공식 instrumentor 조합**.

### §5.2 [2] Anthropic wrap 실측이 무엇을 확인한 것인가

`framework_probe_anthropic_wrapped.py` 실측:
- 사용자 code 가 `tracer.start_as_current_span` 로 wrap + tool 실행을 수동 계측 → R5 PASS · cascade 작동.
- 이 절차는 `openinference-instrumentation-anthropic` 이 없어도 원리적으로 동일 (사용자 code 가 OTel span 을 직접 만들면 우리 어댑터가 읽음).
- 즉 확인된 건 **프레임워크 A 의 instrumentor 조합** 이 아니라 **우리 어댑터의 OTel 일반성**.

**★ 이건 §4.1 의 "실측 확인" 정의를 만족하지 않는다.**
- 프레임워크의 계측 툴체인이 통과한 게 아님.
- 모든 OTel 트레이스에 해당하는 말이라 프레임워크 지원 목록의 근거가 될 수 없음.

### §5.3 지원 목록 표기 결정

**Anthropic 은 지원 목록에 넣지 않는다.**
- Tier 1 결과 리포트 §6.3 문면 유지: "OpenAI Agents SDK · Anthropic (direct SDK) · AutoGen — 현재 이 instrumentor 로는 읽지 못한다."
- Part 2 로 T1.2 · T1.4 는 PASS 로 이동. **Anthropic 만 FAIL 유지** — instrumentor #3392 미해결 (TOOL span 자체 미emit).

### §5.4 README 사용 안내로는 값이 있음 (별건)

Anthropic direct SDK 사용자가 wrap 하면 우리 도구가 읽는다는 사실 자체는 사용 안내로 문서화할 값이 있다:
- **위치 후보**: README "advanced usage" · "framework support caveats" 섹션.
- **내용**: "Anthropic SDK 를 직접 쓰는 경우, `tracer.start_as_current_span('agent_turn')` 로 다중 호출을 감싸고 tool 실행부를 수동 계측하면 우리 도구가 읽습니다. 이는 프레임워크 지원이 아니라 OTel 일반성입니다."
- **명시 필수**: "지원 프레임워크 목록에 넣지 않는 이유" — instrumentor #3392 · TOOL span 미emit.
- **별건 사전등록** — 이번 사전등록 스코프 밖 (§8).

### §5.5 §4.1 규약 재확인

- Anthropic 은 **PASS 목록에 안 들어감** → "N 개 프레임워크에서 실측 확인" 카운트에 미포함.
- "사용 안내" 는 지원 표기가 아니므로 §4.1 이름 나열 규약과 별개 축.
- 카운트는 Tier 1 결과 리포트 §6.1 그대로: **LangChain, CrewAI, LlamaIndex** (3 개). Part 2 로 OpenAI Agents · AutoGen 추가 시 5 개 (Tier 2 결정 시점에서 재확정).

---

## §6 — ★ Tier 2 판정 기준 확정

### §6.1 개정된 축을 Tier 2 판정에 사용

**개정된 §2 R2 · §3.1 R1 (관찰 격하) · §3.2 R3 (PARTIAL 편입) · §3.4 R5 (확인·기록) 로 Tier 2 를 판정한다.**

Tier 2 대상 (Tier 1 사전등록 §5.2 그대로):
- T2.1 Pydantic AI · T2.2 Google GenAI · T2.3 Haystack · T2.4 Smolagents · T2.5 MCP.

### §6.2 Tier 2 결과 리포트 형식

- 별건 사전등록 · 별건 docs 커밋: `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS_TIER2.md` (또는 동등 파일명).
- **개정 축 문면 인용 필수** — R2 새 문면 · R1 관찰 격하 · R3 PARTIAL 규칙 · R5 확인 규칙 모두 이 사전등록 §2/§3 을 references 로 인용.
- Anthropic 표기 규칙 (§5) 준수 — 지원 목록 표기와 사용 안내 표기의 분리 명시.

### §6.3 Tier 2 시작 조건

- 이 사전등록 승인 · 별건 PR · merge 완료 이후.
- **★ 이번 문서는 draft. 승인 전 Tier 2 시작 금지.**

---

## §7 — ★ 불가침

### §7.1 값 무변

- `waste_span_ids sha256`: `cand=5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4`, `pair=742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0`.
- `between_window_counts`: `1226/888/405/248/1024`.
- `id_bridge_candidates`: `differ/same/no_id = 159/76/3197`.
- `eval/set_manifest.json` sha256: `a205a3d62e8310f67f0ab1a7faa957504b9f486a8c5a68cebeadf010aff42952` (2026-08-01 재동결본).
- `coverage_stats` 6 필드.

### §7.2 탐지 로직 · 동결 파라미터

- φ = 0.514345, N = 2, model `paraphrase-multilingual-MiniLM-L12-v2` @ rev `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
- `cascade` / `structural` / `semantic` 로직.
- `_ID_BRIDGE_MAPPING` 26 도구.
- `raw_output_text` fallback 규약 (`_enrich.py::scan_id_bridge_candidates`).

### §7.3 어댑터 · preprocess · 코드 무변

- 이번 사전등록은 **기준 문서 개정만**. `src/clew/*` 어느 파일도 수정하지 않는다.
- Part 1 · Part 2 코드 상태 그대로 유지. 개정된 판정 축은 이미 코드에 정합.

### §7.4 원 문서 사후 수정 금지

- Tier 1 사전등록 · Tier 1 결과 리포트 · Part 1 · Part 2 사전등록 어느 것도 사후 수정하지 않는다.
- 이 사전등록은 새 문서로만 존재하고, 참조 체인으로 원 문서와 연결.

---

## §8 — 범위 밖

| 항목 | 이유 · 후속 |
|---|---|
| R5 실제 개정 (§3.4 α/β 후보) | 별건 사전등록. Anthropic + 다른 multi-trace 프레임워크 사례 축적 후. |
| `otel_json.py:241` (Format C `warn+skip`) R2 정합 | Part 3 이월 (Part 2 §13 참조). |
| Format A · Format C 경로 이질성 통합 (R1) | 별건. Format A 도 `openinference.span.kind` 없는 span 을 필터할지 결정 필요. |
| Tier 2 조사 실행 | 이 사전등록 승인 · merge 후. |
| 어댑터 · preprocess · cascade 코드 변경 | 이번은 기준 문서만. |
| README Anthropic 사용 안내 반영 (§5.4) | 별건 사전등록 · 별건 PR. |
| Tier 1 결과 리포트 §3.4 addendum (§4.2 방식 (b)) | 승인자 판단. draft 단계에서는 (a) 기본. |
| 새 프레임워크 fixture 추가 | 프레임워크당 별건 (LangChain · CrewAI 선례). |

---

## §9 — 산출물

### §9.1 이번 사전등록 커밋 (승인 후)

- **이 파일** (`docs/OPENINFERENCE_JUDGMENT_AXES_REVISION_PREREG.md`).
- 코드·테스트 변경 없음. **docs-only commit.**
- Rule 8 — 별건 branch (`prereg/judgment-axes-revision` 등) · PR 개설은 승인자 · merge commit.
- 사용자 승인 전 커밋 금지.

### §9.2 이번 사전등록이 만드는 것이 아닌 것

- Tier 2 실행 스크립트 · dump — 다음 단계에서 별건.
- 어댑터 shim · 코드 fix — 별건.
- Tier 1 결과 리포트 addendum — 승인자 판단 (§4.2).

### §9.3 승인 후 이어질 작업 순서 (제안)

1. 이 사전등록 merge → 개정 축 확정.
2. (선택) Tier 1 결과 리포트 addendum (§4.2 (b) 방식) — 별건.
3. Tier 2 실행 → 결과 리포트 (별건 사전등록 · 별건 PR).
4. (별건) R5 개정 방향 판단 (§8).
5. (별건) README Anthropic 사용 안내 (§5.4).

---

## §10 — 확인 질의 (승인자 확정 답 기록)

| # | 질의 | 확정 답 |
|---|---|---|
| Q1 | §2 R2 새 문면 문안 확정 여부 | **동의** — 위 §2.1 표 그대로 |
| Q2 | §3.1 R1 을 판정 축에서 관찰 축으로 격하 · 경로 이질성은 별건 처리 | **★ 격하 기각 · 필수 축 유지** — R1 은 스펙상 유일한 필수 속성 ("required for all OpenInference spans"). R2 는 스펙 optional 을 우리가 필수로 요구해 틀린 반면, R1 은 스펙 필수 · 문면 필수로 정합. 틀린 것은 Format A 코드 (스펙 위반 데이터를 chain 으로 조용히 삼킴). 격하하면 실질 손실 — kind 부재 시 cascade 분기 (sha256 vs φ) 결정 불가 → 탐지 무의미. Format A fallback 처리는 별건 (§8). §3.1 (f) 문면 채택. |
| Q3 | §3.2 R3 을 PARTIAL 사유로 편입 · 기능 저하 규칙 그대로 | **동의** — PARTIAL 편입 |
| Q4 | §3.4 R5 확인·기록만 · 개정은 별건 | **동의** — 이번 개정 X · 별건 |
| Q5 | §4.2 Tier 1 결과 리포트 처리 방식 (a) vs (b) | **★ (b) 채택** — §12.4 원칙 취지는 "틀린 것을 고쳐서 처음부터 맞았던 것처럼 보이게 하지 말라". 참조 링크 한 줄 추가는 여기에 해당 안 함. (a) 면 Tier 1 결과 리포트만 읽는 독자가 낡은 기준을 봄 — 더 큰 위험. 단 조건: addendum 은 "이 결함은 후속 사전등록으로 개정됨 → <문서명>" 한 줄만. 원 문면·판정은 한 글자도 수정 X. |
| Q6 | §5.3 Anthropic 지원 목록 배제 · §5.4 사용 안내 별건 | **동의** — 배제 + 사용 안내 별건 |
| Q7 | §6 Tier 2 는 개정된 축으로만 판정 | **동의** — 개정된 축 |

---

## §11 — 참조

### 사전등록 · 결과 리포트
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` (`0b619c5`, PR #53 merge `009be0c`) — Tier 1 원 §2.1 R2.
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` — §3 자기공개 · §1.1 Part 2 재판정 대조.
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` (Part 1) — model.py + cascade 완화.
- `docs/ADAPTER_R2_RELAXATION_PART2_PREREG.md` (Part 2) — `langgraph.py:169` 삭제 · §12 문면 오류 사후 정정 선례.

### 코드
- `src/clew/model.py:80-93` — `_output_text_non_empty_on_tool` (개정 R2 근거).
- `src/clew/detect/cascade.py:66-73` — non-tool 빈 skip.
- `src/clew/ingest/langgraph.py:62-66` — `_kind_of` (R1 Format A 관대).
- `src/clew/ingest/langgraph.py:69-88` — `_agent_or_node_id_of` (R3 fallback).
- `src/clew/ingest/langgraph.py:159-207` — R5 single trace + single root 어댑터 층 강제.
- `src/clew/ingest/otel_json.py:227-236` — R1 Format C 필터 (스펙 정합).
- `src/clew/ingest/otel_json.py:239-254` — R2 Format C `warn+skip` (Part 3 대상).
- `src/clew/ingest/otel_json.py:261-289` — R5 Format C synthetic root (관찰).
- `src/clew/model.py:113-150` — `Trace._validate_tree` (R5 근거 원 문면 인용).

### 실측
- `field_test/diagnostics/framework_probe_anthropic.py` (T1.3 원본).
- `field_test/diagnostics/framework_probe_anthropic_wrapped.py` (2026-08-01, [2] wrap 실측).
- Tier 1 dump 5 종 (`field_test/diagnostics/framework_expansion_dumps/`, 로컬).

### OpenInference 스펙 (§3 검증 앵커)
- [spec/semantic_conventions.md](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md) — `openinference.span.kind` 필수 · `output.value` MUST/SHOULD 없음.
- [python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py](https://github.com/Arize-ai/openinference/blob/main/python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py) — `OUTPUT_VALUE` docstring 없음.
- [Phoenix — Using Tracing Helpers](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/instrument) — 수동 계측 사례 존재 (자동 계측이 output 을 안 채우는 경우 전제).

### Upstream 이슈 (§5 근거)
- [openinference/#3392](https://github.com/Arize-ai/openinference/issues/3392) — Anthropic tool helpers 미계측 (open enhancement).
- [openinference/#3337](https://github.com/Arize-ai/openinference/issues/3337) — OpenAI Agents parent AGENT/CHAIN output 미채움 (open bug, Part 2 로 우리 쪽 대응 완료).

### Memory
- `memory/feedback_prereg_vs_local_design.md` — docs/ vs 로컬 정책.
- `memory/feedback_frozen_absolutes.md` — 동결 문서 절대값 규약.
- `memory/feedback_single_source.md` — 사실 단일 출처 원칙.

---

**★ 이 문서는 DRAFT. 승인자 확인 · 질의 Q1-Q7 답변 후 최종 문안 확정 · 커밋.**
