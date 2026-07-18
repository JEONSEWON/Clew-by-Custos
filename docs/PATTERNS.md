# Clew — 낭비 패턴 정밀 진단 로그

프로젝트가 광고하는 3개 낭비 패턴 (repeat_node / pingpong / requery_known) 각각의
코드 상 실제 상태와 실측 검출 사례를 정직하게 기록한다. 탐지 로직·frozen 파라미터는
건드리지 않고 관측 사실만 정리한 fold-back 로그.

## §28 — 낭비 패턴 3종 정밀 진단 (2026-07-18)

### repeat_node — 실작동 (유일한 실측 검출 경로)

- 함수: `find_repeat_candidates(trace, n)` (`src/clew/detect/structural.py:48`).
  N=2 는 window 가 아니라 **occurrence count threshold** (§25).
- 하위그룹 키:
  - `span_kind == "tool"` → `(agent_or_node_id, _normalize_input(input_text))`
    (`structural.py:20`: `strip().casefold()`)
  - 그 외 kind → `(agent_or_node_id, None)`
- SPEC §16 parent-AGENT gate: 두 스팬의 가장 가까운 조상 AGENT 가 다르면 후보 제외.
- 실측 검출:
  - CC 5+ 사례 (§22.11.8, 세션 2502fe9a 등)
  - RedundancyBench 218 예측 (§24.7, F1=0.2642 precision=0.8258)
  - Toolathlon 22모델 스캔 8,042 waste (§26) — 전량 이 함수 경로

### pingpong — 구현됐으나 실측 0건 (이중 봉쇄)

- 함수: `find_pingpong_candidates(trace)` (`structural.py:80–104`).
- 발동 조건: 시간순 4-window `A→B→A→B` 가 (a) 4스팬 전부 `span_kind == "llm"`
  AND (b) `agent_or_node_id` 가 `A == A' ≠ B == B'` AND (c) 순수 인접
  (`ordered[i], ordered[i+1], ordered[i+2], ordered[i+3]`). 매우 협소한 패턴
  (multi-agent supervisor/worker 라우터 왕복 이론상).
- **봉쇄 ①** — 어댑터가 LLM 스팬을 만들지 않음:
  - `src/clew/ingest/claude_code.py:212–227` : 모든 스팬 `span_kind="tool"` 하드코딩.
    `claude_code.py:152–154` 는 `thinking`/`text` 블록을 스팬화하지 않음 (§22.3).
  - `src/clew/ingest/toolathlon.py:6` docstring: "synthetic CHAIN root + tool 스팬만".
  - `src/clew/ingest/redundancy_bench.py:216–230` : matched_pair 를 전부
    `span_kind="tool"` 로 생성. assistant 텍스트 미스팬화 (§24.2).
- **봉쇄 ②** — OTel/LangGraph 는 LLM 스팬을 만드나 preprocess 가 제거:
  - `src/clew/ingest/langgraph.py:32–38` `_KIND_MAP` : `"LLM": "llm"` 매핑 존재.
  - 공식 진입점 `ingest_otel_spans` (`langgraph.py:148–161`) 는 항상
    `preprocess_trace()` 호출.
  - `src/clew/ingest/preprocess.py:94–146` `collapse_llm_spans` 가 `span_kind == "llm"`
    스팬을 **전부 제거** (token_count 는 부모 chain 으로 rollup, ReAct 자식 re-parent).
  - 결과: OTel/LangGraph 를 통과한 트레이스에도 llm 스팬 zero → pingpong 항상 0.
- **유일 발동 경로**: `eval/generators/patterns/pingpong_aba.py` (synthetic).
  Trace 를 직접 구성해 preprocess 우회, `span_kind="llm"` 직접 지정
  (line 54, 63, 72, 81). synthetic F1=0.857 평가의 pingpong 성분은 이 경로 전용.
- 실측 어댑터 산출물 3종 (CC 6,780 tool 스팬 / Toolathlon 176,270 tool 스팬 /
  RB 1,628 tool 스팬) 전부 0건.
- **정직 표기**: "구현됨 ≠ 관측됨". 코딩·도구 에이전트는 단일 에이전트가 지배적이라
  A→B→A→B LLM 왕복이 원리적으로 없음. 멀티에이전트 트레이스 확보 시
  (1) 실제 왕복 존재 확인 (2) pingpong 정의 적합성 리콘 (3) llm 스팬 활성화
  → 검증 후 켠다. **검증 전 미광고.**

### requery_known — 별도 함수 없음, repeat 의 tool 하위그룹으로 흡수

- `structural.py:1–13` 주석:
  > "requery: 반복 tool 노드의 특수형 → 하위그룹핑이 그대로 작동."
- 정의: `requery ≡ (repeat AND span_kind == "tool" AND normalize(input) 일치)`.
- `find_repeat_candidates` 의 tool 하위그룹 키가 `(name, normalize(input))` 이므로
  같은 도구·같은 인자 재호출은 자연스럽게 같은 그룹으로 묶임. 별도 detect 함수
  불필요 = **재발명 회피, 설계상 옳음**.
- 실측 커버리지:
  - RedundancyBench `duplicated step` (요구리 라벨) recall 0.6077 (79/130,
    `docs/REDUNDANCY_BENCH.md §24.4`).
  - Toolathlon 8,042 waste 는 전량 tool 스팬 → 전량 이 경로.
- 미탐 40% (RB 51 miss 중 30건 gap≥6): N=2 는 occurrence count 이지 window 가
  아니라 커버 불가 (§24.9 / §25). Recall ceiling 로 문서화 완료.

### §28.1 — 라벨 스킴 백로그 (detect 무변경, Phase 2 후보)

**현재 상태 — 패턴 라벨 미보존**:
- `CascadeResult` (`src/clew/detect/cascade.py:32–37`) 필드: `waste_span_ids: list[str]`.
  패턴 라벨 필드 없음 (flat list).
- `find_candidates` (`structural.py:107–117`) 는 `find_repeat_candidates` +
  `find_pingpong_candidates` 결과를 합쳐 `list[tuple[Span, Span]]` 반환. 어느 패턴에서
  온 페어인지 정보 소실.
- `src/clew/report/markdown.py:73` 의 "repeat_node" 는 컬럼 헤더일 뿐
  (재등장 스팬의 `agent_or_node_id` 를 표시). 패턴 라벨이 아님.

**최소 변경안 (frozen·게이트·임계 무영향, pre-1.0 스키마 확장)**:
1. `find_candidates` 반환에 kind 태그 추가:
   `list[tuple[Span, Span, str]]` where kind ∈ {`"repeat"`, `"requery"`, `"pingpong"`}.
   또는 새 함수 `find_candidates_labeled`.
2. `CascadeResult.waste_labels: dict[str, str]` 필드 추가 (span_id → 패턴 이름).
3. `markdown.py` / `json_report.py` 렌더러에 "pattern" 컬럼 추가.
4. requery 는 `(repeat AND kind == "tool" AND normalize(input) 일치)` 파생 라벨.
   별도 detect 함수 신설 안 함.

**가치**: report 구체화 (Toolathlon 8,042 "전량 requery" 라벨 가능, RB duplicated
recall 을 report 에 직접 명시).

**리스크**: 없음 (탐지 결정 무변, 테스트 대부분 그대로).
**로드맵 밖 — 별도 판단**.
