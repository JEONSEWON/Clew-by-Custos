# Adapter R2 Relaxation — Pre-registration (2026-08-01)

**작성 시각 (UTC)**: 2026-08-01T00:00:00Z
**HEAD 해시**: `main @ c0cf018` (Merge PR #57 `fix/version-from-metadata` merged · v0.4.0 landed on PyPI/tag) 기준으로 컷.
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**선행**:
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` — §2.1 R2 원 정의 (`output.value` 존재·비어있지 않음).
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` §3 — 자기공개: R2 가 OpenInference 스펙보다 엄격.
- `field_test/diagnostics/openinference_output_text_fix_PREREG.md` v3 (로컬) — `raw_output_text` 안전망 선례.
- v0.4.0 태그 · PyPI landed 확증 (`memory/feedback_pypi_release_procedure.md` 준수).

---

## §0 — 이 사전등록이 하는 것 · 하지 않는 것

**하는 것.**
- Tier 1 결과 리포트 §3 이 자기공개한 결함을 fix — `Span.output_text` non-empty 검증기가 OpenInference 스펙보다 엄격했다.
- **결과 보기 전에** 완화 방식 · downstream 영향 예측 · KILL 임계 · 재판정 절차를 확정.
- 완화 후 T1.2 · T1.4 재판정 (upstream 무변경 상태에서).

**하지 않는 것.**
- Tier 2 조사 (별건).
- `extract_output_text` leaf 선택 규칙 재설계 (별건 · Tier 1 §7 한계).
- OpenInference 어댑터 · preprocess 파이프라인 로직 변경 (R2 검증기 완화만).
- README 지원 목록 갱신 · 사용자-facing 문서 확장 (재판정 결과 확정 후 별건).
- 웹앱 · 홈페이지 반영.
- 실 fix 를 마쳤어도 downstream 임계를 넘으면 → **KILL** (§4 · 원복).

---

## §1 — 배경 · 문제 재확인

### §1.1 자기공개 요약 (Results §3)

우리 §2.1 R2 (사전등록):
> "`output.value` 존재 · 비어있지 않음 (strip 후 len ≥ 1)".

OpenInference 스펙 (실측):
- 유일한 필수 속성 = `openinference.span.kind`.
- `output.value` = Reserved Attributes 표 등재, **MUST/SHOULD 언어 없음**.
- span kind 별 mandatory 표 자체 없음.
- `OUTPUT_VALUE` 상수에 docstring 조차 없음.

**결론 재천명**: 우리 R2 는 스펙보다 엄격. 근거를 `src/clew/model.py:38-43` 의 `Span.output_text` non-empty 검증기에서 가져왔고 스펙 대조를 안 했다. Tier 1 FAIL 3 건 중 **T1.2 (OpenAI Agents) · T1.4 (AutoGen)** 가 이 결함으로 FAIL 분류됨.

### §1.2 ★ 이번 변경이 이전과 다른 점 — §3 게이트가 진짜 관문이다

`raw_output_text` 추가 (PR #52) 는 **어댑터 한 경로만 건드렸다** (`preprocess_trace` 의 tool 분기). 그리고 H 실측이 방어막 — `preprocess_trace` 는 langgraph 경로에서만 호출 (Toolathlon/CC/RB 미실행 확증). 즉 §3 gate 축이 자동으로 논리 보장됐다.

**R2 완화는 다르다**. `src/clew/model.py:38-43` 의 `Span.output_text` field validator 는 모든 `Span(...)` 인스턴스에 적용된다. 즉:

- **모든 어댑터의 모든 span 이 이 검증기를 탄다** (`ingest_claude_code_jsonl`, `ingest_toolathlon_jsonl`, `ingest_redundancy_bench_json`, `ingest_otel_spans` 전부).
- H 확증 ("Toolathlon/CC/RB 는 preprocess 미실행") 은 **여기서 방어막이 되지 않는다** — H 는 preprocess 경로만 다뤘다.
- `Span` 검증기 완화는 §3.1 gate 축 (waste_span_ids sha256, between_window, id_bridge 수치) 에 **직접 영향할 수 있다** — 빈 output_text 를 새로 허용하면 이전에 거부됐던 span 이 데이터에 들어올 수 있고, 이는 cascade / between_window / id_bridge 로 전파.

**정합 결과**: §3 gate 는 여기서 **진짜 관문**이다. 자동 논리 보증 아니고 실측으로 검증 필수. 그리고 KILL 조건도 이 gate 를 기준으로 잡는다 (§4).

---

## §2 — ★ 완화 방식 · 결과 보기 전 확정

### §2.1 근거 원칙 (재프레이밍, 커밋 전 확립)

**부재는 어느 쪽에 있든 판정 대상이 아니다.** φ 게이트는 "같은 뜻을 다르게 표현했는가" 를 묻는다. 빈 문자열은 **표현이 아니라 부재**다. 빈 값 두 개를 비교하는 것은 부재끼리 비교해서 "같다" 는 잘못된 답을 얻는 것이고, 빈 값 하나와 정상 값을 비교하는 것은 **비교가 성립해서 다른 게 아니라 비교할 대상이 없는 것**이다 (한쪽이 표현 자체를 안 낸 상태). sha256 도 마찬가지 — 빈 값 두 개가 바이트 동일한 것은 "같은 결과" 가 아니라 "결과가 없음" 이다.

지금까지 이 경로가 닫혀 있던 이유는 **입구 (`Span` 검증기) 가 막고 있었기 때문**이다. 입구를 스펙에 맞게 열면, 막고 있던 판정을 **판정 층에서 명시적으로 처리** 해야 한다. 게이트 추가는 KILL 회피가 아니라 **책임의 이전**이다.

**★ 실측 참조 (§3.b)**: `cosine(embed(""), embed(<normal text>))` 는 7 개 샘플 전부 **φ 미만** (0.009 ~ 0.315). 즉 빈-vs-값 케이스는 실용적으로는 φ 미달로 자연 skip 된다. 이 사전등록이 § 2.5 코드에서 `and` 로 빈-vs-값도 명시적으로 skip 하는 것은 **실용 차이 때문이 아니라 원칙의 정의를 코드와 문서에서 동일하게 유지하기 위함**이다.

**★ 왜 코드를 좁히는 대신 문서를 넓혔는가**:
- (i) 코드가 문서보다 좁을 이유가 없다. 실측이 빈-vs-값도 skip 대상으로 처리해도 안전함을 이미 보여줬다.
- (ii) 판정 대상 정의가 두 곳 (문서 · 코드) 에 존재하면 어긋남이 나올 수 있다. 이 프로젝트는 오늘 그런 어긋남을 이미 두 번 잡았다 (`__version__` 이중 소스, `docs/*.md` grep 가드 좁음). 여기서도 같은 패턴이 재발할 여지를 줄인다.
- (iii) 사전등록의 목적은 결과 보기 전에 판정 규칙을 못 박는 것. 코드가 표현하는 규칙이 원칙 서술보다 넓으면 나중에 "왜 이렇게 했지" 가 된다. 그걸 지금 정한다.

### §2.2 후보와 기각 근거

| 방식 | 요지 | 판정 |
|---|---|---|
| (a) 완전 제거 | `_output_text_non_empty` 삭제, 판정층 추가 없음. | 기각 — cascade sha256 (tool) 이 빈-vs-빈 매치 → false positive. |
| (b) span_kind 별 분기, 판정층 무변 | tool 은 non-empty 유지, chain/agent 는 허용, cascade 는 무변. | 기각 — §3.b 실측: `cosine(embed(""), embed("")) = 1.0` → φ 훨씬 초과. non-tool 빈-vs-빈 매치 확정. |
| (c) placeholder 대체 | 빈 값을 sentinel 로 치환. | 기각 — 값 지어내기 (project 관행 위반). placeholder 두 개도 sha/cos 매치. |
| **(b') 채택 ★** | 입구 정책 + 판정층 skip 을 함께 재정비. 구체 범위는 §2.4. | §2.1 근거 원칙 정합. |

### §2.3 (b') 범위 결정 — 두 안

두 안 다 §2.1 원칙 ("부재 두 개는 판정 대상 아님") 은 동일. 다른 것은 **원칙 적용 층**과 **폭발 반경**.

#### §2.3.1 (b'-좁게)

- **입구**: `Span._output_text_non_empty` 를 `span_kind == "tool"` 조건에서만 유지 (tool 은 여전히 non-empty 요구).
- **판정층**: `cascade.py:66` non-tool 분기 앞에 `if not (origin.output_text.strip() and candidate.output_text.strip()): continue` 삽입. cascade tool 분기 (`cascade.py:62`) 는 무변 (tool 은 입구에서 이미 걸러짐).
- **§3.a 예측**: 무변 (`5c0c94d6…` / `742b51a7…`). tool 입구 검증기 유지되어 tool 경로 자동 보증.
- **§3.b 예측**: 무변. non-tool 이 빈 값 두 개로 들어와도 cascade 진입 전 skip.

#### §2.3.2 (b'-넓게)

- **입구**: `Span._output_text_non_empty` 완전 제거. 모든 span kind 가 빈 output_text 허용.
- **판정층**: `cascade.py:62` (tool) · `cascade.py:66` (non-tool) 양쪽 앞에 `if not (origin.output_text.strip() and candidate.output_text.strip()): continue` 삽입. **"빈 값은 판정 대상 아님" 규칙이 판정 층 한 곳에만 존재**.
- **§3.a 예측**: 무변 예상이지만 **재검증 필수** — tool 경로가 처음으로 빈 output_text 허용받게 되므로 Toolathlon 실측으로 sha 확인.
- **§3.b 예측**: 무변. non-tool skip 은 (b'-좁게) 와 동일.

### §2.4 (b') 채택 안 — **(b'-좁게)** ★

**근거 4 축**:

1. **T1.2 / T1.4 재판정 목표 필요·충분** — 두 FAIL 원인 모두 non-TOOL span (`turn` CHAIN, `on_messages_stream` AGENT). non-tool 완화만으로 두 판정 뒤집기 시도 가능. tool 경로 완화는 이 목표에 불필요.
2. **§6.1 gate 축 자동 보증** — tool 입구 검증기 유지되어 `waste_span_ids sha256`, `id_bridge_candidates` (tool-only pool), `between_window` (tool 만 스캔) 모두 자동 무변. 재검증 부담 없음.
3. **"한 층 원칙" 논지 재평가** — Model validator 와 cascade skip 은 서로 다른 concern 이다:
   - Validator: `Span` 객체의 **구조적 불변식** (invalid data 구성 자체 방지).
   - Cascade skip: 이 span 이 **의미상 판정 대상인가** (matchable 여부).
   
   "같은 원칙 두 층" 프레이밍은 aesthetic argument. 실제로는 다른 계약. (b'-좁게) 가 원칙 위반이 아니라 **역할 분업** 이다.
4. **점진적 확장 · reread 선례** — 작게 시작하고 증거 확보 후 확장. (b'-넓게) 로 완전 정합을 노리는 것은 "먼저 이상형에 맞춘다". 프로젝트 관행은 반대. (b'-넓게) 는 (b'-좁게) 로 dev-7 FPR 0.0 · T1.2/T1.4 재판정 성공 확증 후 **별건 사전등록 후보**.

### §2.5 구체 변경 (설계상, 실 구현 승인 후)

**`src/clew/model.py:38-43`**:

```python
# 현재 (모든 span 이 non-empty 요구)
@field_validator("output_text")
@classmethod
def _output_text_non_empty(cls, v: str) -> str:
    if not v.strip():
        raise ValueError("output_text must be non-empty after strip (★ SPEC §8 1.1)")
    return v

# 변경 후 — tool span 만 non-empty 요구 (§2.4 근거 2 · 구조적 불변식)
@model_validator(mode="after")
def _output_text_non_empty_on_tool(self) -> Span:
    if self.span_kind == "tool" and not self.output_text.strip():
        raise ValueError(
            "tool span output_text must be non-empty after strip "
            "— structural invariant: a tool call with no output is invalid data"
        )
    return self
```

**`src/clew/detect/cascade.py:66` 앞** (non-tool 분기 진입 전, §2.1 원칙 · "부재 두 개는 판정 대상 아님"):

```python
# 변경 후 (non-tool cosine 분기 앞)
if candidate.span_kind != "tool":
    if not (origin.output_text.strip() and candidate.output_text.strip()):
        continue        # ← 부재 vs 부재 · 부재 vs 값 판정 대상 아님
    if cosine(embedder.embed(origin.output_text), embedder.embed(candidate.output_text)) >= phi:
        ...
```

**★ SPEC.md §8 1.1 문면 갱신 이번 커밋에 포함** — 검증기 범위 변경 반영 (참조 정합).

**cascade tool 분기 (`cascade.py:62`) 는 변경하지 않는다** (b'-좁게, §2.4 근거 1·2).

---

## §3 — ★ downstream 영향 예측 (구현 전 확정, §4 KILL 기준의 근거)

각 항목에 대해 **예측**을 결과 보기 전에 박아둔다. 실측 결과 예측과 어긋나면 그것을 정보로 삼는다 (KILL 여부는 §4 임계로 판단).

### §3.a cascade sha256 (tool 분기)

- **예측**: (b) 채택 시 tool span 은 여전히 non-empty → 빈 문자열 매칭 위험 없음. `waste_span_ids sha256 = cand 5c0c94d6…, pair 742b51a7…` **무변**.
- **검증 방법**: Toolathlon 재실행 · 두 sha 값 대조.

### §3.b cascade φ (non-tool 분기, 임베딩 유사도)

- **실측 (구현 전, 사전 측정)**:
  - 동결 모델 `paraphrase-multilingual-MiniLM-L12-v2 @ rev e8f8c211…`, φ = 0.514345.
  - `cosine(embed(""), embed(""))` = **1.000000** · φ 훨씬 초과 (거의 2 배).
  - `cosine(embed(""), embed(<normal text>))` — 7 개 샘플 전부 φ 미만 (0.009 ~ 0.315).
  - 위험은 **빈-vs-빈 한 축에 국한**. 빈-vs-정상 text 는 안전.
- **§2.1 원칙 반영**: 빈 값 두 개가 cosine=1.0 이 나오는 것이 사후에 발견된 사고가 아니라 **애초에 판정 질문 자체가 잘못된 케이스**. 부재끼리 비교하면 안 된다.
- **(b'-좁게) 채택 예측**: `cascade.py:66` 앞에 `if not (origin.output_text.strip() and candidate.output_text.strip()): continue` 삽입. 빈-vs-빈 · 빈-vs-값 모두 판정 대상에서 제외. **cascade φ (non-tool) waste 결과 무변** (dev-7 재실행 대조).
- **검증 방법**: dev-7 재실행. 완화 전 (main) waste_span_ids 개수 · trace-level FPR (=0.0) 과 대조. 무변 시 예측 확정.

### §3.c 리포트 스니펫 렌더 (JSON · Markdown)

- **위치**: `json_report.py:97` (`entry["snippet"] = wd.candidate.output_text[:snippet_len]`), `markdown.py:563` (`snip = wd.candidate.output_text[:snippet_len]`).
- **예측**: 빈 문자열 슬라이스는 빈 문자열. 리포트에 `snippet=""` 이 렌더될 뿐 렌더 실패 없음. 다만 사용자 경험상 빈 스니펫은 `"(no output)"` 같은 명시적 안내가 필요할 수 있음.
- **결정**: 이번 스코프에 렌더 문면 개선 포함 안 함. 재판정 시 관찰만 기록. 문면 개선은 별건.

### §3.d amplification 토큰 추정

- **위치**: `cost/amplification.py:131` (`if s is None or not s.output_text: continue`).
- **예측**: 이미 빈 output_text 를 skip 한다. `n_skipped_no_metadata` 카운트가 상승할 뿐 amplification 값 자체 무영향.
- **검증 방법**: Toolathlon 재실행 시 amplification 결과 필드 대조 (기존 amplification 결과가 있으면 무변).

### §3.e between_window 분류

- **위치**: `_enrich.py:_classify_between_window`.
- **예측**: `span_kind`, `agent_or_node_id`, timestamp 만 읽음. `output_text` 안 봄. **무영향**.
- **검증 방법**: Toolathlon `between_window` 5-카운트 대조 (예상 1226/888/405/248/1024 무변).

### §3.f id_bridge (raw_output_text fallback 과의 상호작용)

- **위치**: `_enrich.py::scan_id_bridge_candidates` — `raw_output_text or output_text` fallback.
- **예측**: id_bridge pool 은 `cand.span_kind == "tool"` + `agent_or_node_id in side_effect_pool`. (b) 채택 시 tool span 은 여전히 non-empty 이므로 id_bridge 로 들어가는 span 무변. **완전 무영향**. 159/76/3197 무변.
- **검증 방법**: `test_id_bridge_toolathlon_distribution_reproduces_pool_a` 재실행.

### §3.g 종합 예측 표

| 축 | 예측 (b'-좁게 채택) | 임계 (§4 KILL 조건 참조) |
|---|---|---|
| §3.a cascade sha256 (tool) | 무변 (`5c0c94d6…` / `742b51a7…`) | ★ 변화 = 즉시 KILL |
| §3.b cascade φ (non-tool) | **무변** — 사전 측정 `cos(empty,empty)=1.0` 로 빈-vs-빈 매치 위험 확정됐으나 `cascade.py:66` 앞 skip 로 판정 대상에서 제외 | dev-7 trace FPR 상승 > 0 = KILL |
| §3.c 리포트 스니펫 | 렌더 실패 없음, 빈 스니펫 렌더 | 별건 문면 개선 |
| §3.d amplification | 값 무변 | 값 변화 = KILL |
| §3.e between_window | 무변 (1226/888/405/248/1024) | ★ 변화 = KILL |
| §3.f id_bridge | 무변 (159/76/3197) | ★ 변화 = KILL |

---

## §4 — ★ KILL 기준 (결과 보기 전 확정, 불가침)

**★ 완화 후 다음 중 하나라도 발생하면 즉시 KILL — 원복. 고쳐서 살리지 않는다** (reread 선례: `docs/REREAD_DETECTOR_PREREG.md` §11.2 KILL verdict 그대로 준수).

### §4.1 즉시 KILL 조건 (하나라도 발동 시)

1. **`waste_span_ids sha256` 변화** — cand `5c0c94d6…` 또는 pair `742b51a7…` 중 하나라도 다른 값이 나오면 KILL.
2. **`between_window_counts` 변화** — `1226/888/405/248/1024` 중 하나라도 다르면 KILL.
3. **`id_bridge_candidates` 분포 변화** — `159/76/3197` 중 하나라도 다르면 KILL.
4. **`eval/set_manifest.json` sha 변화** — 재동결 필요 시 재동결이 아니라 KILL (검증기 완화가 seed=42 트레이스 생성에 영향 주면 안 됨).
5. **dev-7 trace-level FPR 상승** — 현재 `dev-7 trace-level FPR = 0.0` (CRITERIA_FROZEN.md `Stage 2 results` 기록). 완화 후 재실행 시 FPR > 0 이면 KILL. 즉 새 false positive 하나라도 발생 시.
6. **기존 pytest 회귀** — 445 → 449 → 451 chain 에서 회귀 발생 시 KILL (완화가 정상 span 을 거부하는 케이스로 몰면 test_model / test_roundtrip / adapter test 가 실패).

### §4.2 KILL 시 대응

- 커밋 revert. `Span._output_text_non_empty` 원 검증기 복원.
- 이 사전등록 문서에 KILL verdict 부기 (reread 선례 그대로 · §11 형태).
- **완화 자체를 재시도하지 않는다**. 별건 사전등록으로 다른 방식 검토 (예: 특정 어댑터 shim 에서 output.value 부재 시 placeholder 주입).
- 완화가 성공하지 못했다는 사실은 다음 릴리스 노트에 명시. FAIL 3 → PASS 로 갱신 시도가 없었음을 공개.

### §4.3 KILL 이 아닌 관찰 (기록만)

- Non-tool span 에 빈 output_text 가 새로 들어옴 (dev-7 에서 카운트).
- 리포트 스니펫에 빈 값 렌더 (JSON `snippet=""` / Markdown 공백).
- amplification `n_skipped_no_metadata` 카운트 상승 (단 값 자체는 무변).
- Tier 1 재판정 결과: T1.2/T1.4 이 PASS 로 갱신되는지, PARTIAL 로 완화만 되는지, 여전히 FAIL 인지.

**이런 관찰들은 완화 자체가 실패했다는 신호가 아님**. §4.1 이 KILL 축.

---

## §5 — 재판정 계획

### §5.1 대상

- **Tier 1 4 개 프레임워크 재판정** — 완화 후 §3 판정을 다시 매김.
- **Focus**: T1.2 OpenAI Agents · T1.4 AutoGen — FAIL 원인이 R2 였으므로 완화로 PASS 가능성.
- **PASS 유지 확인**: LangChain / CrewAI / LlamaIndex — 새 검증기가 이들 판정을 뒤집지 않는지.
- **T1.3 Anthropic**: FAIL 원인 R5 (multi trace_id) — R2 완화 무관. **재판정 예상 결과 = FAIL 유지**. R2 완화가 이 케이스에 영향 없음을 확증.

### §5.2 ★ 기존 dump 재사용 vs 새로 뜨기 — 결정

**기존 dump 재사용 채택**. 근거:

1. **Baseline 통제**: 기존 dump 는 사전등록 §6 (Tier 1) 절차대로 만들어진 실측. 재-dump 하면 새 조건 (SDK/instrumentor 버전 · Stub 응답 스크립트 순서 등) 이 개입해 판정 원인이 어댑터 완화인지 dump 변화인지 구분 불가.
2. **본 사전등록의 검증 대상은 우리 어댑터의 R2 완화** — 그 상수만 바꾸고 동일 dump 로 재판정하면 R2 완화의 순수 효과 측정.
3. **비용**: LLM 비용 0. Probe 재구현 필요 없음.
4. **재판정 규칙 (§3.4 Tier 1) 준수**: "판정은 dump 하나당 1 회. 프레임워크 여러 dump 가 있으면 최악 등급 채택" — 기존 dump 는 이미 판정 자원. 여기 완화 후 재판정 결과를 추가로 표기.

**재-dump 시나리오는 별건**: upstream (instrumentor) fix 여부 확인이 목적이면 별건 조사. 이번 스코프 아님.

### §5.3 재판정 산출물

**`docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` §1.1 (판정 요약 표) 갱신**:

- T1.2 / T1.4 에 "R2 완화 후 재판정: PASS / PARTIAL / FAIL 중 실측 결과" 별도 컬럼 추가.
- 원 판정 (R2 stricter 시점) 은 유지. 어긋난 경우 이유 표기.
- §3 자기공개 문면 유지 · 완화 결과 병기.

**변경 커밋**: `docs(results): T1.2 · T1.4 재판정 (R2 완화 후)` — 이번 사전등록 chain 의 마지막 커밋 (§9).

---

## §6 — 불가침 (실패 시 KILL, §4 참조)

### §6.1 값 무변 (§4.1 KILL 조건)

- `waste_span_ids sha256`: `cand=5c0c94d680fe4741dd5df6d3cc928a0bba59af6c595e7037df088926b04d47d4`, `pair=742b51a75b67648cedf14d37cf9ea9d4dbc5d9237fe5ee798eeb2c1455fd45a0`.
- `between_window_counts`: `1226/888/405/248/1024`.
- `id_bridge_candidates`: `differ/same/no_id = 159/76/3197`.
- `eval/set_manifest.json` sha256: `a205a3d62e8310f67f0ab1a7faa957504b9f486a8c5a68cebeadf010aff42952`.
- `coverage_stats` 6 필드.

### §6.2 탐지 로직 · 동결 파라미터

- φ = 0.514345, N = 2, embedding model `paraphrase-multilingual-MiniLM-L12-v2 @ rev e8f8c211…`.
- `cascade` / `structural` / `semantic` 로직.
- `_ID_BRIDGE_MAPPING` 26 도구.
- `raw_output_text` fallback 규약 (`_enrich.py::scan_id_bridge_candidates`).
- `preprocess_trace` 호출 위상 (langgraph.py:225 유일, H 확증).

### §6.3 dev-7 FPR = 0.0 baseline

- CRITERIA_FROZEN.md "Stage 2 results" 기록: `dev-7 trace-FPR 0.00`.
- 완화 후 재실행 값 > 0.0 → §4.1 KILL 조건 발동.

---

## §7 — 범위 밖

| 항목 | 이유 |
|---|---|
| Tier 2 조사 | 별건 (사전등록 §5.3 예산 규칙: R2 완화 완료 후 Tier 2 진행 여부 결정). |
| `extract_output_text` leaf 규칙 재설계 | 별건. Tier 1 §7 한계 유지. |
| Instrumentor upstream fix 모니터링 | 별건 (Arize-ai/openinference issue #3337 · #3392). |
| 리포트 스니펫 문면 개선 (빈 값 시 `"(no output)"` 등) | 별건 · §3.c 관찰만. |
| Anthropic (T1.3) 재판정 대응 | R2 무관 원인 (R5 multi trace_id) — 이번 완화로 결과 안 바뀐다. FAIL 유지 예상 · 결과만 재확인. |
| 웹앱 · 홈페이지 반영 · README 갱신 | 재판정 결과 확정 후 별건. |

---

## §8 — Open Questions (승인 전 사용자 확정)

| # | 질문 | 초안 답 |
|---|---|---|
| Q1 | **(b'-좁게) 채택** — `Span._output_text_non_empty` 는 `span_kind == "tool"` 조건에서만 유지 (입구 · 구조적 불변식) + `cascade.py:66` non-tool 분기 앞에 empty skip 삽입 (판정층 · "부재 두 개는 판정 대상 아님"). tool 분기 (`cascade.py:62`) 는 무변. (b'-넓게 · cascade tool 분기까지 skip · validator 완전 제거) 는 §2.4 근거 4 대로 **별건 사전등록 후보** — narrow 로 실측 확증 후. | 예상 유지. |
| Q2 | KILL 임계 목록 (§4.1) 완전한가? 다른 축 필요? | 초안 유지. **★ Q2b 기각** — dev-7 FPR > 0 을 > 0.05 로 완화하지 않는다. 근거: dev-7 FPR = 0.0 은 Stage 2 에서 동결된 값이고, 이번 변경이 그걸 깨면 그건 실패다. 임계를 완화하는 것은 결과 보고 기준을 바꾸는 것 (사전등록 목적 위반). |
| Q3 | 기존 dump 재사용 (§5.2) | **동의** — baseline 통제 · 완화 순수 효과 측정을 위해 재사용. |
| Q4 | SPEC.md §8 1.1 문면 갱신 이번 커밋에 포함 | **동의** — 참조 정합 위해 완화 커밋 시 함께 갱신. |
| Q5 | Tier 1 결과 리포트 §1.1 갱신 시 컬럼 추가 방식 | **동의** — "재판정: R2 완화 후" 컬럼 추가. **★ 원 판정을 덮어쓰지 않는다.** 사전등록 §3 기준으로 내린 판정 (Tier 1 결과 리포트 landed 시점) 이 기록으로 남아야 한다. 컬럼 병기만 허용. |
| Q6 | 완화 커밋 후 v0.4.1 patch bump? 아니면 main 에 두고 다음 릴리스에 합류? | **★ 재판정 결과를 보고 정한다.** 이 작업의 목표는 릴리스가 아니라 T1.2/T1.4 재판정이다. 결과를 모르는 상태에서 릴리스 계획을 확정하지 않는다. 재판정이 PASS 로 갱신되면 그 자체가 사용자에게 노출할 가치가 있는 변경이고, FAIL 유지면 릴리스에 담을 것이 없다. 결과 후 별건 결정. |

---

## §9 — 커밋 체인 (설계상, 사전등록 승인 후)

**★ PR 없이 바로 구현 · 3 커밋**:

1. `feat(model): relax R2 to tool spans only` —
   - `src/clew/model.py::Span::_output_text_non_empty` → `_output_text_non_empty_on_tool` (model_validator 로 변경).
   - `SPEC.md §8 1.1` 참조 문면 갱신 (완화 정합).
   - `tests/test_model.py` — 회귀 갱신 (기존 `test_output_text_required_non_empty` 는 tool span 만 대상으로 변경 · non-tool 케이스 새 assertion).
2. `test(model): downstream freeze regression under R2 relaxation` —
   - `tests/test_between_window.py`, `tests/test_id_bridge.py`, `tests/test_coverage_transparency.py`, `tests/test_dod.py` — 재실행 통과 확인. 새 회귀 필요 없으면 삽입 없음.
   - dev-7 FPR 확인용 script/assertion (`tests/test_evaluate_reproducible.py::test_per_pattern_dev_direct` 유지 확인).
3. `docs(results): T1.2 · T1.4 재판정 (R2 완화 후)` —
   - `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` §1.1 컬럼 추가.
   - Anthropic (T1.3) 재판정 결과 (FAIL 유지 예상) 기록.
   - LangChain / CrewAI / LlamaIndex PASS 유지 확인.

**전체 pytest 통과 후 push. PR 사용자 개설.**

**KILL 발동 시**: 이 세 커밋을 revert. §11 (Results §11-형태) verdict 추가.

---

## §10 — 참조

### 사전등록
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` — Tier 1 판정 기준 원.
- `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` — §3 자기공개 · 이번 사전등록의 근거.
- `docs/REREAD_DETECTOR_PREREG.md` §11 — KILL 대응 선례.

### 코드
- `src/clew/model.py:38-43` — 완화 대상 검증기.
- `src/clew/detect/cascade.py:62,66` — cascade sha256 (tool) · φ (non-tool) 분기 · §3 예측 근거.
- `src/clew/cost/amplification.py:131` — 빈 output_text skip 확인.
- `src/clew/report/_enrich.py::_classify_between_window` — output_text 참조 없음 확인.
- `src/clew/report/_enrich.py::scan_id_bridge_candidates` — tool 만 참조, 무영향.

### 실측·측정
- `field_test/diagnostics/framework_expansion_dumps/` — Tier 1 dump (재사용 대상).
- `eval/dev/seed-7/` — dev-7 FPR baseline (0.0) · 완화 후 재실행 대상.
- `validation/CRITERIA_FROZEN.md` — Stage 2 results 기록.

### Memory
- `memory/feedback_intentional_drift.md` — 완화가 정당한 변경일 때 회귀 처리 원칙.
- `memory/feedback_prereg_vs_local_design.md` — docs/ 커밋 판단 기준 (임계값 있으므로 docs/).
- `memory/reference_reread_kill_doc.md` — reread KILL 선례.
- `memory/project_pingpong_blocked.md` — BLOCKED / KILL 위상 정정 (혼동 방지).

### Upstream 참고
- Arize-ai/openinference [Issue #3337](https://github.com/Arize-ai/openinference/issues/3337) (OpenAI Agents parent spans missing input/output) — 우리 R2 완화 필요성 배경.
- Arize-ai/openinference [Issue #3392](https://github.com/Arize-ai/openinference/issues/3392) (Anthropic tool helpers) — 별건 (R5 원인).

---

## §11 — Verdict (2026-08-01 실행 후 기록)

**실행 커밋**: `feat/r2-relaxation` 브랜치, commit `421bfbf` (feat(model+cascade): scope R2 to tool spans).

### §11.1 §3 예측 대조 (전부 일치)

| 축 | 예측 | 실제 |
|---|---|---|
| §3.a cascade sha256 (tool) | 무변 (`5c0c94d6…` / `742b51a7…`) | ✓ 일치 (`test_waste_span_ids_bit_identical_post_id_bridge` PASS) |
| §3.b cascade φ (non-tool) | 무변 (skip 삽입으로 empty pair 판정 대상 제외) | ✓ 일치 (dev-7 FPR 0.0 유지 · 신규 cascade skip 3 test PASS) |
| §3.c 리포트 스니펫 | 렌더 실패 없음 | ✓ 일치 (report render test PASS) |
| §3.d amplification | 값 무변 | ✓ 일치 |
| §3.e between_window | 무변 (1226/888/405/248/1024) | ✓ 일치 |
| §3.f id_bridge | 무변 (159/76/3197) | ✓ 일치 |

### §11.2 §4 KILL 6 축 (전부 통과)

1. `waste_span_ids sha256` cand=5c0c94d6… / pair=742b51a7… — 무변.
2. `between_window_counts` 1226/888/405/248/1024 — 무변.
3. `id_bridge_candidates` 159/76/3197 — 무변.
4. `eval/set_manifest.json` sha `a205a3d6…` — 무변.
5. dev-7 trace-level FPR — **0.0 유지**.
6. 전체 pytest — 455 passed (451 baseline + 4 신규), 실패 0.

### §11.3 ★ §5 재판정 목표 — 미달 (adapter 층 gate 발견)

**T1.2 · T1.4 재판정 결과**: R2 완화 후에도 **FAIL 유지**.

원인: `src/clew/ingest/langgraph.py:169-173` 에 **세 번째 empty-check** 이 존재. Non-tool span 이 ingest 단계에서 이 check 로 거부되어 cascade layer 에 도달하지 못한다.

```python
# langgraph.py:169-173 — 사전등록 §2.5 목록에 없던 지점
if not output_text.strip():
    raise ValueError(
        f"span {s.name!r} ... has empty output.value — adapter refuses to construct invalid Span"
    )
```

**T1.2 재-ingest 시도** (기존 dump 재사용 · §5.2):
- OA-primitive: `probe_workflow has empty output.value` → FAIL at adapter layer.
- OA-Runner: `turn has empty output.value` → FAIL at adapter layer.

**T1.4 재-ingest 시도**:
- AutoGen: `TicketAgent.on_messages_stream has empty output.value` → FAIL at adapter layer.

**T1.1 · T1.3**:
- T1.1 LlamaIndex: OK (5 spans) — 이미 PASS 였으므로 변화 없음.
- T1.3 Anthropic: FAIL — R5 (multi trace_id) 원인, R2 무관. 예상대로.

### §11.4 ★ 완화가 실제로 발동했는가 — 확인 결과

사용자 지적: `§3.b~§3.g` 의 "무변" 확증이 "skip 이 작동해서" 인지 "빈 non-tool span 이 애초에 파이프라인에 없어서" 인지 구분 필요.

**실측 카운트** (3 코퍼스, R2 완화 후 · adapter 통과 이후):

| 코퍼스 | 총 spans | 빈 output_text (non-tool) | 빈 output_text (tool) |
|---|---|---|---|
| dev-7 (checked-in Trace JSON) | 480 | **0** | 0 |
| Toolathlon (66 files) | 183,050 | **0** | 0 |
| CC (3 files) | 356 | **0** | 0 |

★ **결론**: **완화는 발동한 적 없다.** §11.1 의 §3.b-g "무변" 확증은 skip 로직이 안전함을 증명하지 않는다. **skip 로직 자체의 유효성은 3 개 신규 cascade test 만이 보장** (`test_non_tool_empty_pair_skipped_before_cosine`, `test_non_tool_empty_vs_value_pair_skipped`, `test_non_tool_non_empty_pair_still_evaluated` — 합성 데이터로 skip 경로 직접 exercise).

이 사실은 §5 재판정 미달 (§11.3) 과 인과 관계가 있다: **어댑터 층 gate 가 빈 non-tool span 을 이전부터 이미 막고 있었다**. 우리가 완화한 두 layer (Span validator · cascade skip) 는 실 데이터로는 한 번도 발동 안 함.

### §11.5 후속

- **별건 사전등록 필요**: `docs/ADAPTER_R2_RELAXATION_PART2_PREREG.md` (or similar).
  - 스코프: `langgraph.py:169-173` adapter-layer empty check 를 tool-only 로 scope.
  - 그 사전등록에서 §3 다시 짜라 — 어댑터 층 gate 를 열면 실제로 빈 non-tool span 이 cascade 까지 도달하게 되므로, dev-7 FPR 실측이 skip 유효성 실증이 될 수 있다.
  - 이번 사전등록에서 이 지점을 놓친 것은 실측 확증 부재 때문. Part 2 는 어댑터 코드 실측 후 작성.
- **이번 커밋 revert 하지 않음**: §4 KILL 6축 전부 통과, §3 예측 전부 일치. 완화가 발동 안 했다 = 완화가 실패했다는 뜻이 아님. Part 2 에서 어댑터 layer 를 열면 이 layer 의 skip 이 정확히 필요해진다.

### §11.6 요약 한 줄

**Prereg 자체는 성공: §4 6축 통과, §3 예측 일치. 재판정 목표는 미달 — 사전등록이 어댑터 층 gate 존재를 놓쳤다. 완화가 실 데이터로는 발동 안 함 (skip 유효성은 합성 test 만 보장). 별건 Part 2 로 진행.**
