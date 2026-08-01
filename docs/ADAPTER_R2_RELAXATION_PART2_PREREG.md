# Adapter R2 Relaxation — Part 2 Pre-registration (2026-08-01)

**작성 시각 (UTC)**: 2026-08-01T00:00:00Z
**HEAD 해시**: `main @ db94565` (Merge PR #58 `prereg/r2-relaxation` merged) 기준으로 컷. Part 1 fix 브랜치 `feat/r2-relaxation` (commits `421bfbf` + `65ca396`) merge 후 컷 예정.
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**선행**:
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` (Part 1) — model.py:88 + cascade.py:73 완화 · §11 verdict 채움.
- Part 1 §11.5 후속: Part 2 필요성 명시.
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` §3 — R2 원 자기공개.

---

## §0 — 이 사전등록이 하는 것 · 하지 않는 것

**★ 스코프 축소 (draft 재검토 후 확정)**: Part 2 는 게이트 **하나** (`langgraph.py:169` · Format A 경로) 만 다룬다. `otel_json.py:241` (Format C 전용) 은 **Part 3 로 이월** (§13 참조).

축소 근거는 §2.3 실측 [5] 결과:
- TRAIL 실 데이터에서 빈 output.value OI span 12 개 중 **TOOL 6 개** (`PageDownTool` × 5 · `FinalAnswerTool` × 1).
- `otel_json.py:241` 완화 시 이 6 개가 Part 1 이 유지한 tool-only Span validator raise 를 유발 → 트레이스 전체 실패.
- 이건 원 커밋 `14451e18` 이 `warn+skip` 을 선택한 정확히 그 시나리오를 재현.
- 4번을 어떻게 다룰지는 Part 1 (b'-넓게) 를 함께 열어야 정합. Part 3 대상.

**하는 것.**
- `src/clew/ingest/langgraph.py:169-173` 어댑터 층 empty-check 를 완전 제거 · Format A 어댑터 경로에서 non-tool 빈 span 을 파이프라인에 통과시킴.
- Part 1 §2.1 원칙 ("부재는 판정 대상이 아니다") 을 어댑터 층으로 이어받음 (새 원칙 만들지 않음).
- **결과 보기 전에** 범위 · 완화 방식 · downstream 예측 · KILL 임계 · 재판정 절차 확정.
- Part 1 skip 로직이 **실 데이터에서 처음으로 발동하는지** 확증 (Part 1 §11.4 미확증 축).
- T1.2 · T1.4 재판정 (Part 1 §11.3 미달 목표) — 두 케이스 다 Format A 어댑터 경로.
- **★ Part 1 §2.4 근거 문면 오류를 이 문서 §12 에 기록** (Part 1 결정 자체는 유지 · 근거만 정정).

**하지 않는 것.**
- **`otel_json.py:241` 완화 — Part 3 로 이월** (§13).
- **Part 1 문서 사후 수정** — merge 된 판정 문서는 사후 수정하지 않는다. 근거 정정은 이 Part 2 문서 §12 에만 기록.
- Tier 2 조사.
- 리포트에 빈 span 을 표시할 문면 개선 (별건 · §7).
- `extract_output_text` leaf 선택 규칙 재설계 (별건).
- 어댑터 신설 · shim 확장.
- 웹앱 · README 갱신 (재판정 결과 확정 후 별건).

---

## §1 — 배경 · Part 1 유산

### §1.1 Part 1 verdict 요약

Part 1 은 `Span._output_text_non_empty` field validator + `cascade.py:66` non-tool 분기 앞 skip 두 지점 완화. 결과:
- §4 KILL 6축 전부 통과 (waste_span_ids · between_window · id_bridge · manifest sha · dev-7 FPR 0.0 · pytest).
- §3 예측 전부 일치.
- **★ §5 재판정 미달** — T1.2 / T1.4 는 여전히 FAIL. 원인: 어댑터 층 세 번째 게이트 `langgraph.py:169-173`.
- **★ §11.4 실측**: 빈 non-tool span 카운트 (dev-7 480 / Toolathlon 183,050 / CC 356) **전부 0**. 완화가 실 데이터에서 발동한 적 없음. Part 1 skip 유효성은 3 개 합성 test 만이 보장.

### §1.2 Part 2 필요성

- **본질적 필요**: T1.2 · T1.4 재판정 목표 미달 상태. R2 완화 취지가 어댑터 층 게이트 때문에 실현되지 않음.
- **부수 이득**: Part 1 skip 이 실 데이터에서 처음 발동하는지 확증 · Part 1 §11.4 미확증 축 해소.

### §1.3 ★ [W] 전수 조사로 파악한 대상 (Part 1 은 놓친 것)

Part 1 사전등록의 실수는 게이트 하나 (`langgraph.py:169`) 를 놓친 것. Part 2 는 이 실수를 반복하지 않기 위해 커밋 전에 R2 관련 게이트를 전수 조사했다.

| # | 위치 | 동작 | 상태 |
|---|---|---|---|
| 1 | `src/clew/model.py:88` | tool 만 non-empty `raise` (Span field validator) | Part 1 완료 |
| 2 | `src/clew/detect/cascade.py:73` | non-tool 분기 진입 전 skip | Part 1 완료 |
| 3 | `src/clew/ingest/langgraph.py:169` | any-kind `raise` — 트레이스 전체 ingest 실패 | **★ Part 2 대상** |
| 4 | `src/clew/ingest/otel_json.py:241` | Format C 진입 시 빈 output.value span `warn + skip` | **★ Part 2 대상 (Part 1 조사 시 미확인 지점)** |

**참고 (R2 무관 · 조사에서 배제)**:
- `report/_enrich.py:572, 621` — id_bridge unwrap · extract 의 빈 body early return. Pool 이 tool 만이라 R2 무관.
- `cost/amplification.py:131` — token 추정 skip. 리포트 층, R2 게이트 아님.

### §1.4 3번 · 4번의 성격 차이 (★ Part 2 실질 결정 지점)

| 축 | 3번 `langgraph.py:169` | 4번 `otel_json.py:241` |
|---|---|---|
| 동작 | `raise ValueError` | `warnings.warn` + span 제거 |
| 파급 | **트레이스 전체 ingest 실패** — 사용자는 즉시 알아챈다 (시끄러움) | **그 span 만 조용히 사라짐** — 사용자는 span 이 빠진 걸 모른다 (조용함) |
| 도입 커밋 | `0fa25e0` "Stage 1: data foundation + validation harness (frozen)" (2026-06-06) | `14451e18` "stage14: Format C (OpenInference/TRAIL) ingest" (2026-07-10) |
| 도입 근거 기록 | **없음** — 주석 · 커밋 메시지 · 설계 문서 어디에도 Span 검증기와 중복으로 둔 이유 없음. Part 1 §11.5 조사 결과. | **있음** — 커밋 메시지: "TRAIL real data 에 output.value 없는 OI span 이 실제로 있어서" (raise 대신 warn+skip 선택). |
| 특이점 | 51ac87e2 (2026-07-31) 에서 바로 위 아래 라인 (165-168) 을 손댔지만 169-173 은 안 건드림. 인식 못 했거나 인식했어도 기록 없음. | fee3f6c9 (2026-07-19) 에서 주석만 영어로 번역. 로직 무변. |

**★ 조용한 쪽이 더 위험하다** — 사용자가 span 이 빠진 걸 모르는 상태에서 waste 리포트가 나온다. 4 번 (skip) 을 어떻게 다룰지가 Part 2 의 실질 결정.

---

## §2 — ★ 완화 방식 · 결과 보기 전 확정 (Part 1 §2.1 원칙 이어받음)

### §2.1 원칙 (Part 1 §2.1 확장 재천명)

**부재는 어느 쪽에 있든 판정 대상이 아니다.**

Part 1 §2.1: "빈 문자열은 표현이 아니라 부재다. 부재끼리 비교하면 안 되고, 부재-vs-값도 비교 대상이 아니다." — 이 원칙을 어댑터 층에도 이어받는다:

- **어댑터가 빈 output.value span 을 `raise` 하는 것 (3번)**: 사용자에게 "이 트레이스는 무효 데이터" 라고 오해시킴. 실제로는 그 span 하나가 부재를 담고 있을 뿐, 트레이스 전체가 무효한 게 아니다.
- **어댑터가 빈 output.value span 을 `warn+skip` 하는 것 (4번)**: 부재를 은닉. Cascade 층까지 도달하지 못하므로 cascade 의 명시적 skip (Part 1 §2.5) 이 발동할 여지 없음. 부재를 판정 대상에서 제외하는 결정이 어댑터 층에 숨어 있다.

**두 경우 다 판정 층 위로 결정이 밀려 올라가 있다.** 판정 층에서 명시적으로 skip 하는 것 (Part 1 §2.5) 과 다르다. 어댑터 층에서는 **판정과 무관한 형태로만 처리** 해야 한다 — 즉 부재를 있는 그대로 Span 으로 만들되, 그 이후 처리를 판정 층에 맡긴다.

### §2.2 3번 `langgraph.py:169` — 후보와 판정

| 방식 | 요지 | 판정 |
|---|---|---|
| (3-a) 완전 제거 | if 블록 삭제 · 모든 span 을 Span 생성기에 전달. tool 이면 Span validator 가 raise (Part 1 §2.4 구조적 불변식). non-tool 이면 통과. | **채택 ★** — 판정을 판정 층에 맡기고 어댑터는 통과시킨다. 원칙 정합. |
| (3-b) span_kind 별 분기 | `if span_kind == "tool" and not output_text.strip(): raise`. tool 만 어댑터 층에서도 걸러냄. non-tool 은 통과. | 기각 — Span validator 가 이미 tool 만 raise. 어댑터가 그 판단을 앞당길 이유 없음 · 중복 방어망은 근거 없이 유지되어 오늘 이 사고 원인이 됨. |
| (3-c) 유지 | 현행 유지. Part 2 재판정 목표 미달 유지. | 기각 — 이번 사전등록의 이유 자체. |

**(3-a) 채택 근거**:
- **원칙**: 판정과 무관한 처리는 어댑터에, 판정은 판정 층에. `raise` 는 판정.
- **역할 분업 (Part 1 §2.4 근거 3 계승)**: Span validator = 구조적 불변식 (tool span 은 output 이 있어야 유효). 어댑터의 역할은 attribute → Span 변환일 뿐. 유효성은 Span 이 스스로 검증.
- **[X] 조사 결과**: 이 게이트가 왜 어댑터에 중복으로 있는지 근거 없음. 유지할 이유가 문서화되지 않았고 제거해도 잃을 계약 없음.

### §2.3 4번 `otel_json.py:241` — 후보와 판정 (★ 실측 [5] 후 재검토)

**★ [5] 실측 결과** (`field_test/diagnostics/probe_trail_empty_kind.py`):

TRAIL 실 데이터 (`field_test/trail_sample.json` · 원 도입 커밋 `14451e18` 이 참조한 real o3-mini trace) 에서 빈 output.value OI span **12 개**:

| kind | count | names |
|---|---|---|
| CHAIN | 6 | `Step 4/5/6/7/8/13` |
| **TOOL** | **6** | `PageDownTool` × 5, `FinalAnswerTool` × 1 |

즉 원 커밋 `14451e18` 이 `warn+skip` 을 도입한 이유 ("TRAIL real data 에 output.value 없는 OI span 이 실제로 있어서 raise 하면 트레이스가 실패") 의 대상 중 **절반이 TOOL span** 이었다. Part 1 이 tool-only Span validator 를 유지했으므로 이 tool 6 개는 여전히 raise 대상.

| 방식 | 요지 | 판정 |
|---|---|---|
| (4-a) 완전 제거 | filter 블록 삭제. 빈 output.value span 도 Span 생성기에 전달. tool 이면 Span validator raise. non-tool 이면 통과. | **★ 기각** — [5] 실측: TRAIL 의 빈 tool span 6 개가 Part 1 Span validator raise 를 유발 → **트레이스 전체 실패**. `14451e18` 도입 근거인 "TRAIL trace 실패" 를 정확히 재현한다. draft 가 (4-d) 를 "도입 근거를 뒤집는 방향" 이라 기각한 것과 동일 이유로 (4-a) 도 기각. |
| (4-b) span_kind 별 분기 | `if kind == "tool" and no output.value: skip`. tool 만 어댑터에서 skip. non-tool 은 통과. | **기각** — (i) 조용한 데이터 손실이 tool 쪽에 그대로 남는다. (ii) "왜 tool 만 버리나" 의 근거가 "Span validator 가 tool 을 거부하니까" 여서 순환이다 (tool 을 버리는 이유가 tool 이 거부되는 것). 원칙 층에서 정당화 불가. |
| **(4-c) 유지 ★** | 현행 `warn+skip` 유지. Format C 진입 시 빈 output.value OI span 조용히 삭제 (raise 없음). | **채택** — Part 2 목표 (T1.2 / T1.4 재판정) 는 Format A 경로이고 4번은 Format C 전용이라 목표와 무관. 이 게이트를 열려면 Part 1 tool-only 결정도 함께 열어야 하며 (§13), 두 변경은 서로 의존하므로 별건 (Part 3) 로 다룬다. |
| (4-d) `raise` 로 승격 | warn+skip → raise 로 시끄럽게 처리. | 기각 — TRAIL real data 에 원래 있는 케이스 (도입 근거 · 커밋 `14451e18`) 라 시끄럽게 하면 정상 트레이스가 실패한다. 도입 근거를 뒤집는 방향. |

**(4-c) 유지 채택 근거**:
- **Part 2 목표와 무관**: T1.2 (OpenAI Agents) · T1.4 (AutoGen) 두 재판정 대상은 Format A 어댑터 (`ingest_from_otel_json` → `ingest_otel_spans`) 경로. Format C 필터 `otel_json.py:241` 을 지나가지 않는다. 이 게이트를 유지해도 Part 2 목표 달성에 지장 없음.
- **[5] 실측이 (4-a) / (4-d) 를 동시에 기각**: 두 후보 다 TRAIL 실 데이터에서 트레이스 전체 실패를 유발. `14451e18` 이 관측 근거로 도입한 결정이므로 관측 없이 뒤집는 것은 오류.
- **(4-b) 순환**: tool 만 어댑터에서 skip 하는 근거가 "Span validator 가 tool 을 거부하니까" 여서 순환 · 정당화 불가.
- **Part 1 (b'-넓게) 와 함께 다뤄야 정합** (§13): [5] 는 빈 tool 이 정상 데이터임을 함께 보였다 (`PageDownTool` 은 페이지를 넘기는 도구로 반환값이 없는 것이 정상). 즉 tool 도 Span validator 에서 빼고, cascade tool 분기에도 skip 을 넣고, `otel_json.py:241` 을 함께 여는 것이 Part 3 의 정합 스코프.
- **조용한 데이터 손실 리스크는 Part 3 로 이월**: Part 2 는 게이트 하나만 다룬다는 원칙 (Part 1 실수 재발 방지) 을 지킨다. 조용한 skip 은 문제로 인지만 하되 완화는 Part 3.

### §2.4 구체 변경 (설계상, 승인 후 구현)

**`src/clew/ingest/langgraph.py:169-173`** — 삭제:

```python
# 삭제 대상 (Part 2 §2.2 (3-a))
if not output_text.strip():
    raise ValueError(
        f"span {s.name!r} (span_id={_hex_span(s.context.span_id)}) has empty "
        "output.value — adapter refuses to construct invalid Span"
    )
```

Span 생성 라인 (`converted.append(Span(...))`) 은 그대로. tool 이면 Span validator 가 raise, non-tool 이면 통과.

**`src/clew/ingest/otel_json.py:238-252`** — 완전 제거 (skip filter 블록 전체):

```python
# 삭제 대상 (Part 2 §2.3 (4-a))
no_output = [
    r for r in oi_raws
    if not (r.get("span_attributes", {}).get("output.value") or "").strip()
]
if no_output:
    skipped_ids = ", ".join(...)
    warnings.warn(...)
    oi_raws = [r for r in oi_raws if r not in no_output]
```

**`src/clew/ingest/otel_json.py:253-254`** — 다음 raise 도 검토:

```python
if not oi_raws:
    raise ValueError(f"{path}: output.value 있는 OI 스팬이 하나도 없음")
```

원 의도: "전체 트레이스가 다 빈 output.value" 이면 무의미하니 실패. (4-a) 채택 후에도 유지 여부 판단: **유지** — 모든 span 이 빈 트레이스는 실제로 무효 데이터 (OI span 이 있긴 있는데 전부 부재). 부분적으로 빈 트레이스와 전체가 빈 트레이스는 다르다.

**docstring · 주석**: `langgraph.py::otel_spans_to_trace` 및 `otel_json.py::ingest_from_openinference_json` docstring 갱신 (부재 처리 정책 명시 · Part 2 참조).

---

## §3 — ★ downstream 영향 예측 (구현 전 확정, §4 KILL 기준 근거)

### §3.a Part 1 skip 이 실제로 발동하는가 (Part 1 §11.4 확증 축)

- **예측**: (3-a) + (4-a) 채택 시 빈 non-tool span 이 파이프라인에 처음으로 들어옴. cascade `cascade.py:73` skip 이 실 데이터로 발동.
- **검증 방법**: 
  1. dev-7 재실행 시 cascade skip 이 몇 번 발동하는지 카운터 (계측 코드가 없으면 이번 사전등록 스코프 밖 · 관찰만).
  2. Tier 1 재판정 시 T1.2 / T1.4 span 카운트가 완화 전보다 늘어난 것 확인.
- **의의**: Part 1 §11.4 "완화가 실 데이터에서 발동한 적 없음" 미확증이 이번에 해소.

### §3.b dev-7 trace-level FPR

- **예측**: **0.0 유지**. dev-7 는 seed=42 로 생성된 합성 데이터 · Trace JSON 을 checked-in (Clew 시리얼라이즈 형식). Part 2 대상은 **Format A/C 어댑터** 경로만 건드림 — dev-7 로드는 `_load_trace_auto` 가 Clew Trace JSON 경로로 (`__main__.py:102-103` `load_trace`) 처리하고 Format A/C 어댑터 안 탐. Part 2 변경 무영향.
- **검증 방법**: `test_per_pattern_dev_direct` 재실행. `agg["fpr"] == 0.0` · `pp["_control"]["fpr"] == 0.0` assertion 통과 확인.

### §3.c 리포트 렌더에 빈 span 이 어떻게 보이나

- **예측**: 
  - **cascade waste 리포트**: 빈 span 은 skip 되므로 waste_span_ids 에 등장 안 함. 리포트 스니펫에도 등장 안 함.
  - **id_bridge 리포트**: pool 은 tool span 만이므로 빈 non-tool span 무관.
  - **between_window**: `_classify_between_window` 이 output_text 안 봄. 무영향.
  - **amplification**: `amplification.py:131` `if not s.output_text: continue` — 빈 span 스킵 (n_skip_meta 증가). 값 자체 무변.
- **의의**: **리포트 문면 개선은 별건 (§7 스코프 밖)**. 이번 스코프는 리포트에 빈 span 이 조용히 안 보이는 것을 허용.

### §3.d between_window / id_bridge / amplification

- **§3.d.1 between_window**: 무변 (`_classify_between_window` 이 span_kind / agent_or_node_id / timestamp 만 참조). 5-count `1226/888/405/248/1024` 무변.
- **§3.d.2 id_bridge**: 무변 (`scan_id_bridge_candidates` 의 pool `cand.span_kind == "tool"`). tool 은 여전히 Span validator 로 non-empty. `differ/same/no_id 159/76/3197` 무변.
- **§3.d.3 amplification**: 이미 빈 output_text skip. n_skip_meta 카운트만 상승 가능 · 값 무변.

### §3.e Format A fixture 결과 변화 (★ 재실측 필수 축)

- **예측**: 
  - `tests/fixtures/openinference_langchain.json` · `tests/fixtures/openinference_crewai.json` 는 Format A (SDK JSON list) 로 판별됨 (probe_h.py [4] 결과 · `ingest_from_otel_json` 경로).
  - 두 fixture 는 R2 완화 이전에 output.value non-empty · 이번 3번 완화로도 무영향 예상.
- **검증 방법**: `pytest tests/test_openinference_adapter.py -q` — LangChain / CrewAI fixture 회귀. 무변 예상.
- **KILL 조건**: 기존 fixture 회귀 실패 → KILL.

### §3.f Span 수가 늘어나는가 (Format A 경로)

- **예측**: T1.2 · T1.4 dump 재판정 시 non-tool 빈 span 이 이전에 어댑터 층에서 raise 되었으나 이제 통과. Span 수 증가.
- **검증 방법**: 재판정 시 이전 (Part 1 상태) 대비 span 수 대조.
- **KILL 여부**: 카운트 증가 자체는 KILL 아님. 늘어난 span 이 downstream 판정을 뒤집으면 (waste_span_ids 등) 그건 §4 KILL.

**Format C 경로 (`otel_json.py:241`) 는 이번 스코프 밖 · Part 3 로 이월** (§13). TRAIL fixture 등 Format C 결과 변화는 Part 3 에서 예측한다.

### §3.g 종합 예측 표

| 축 | 예측 | KILL 조건 |
|---|---|---|
| §3.a Part 1 skip 발동 확증 | 발동 (Tier 1 재판정 시) | 발동 안 하면 KILL 아니지만 유효성 미확증 유지 |
| §3.b dev-7 FPR | 0.0 유지 (Part 2 는 Format A 어댑터만 · dev-7 무관) | > 0 = KILL |
| §3.c 리포트 렌더 | 빈 span 은 waste/id_bridge/between_window 모두 등장 안 함 | 렌더 실패 = KILL |
| §3.d.1 between_window | 무변 (1226/888/405/248/1024) | 변화 = KILL |
| §3.d.2 id_bridge | 무변 (159/76/3197) | 변화 = KILL |
| §3.d.3 amplification | 값 무변 | 값 변화 = KILL |
| §3.e Format A fixture 회귀 | 기존 fixture 무변 | 회귀 = KILL |
| §3.f span 수 증가 | 재판정 대상 dump 에서 증가 (Format A 경로) | 증가 자체는 KILL 아님 |

---

## §4 — ★ KILL 기준 (결과 보기 전 확정, 불가침)

**Part 1 §4 6축 그대로 유지 + Part 2 특화 축 추가**.

### §4.1 즉시 KILL 조건 (하나라도 발동 시)

1. **`waste_span_ids sha256` 변화** — cand `5c0c94d6…` / pair `742b51a7…`.
2. **`between_window_counts` 변화** — `1226/888/405/248/1024`.
3. **`id_bridge_candidates` 분포 변화** — `159/76/3197`.
4. **`eval/set_manifest.json` sha 변화** — `a205a3d6…`.
5. **dev-7 trace-level FPR > 0** — 완화 전 baseline 0.0. **★ 임계 완화 없음** (Part 1 Q2b 기각 계승).
6. **기존 pytest 회귀** — 455 → 455 + N 신규. 회귀 발생 시 KILL.
7. **★ Format A fixture 회귀** — `tests/test_openinference_adapter.py::test_ingest_openinference_langchain_fixture_*` · `test_ingest_openinference_crewai_fixture_*` 실패 시 KILL.
8. **★ Tier 1 재판정 부작용** — T1.1 LlamaIndex (기존 PASS) 가 FAIL 로 뒤집히거나, T1.3 Anthropic (R5 · R2 무관) 결과가 바뀌면 KILL. 두 축 다 R2 무관 지점이므로 결과 변화는 완화 부작용 신호.

### §4.2 KILL 시 대응

- 커밋 revert (`langgraph.py:169-173` + `otel_json.py:238-254` 원 상태 복원).
- 사전등록 §11 verdict 부기 (KILL sha · 원인).
- **완화 자체를 재시도하지 않는다** (reread 선례 계승).
- 리포트 노트에 명시.

### §4.3 KILL 이 아닌 관찰 (기록만)

- Format C 경로에서 span 수 증가 (§3.f).
- Cascade skip 발동 카운트 (계측 없으면 관찰 못 함).
- amplification `n_skip_meta` 카운트 상승.
- 리포트에 빈 span 이 조용히 안 보이는 케이스 (§3.c) — 문면 개선은 별건.
- Tier 1 T1.2 / T1.4 재판정 결과 (§5).

---

## §5 — 재판정 계획

### §5.1 대상

- **Tier 1 4 프레임워크 재판정** — Part 1 §5 과 동일 스코프.
- **Focus**: T1.2 OpenAI Agents · T1.4 AutoGen — Part 1 §11.3 미달 지점. 이번 Part 2 로 어댑터 gate 열림.
- **PASS 유지 확증**: T1.1 LlamaIndex (Part 1 재판정에서 PASS 유지 확증).
- **T1.3 Anthropic**: FAIL 원인 R5 (multi trace_id). R2 무관 · Part 2 로도 결과 안 바뀔 예정.

### §5.2 기존 dump 재사용 (Part 1 §5.2 계승)

Part 1 근거 4 축 그대로:
1. Baseline 통제.
2. 어댑터 완화의 순수 효과 측정.
3. LLM 비용 0.
4. `§3.4 Tier 1 규칙` 정합.

### §5.3 재판정 산출물

**`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` §1.1 갱신**:
- "재판정 (Part 2 완화 후)" 컬럼 추가. Part 1 열 유지 · **원 판정 덮어쓰지 않음** (Part 1 Q5 계승).
- T1.2 / T1.4 결과 (PASS / PARTIAL / FAIL) 병기.
- **★ Tier 1 재판정 결과가 나온 뒤 별건 커밋** (Part 2 세 번째 커밋).

**변경 커밋**: `docs(results): T1.2 · T1.4 재판정 (Part 2 완화 후)` — Part 2 커밋 chain 의 마지막.

---

## §6 — 불가침 (Part 1 §6 그대로)

### §6.1 값 무변 (§4.1 KILL 조건)

- `waste_span_ids sha256`: `cand=5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4`, `pair=742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0`.
- `between_window_counts`: `1226/888/405/248/1024`.
- `id_bridge_candidates`: `differ/same/no_id = 159/76/3197`.
- `eval/set_manifest.json` sha256: `a205a3d62e8310f67f0ab1a7faa957504b9f486a8c5a68cebeadf010aff42952`.
- `coverage_stats` 6 필드.

### §6.2 탐지 로직 · 동결 파라미터

- φ = 0.514345, N = 2, embedding model 동결.
- `cascade` (Part 1 이미 skip 삽입 · Part 2 는 어댑터만) / `structural` / `semantic` 로직.
- `_ID_BRIDGE_MAPPING` 26 도구.
- Part 1 완화 지점 (model.py:88 · cascade.py:73) 무변 — Part 2 는 어댑터 층만.

### §6.3 dev-7 FPR = 0.0 baseline

- Part 1 §6.3 계승. 완화 후 FPR > 0 = KILL.

---

## §7 — 범위 밖

| 항목 | 이유 |
|---|---|
| **`otel_json.py:241` 완화 (Format C · 4번 게이트)** | **★ Part 3 로 이월** (§13). [5] 실측 결과 Part 1 (b'-넓게) 와 함께 다뤄야 정합. |
| **Part 1 `Span._output_text_non_empty_on_tool` 완전 제거** | Part 3 대상 (§13 상호 의존). [5] 로 빈 tool 이 정상 데이터임이 확인됐으나 cascade tool 분기 skip 삽입과 동시에 다뤄야 함. |
| **cascade tool 분기 (`cascade.py:62`) 에 빈 값 skip 삽입** | Part 3 대상 (§13). |
| **Part 1 문서 (`docs/ADAPTER_R2_RELAXATION_PREREG.md`) 사후 수정** | 원칙적으로 금지. 근거 정정은 이 문서 §12 에만 기록. 코드 주석은 Part 3 시점에 갱신. |
| 리포트에 빈 span 을 표시할 문면 (예: `"(no output)"` 스니펫) | 별건 · 문면 개선은 재판정 결과 확정 후 결정. |
| Tier 2 조사 | 별건 (사전등록 §5.3 예산 규칙). |
| Instrumentor upstream fix 모니터링 | 별건 (Arize-ai/openinference issue #3337 · #3392). |
| `extract_output_text` leaf 규칙 재설계 | 별건 · Tier 1 §7 한계 유지. |

---

## §8 — Open Questions (승인 전 사용자 확정)

| # | 질문 | 초안 답 |
|---|---|---|
| Q1 | 3번 `langgraph.py:169` (3-a) 채택 · 완전 제거 | 예상 유지. Span validator 가 tool 은 여전히 raise. |
| Q2 | ★ 4번 `otel_json.py:241` — (4-c) 유지 채택 (스코프 축소) | 예상 유지. [5] TRAIL 실측 근거: 빈 output.value OI span 중 tool 6 개 (`PageDownTool` × 5, `FinalAnswerTool` × 1) 존재. (4-a) / (4-d) 는 원 도입 근거 (`14451e18`) 를 뒤집어 트레이스 실패 유발. (4-b) 는 순환. Part 3 (§13) 로 이월. |
| Q3 | `otel_json.py:253-254` "전체가 빈 트레이스" raise | (4-c) 유지 채택이므로 이 raise 도 손대지 않음 (Part 3 대상). |
| Q4 | KILL 임계 목록 (§4.1) 완전한가? | Part 1 6축 + Format A fixture + Tier 1 부작용 = 8축. dev-7 FPR > 0 임계 유지 (완화 없음). |
| Q5 | 기존 dump 재사용 (§5.2) | Part 1 그대로 계승. |
| Q6 | Tier 1 결과 리포트 §1.1 갱신 · Part 1 열 유지 · Part 2 열 추가 | Q5 (Part 1) 계승 — 덮어쓰지 않음. |
| Q7 | 완화 커밋 후 릴리스 (v0.4.1 patch bump?) | Part 1 Q6 계승: **재판정 결과를 보고 정한다**. 결과 모르는 상태로 릴리스 계획 확정 안 함. |

---

## §9 — 커밋 체인 (설계상, 승인 후)

**★ PR 없이 바로 구현 · 3 커밋**:

1. `feat(ingest): drop langgraph adapter-layer empty output.value gate` —
   - `src/clew/ingest/langgraph.py:169-173` 제거 (§2.2 (3-a)).
   - **`src/clew/ingest/otel_json.py:238-252` 무변** (§2.3 (4-c) 유지 채택 · Part 3 로 이월).
   - docstring 갱신 · Part 2 참조.
   - 신규 회귀 2 개 (Format A 어댑터 빈 non-tool 허용 · 정상 트레이스 회귀).
2. `test(ingest+results): Part 2 재판정 회귀` —
   - `tests/test_openinference_adapter.py` 확인 (Format A LangChain / CrewAI fixture 무변).
   - Tier 1 T1.2 / T1.4 dump 재판정 실행.
3. `docs(results): T1.2 · T1.4 재판정 (Part 2 완화 후)` —
   - `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` §1.1 갱신.
   - **원 판정 유지 · Part 1 재판정 유지 · Part 2 재판정 새 컬럼**.
   - Part 2 verdict (§11) 부기.

**KILL 발동 시**: 세 커밋 revert. §11 (Verdict) 형태로 부기.

---

## §10 — 참조

### 사전등록
- `docs/ADAPTER_R2_RELAXATION_PREREG.md` (Part 1) — §11 verdict.
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` — Tier 1 판정 기준 원.
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` — Tier 1 결과 · §3 자기공개.
- `docs/REREAD_DETECTOR_PREREG.md` §11 — KILL 대응 선례.

### 코드
- `src/clew/ingest/langgraph.py:169-173` — 완화 대상 (Part 2 §2.2 (3-a)).
- `src/clew/ingest/otel_json.py:238-254` — 완화 대상 (Part 2 §2.3 (4-a)).
- `src/clew/model.py:88` — Part 1 완료 · 무변.
- `src/clew/detect/cascade.py:73` — Part 1 완료 · Part 2 에서 실 데이터로 발동 확증.
- `src/clew/ingest/otel_json.py::ingest_from_openinference_json` — Format C 진입.

### 커밋 이력 (Part 2 §1.3 참조)
- `0fa25e0` (2026-06-06) — `langgraph.py:169` 도입 · 근거 미기록.
- `14451e18` (2026-07-10) — `otel_json.py:241` 도입 · 근거 있음 (TRAIL real data).
- Part 1 §11.5 [X] 조사 결과.

### 실측·측정
- `field_test/diagnostics/framework_expansion_dumps/` — Tier 1 dump (재사용).
- `eval/dev/seed-7/` — dev-7 FPR baseline (0.0).
- `validation/CRITERIA_FROZEN.md` — Stage 2 results 기록.

### Memory
- `memory/feedback_intentional_drift.md` — 정당한 변경 시 회귀 처리 원칙.
- `memory/feedback_prereg_vs_local_design.md` — docs/ 커밋 판단.
- `memory/reference_reread_kill_doc.md` — reread KILL 선례.

---

## §11 — Verdict (2026-08-01 실행 후 기록)

**실행 커밋**: `feat/r2-relaxation-part2` 브랜치, commits `74157b9` (langgraph drop) + `22b261d` (test 회귀).

### §11.1 §3 예측 대조 (전부 일치)

| 축 | 예측 | 실제 |
|---|---|---|
| §3.a Part 1 skip 발동 확증 | Tier 1 재판정 시 발동 예상 | ✓ 실증 — T1.2 OA-Runner 1 pair, T1.4 AutoGen 2 pair 가 empty side → cascade skip 발동 (embedder 호출 없이 pass) |
| §3.b dev-7 FPR | 0.0 유지 (Format A 어댑터만 · dev-7 무관) | ✓ 0.0 유지 (`test_per_pattern_dev_direct` PASS) |
| §3.c 리포트 렌더 | 빈 span 은 waste/id_bridge/between_window 모두 등장 안 함 | ✓ 확인 (Format A fixture 회귀 통과) |
| §3.d.1 between_window | 무변 (1226/888/405/248/1024) | ✓ 유지 |
| §3.d.2 id_bridge | 무변 (159/76/3197) | ✓ 유지 |
| §3.d.3 amplification | 값 무변 | ✓ 유지 |
| §3.e Format A fixture 회귀 | 무변 | ✓ (LangChain / CrewAI fixture regression PASS) |
| §3.f span 수 증가 | 재판정 대상 dump 에서 증가 | ✓ T1.2 OA-primitive: FAIL → 5 spans / OA-Runner: FAIL → 7 spans / T1.4 AutoGen: FAIL → 9 spans |

### §11.2 §4 KILL 8 축 (전부 통과)

1. `waste_span_ids sha256` cand=`5c0c94d6…` / pair=`742b51a7…` — 무변.
2. `between_window_counts` `1226/888/405/248/1024` — 무변.
3. `id_bridge_candidates` `differ/same/no_id = 159/76/3197` — 무변.
4. `eval/set_manifest.json` sha `a205a3d6…` — 무변.
5. dev-7 trace-level FPR — **0.0 유지** (완화 없음, Q2b 기각 준수).
6. 전체 pytest — 458 passed (기존 455 baseline + 신규 3), 실패 0.
7. Format A fixture 회귀 — LangChain / CrewAI fixture 무변.
8. Tier 1 부작용 — T1.1 LlamaIndex PASS 유지, T1.3 Anthropic FAIL 유지 (예상대로 · R5 원인, R2 무관).

### §11.3 §5 재판정 (Part 1 §11.3 미달 목표 달성)

**★ T1.2 OA-primitive · T1.2 OA-Runner · T1.4 AutoGen 세 케이스 모두 FAIL → PASS.**

Ingest 결과:
- T1.2 OA-primitive: 5 spans (agent 1 · tool 4). Non-tool empty = 1 (probe_workflow AGENT). single trace_id · 1 root.
- T1.2 OA-Runner: 7 spans (chain 3 · agent 2 · tool 2). Non-tool empty = 5. single trace_id · 1 root.
- T1.4 AutoGen: 9 spans (chain 1 · agent 4 · tool 4). Non-tool empty = 4 (`on_messages_stream` 4). single trace_id · 1 root.

**R1-R5 재판정**: 모두 일치. **O1-O5 관측**: O1 `graph.node.id` 는 OA-Runner 에서 존재 (probe_agent) · AutoGen 에서 존재. Tier 1 §3.2 원칙 그대로 (선택 축 부재 자체 저하 아님).

**T1.3 Anthropic**: FAIL 유지 (R5 · multi trace_id, R2 무관 · 예상대로).

### §11.4 ★ Part 1 §11.4 확증 축 해소

Part 1 §11.4 는 실 데이터로 완화가 발동한 적 없다고 정직하게 기록했다. Part 2 로 어댑터 gate 를 여니 **처음으로 실 데이터가 cascade non-tool skip 을 발동**:

| Dump | non-tool candidate pair with empty side | Part 1 skip 발동 |
|---|---|---|
| T1.2 OA-primitive | 0 | (해당 없음) |
| T1.2 OA-Runner | **1** | ✓ 발동 |
| T1.4 AutoGen | **2** | ✓ 발동 |

즉 Part 1 skip 유효성은 이제 합성 test 3 개 + 실 데이터 3 pair 로 확증됨.

### §11.5 Part 2 verdict 요약 한 줄

**Part 2 성공**: 세 케이스 (T1.2 OA-primitive · OA-Runner · T1.4 AutoGen) FAIL → PASS. Part 1 skip 실 데이터 첫 실증. §4 KILL 8축 전부 통과. §3 예측 전부 일치. T1.3 Anthropic 만 FAIL 유지 (R5 · R2 무관, 예상대로). Part 3 는 `otel_json.py:241` + Part 1 (b'-넓게) 상호 의존 스코프로 별건 사전등록 대상 (§13).

---

## §12 — ★ Part 1 근거 문면 오류 기록 (Part 1 결정 유지 · 근거만 정정)

### §12.1 오류의 정체

Part 1 `docs/ADAPTER_R2_RELAXATION_PREREG.md` §2.4 · §2.5 이 `Span._output_text_non_empty_on_tool` validator 의 근거로 다음 문구를 썼다:

> `"structural invariant: a tool call with no output is invalid data"`

Part 2 [5] 실측이 이 문구를 반증한다:
- TRAIL 실 데이터에서 `PageDownTool` 5 개 · `FinalAnswerTool` 1 개가 **빈 output.value 로 실측 존재**.
- `PageDownTool` 은 페이지를 넘기는 도구로 반환할 값이 없는 것이 정상이다. 빈 tool span 은 **invalid data 가 아니라 정상 데이터**다.
- 즉 "빈 tool = invalid" 는 사실 진술로 성립 안 함.

### §12.2 왜 Part 1 결정 자체는 유지되나

**결정 유지의 실제 근거는 detection-layer constraint 다**. Part 1 §3.a 예측 표에도 이 근거가 이미 명시돼 있다:

- `cascade.py:62` — tool 분기가 `sha256(a) == sha256(b)` 로 waste 를 판정한다.
- `sha256(b"") == sha256(b"")` 은 항상 True → 빈 tool span 두 개는 **판정 대상이 되는 즉시** false positive.
- 이 문제를 막는 방식은 두 가지: (i) 입구에서 tool 을 non-empty 로 제약 (Part 1 채택) 또는 (ii) cascade tool 분기에도 빈 값 skip 을 넣기 (Part 1 §2.3 (b'-넓게) · Part 3 후보).

Part 1 은 폭발 반경이 작은 (i) 을 채택했고, 이 자체는 여전히 옳다. **틀린 것은 결정이 아니라 근거 문면**이다.

### §12.3 정확한 근거 문면 (교체안)

원 문구:
> "structural invariant: a tool call with no output is invalid data"

교체안:
> "cascade sha256 gate matches empty-vs-empty, so tool spans are gated at the entrance. This is a detection-layer constraint, not a statement about data validity — empty tool output is legitimate (measured: TRAIL PageDownTool)."

### §12.4 Part 1 문서 자체는 사후 수정하지 않는다

**★ Merge 된 판정 문서는 사후 수정하지 않는 것이 이 프로젝트의 원칙이다** (사전등록 정합성).

- Part 1 §2.4 · §2.5 문면은 그대로 둔다. 이력에 오류가 남는다.
- 정정은 **이 Part 2 문서 §12 에만 기록**. 향후 이 규칙을 참조할 때는 §12.3 교체안이 근거가 되며, Part 1 §2.4·§2.5 의 원 문구는 "이 결정을 도입할 때 사용된 근거" 라는 역사적 맥락으로만 읽는다.
- 코드 주석 (`src/clew/model.py:88` 부근 · Part 1 커밋 `421bfbf` 로 들어간 `"structural invariant"` 문구) 은 Part 3 완화 시점에 함께 갱신한다 (Part 3 스코프에 포함).

### §12.5 왜 별건이 아니라 이 문서에 기록하는가

- Part 3 사전등록에서 (b'-넓게) 근거를 세울 때 §12 를 반드시 인용해야 한다. 이 문서에 두면 참조 chain 이 명확 (Part 1 결정 → Part 2 §12 정정 → Part 3 근거).
- "Part 1 문서 사후 수정 금지" 원칙을 지키면서도 오류가 기록으로 남는 유일한 자리.

---

## §13 — Part 3 후보 명시

### §13.1 Part 3 스코프 (제안)

**`otel_json.py:241` (Format C 조용한 skip) + Part 1 (b'-넓게) (Span validator 완전 제거 + cascade tool 분기 skip 삽입) 을 함께 다룬다.**

### §13.2 왜 함께 다뤄야 하는가 — 두 변경의 상호 의존성

[5] 실측이 두 사실을 함께 보였다:

1. **빈 tool span 은 정상 데이터** (`PageDownTool` 처럼 반환값이 없는 도구가 실존).
2. **`otel_json.py:241` 이 이 정상 데이터를 조용히 skip 한다** (TRAIL 에서 6 개 tool + 6 개 chain).

두 사실을 인정하면 다음이 자동으로 따라온다:

- Span validator 의 tool non-empty 요구는 정상 데이터 (`PageDownTool` 같은 empty-return tool) 를 거부한다 → validator 완전 제거가 정합.
- 완전 제거 시 cascade tool 분기의 sha256 빈-vs-빈 매칭 문제가 다시 열림 → cascade tool 분기에도 skip 삽입 필요.
- 그러면 `otel_json.py:241` 이 tool 을 조용히 skip 할 이유가 사라진다 (통과시켜도 cascade 가 안전하게 처리) → 4번 게이트 근거 없이 제거 가능.

**즉 Part 3 세 지점은 순차가 아니라 상호 의존이다.** 하나만 열면 정합이 무너진다. Part 2 처럼 하나씩 스코프 축소할 대상이 아니라 세 지점을 함께 sourcing 해야 한다.

### §13.3 Part 3 예상 스코프 요약

| # | 위치 | Part 3 변경 |
|---|---|---|
| 1' | `src/clew/model.py::Span._output_text_non_empty_on_tool` | 완전 제거 (§12 정정 근거 반영) |
| 2' | `src/clew/detect/cascade.py:62` (tool 분기) | non-tool 과 대칭으로 빈 값 skip 삽입 |
| 4' | `src/clew/ingest/otel_json.py:238-252` | 완전 제거 (근거 소멸) |
| 부수 | Part 1 커밋 `421bfbf` 의 `"structural invariant"` 주석 | §12.3 교체안 반영 |

### §13.4 Part 3 사전등록 시 확인 대상 (미리 짚어두는 것 · 결정 아님)

- **cascade tool 분기 skip 삽입** 후 §3.a (Part 1 skip 이 실 데이터에서 발동) 축이 tool 쪽에서도 확증되는지.
- **§6.1 gate 축 8 개 무변** 재확인 필요 (특히 waste_span_ids sha256 · 이제 tool 도 판정층 skip 이 들어가므로 실 데이터 재실행).
- **[5] 결과 재사용 가능성**: 빈 tool 존재 확증은 [5] 로 이미 있음. Part 3 사전등록 시 새 실측 없이 이 결과 인용 가능.

### §13.5 Part 3 진행 시점

- **Part 2 verdict (§11) 확인 후**. Part 2 재판정 결과가 나오지 않은 상태에서 Part 3 를 진행하면 어느 완화가 어느 결과를 냈는지 구분 불가.
- **Q7 (릴리스 시점) 계승**: Part 2 재판정 결과에 따라 Part 3 시점 결정.
