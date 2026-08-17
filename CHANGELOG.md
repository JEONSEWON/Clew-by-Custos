# Changelog

All notable, user-visible changes to `boxdawn` (previously published on PyPI as `clew-custos`). This file tracks releases going forward — earlier versions are not back-filled because the criteria for what qualifies as user-visible were not established at the time.

## Unreleased — Rebrand to Boxdawn

### ★ Breaking (packaging + CLI)

- **PyPI package renamed:** `clew-custos` → `boxdawn`. Install with `pip install boxdawn` (previously `pip install clew-custos`). Users on `clew-custos` remain functional at the last published version (0.4.1) but will not receive further updates under that name.
- **CLI entry point renamed:** `clew analyze …` → `boxdawn analyze …`. The old `clew` script is no longer installed. `python -m clew analyze` still works as a fallback because the Python module name is unchanged.
- **Report header:** `# Clew Waste Report` → `# Boxdawn Waste Report`. CI scripts that grep the header must be updated.

### 무변경

- **Python import path:** `import clew` (and every submodule underneath) is unchanged. Existing user code that does `from clew.metrics import compute_waste_rate` continues to work without modification.
- **User config file name:** `clew.yaml` is kept for backward compatibility with existing configs. Not renamed to `boxdawn.yaml`.
- **Detection logic · frozen parameters:** φ=0.514345, N=2, embedding model rev — all unchanged. sha256 gates, cascade, WR_char / WR_cost / SDR@10 all bit-identical.

### 릴리스 이유

Rebrand from Clew (product) + Custos (company) two-name structure to a single Boxdawn brand. The product domain `hubble.ai` (originally paired with the Clew name after 6 branding attempts) was already held by a live YC-backed healthcare SaaS at rebrand time, breaking the domain anchor. Unifying to Boxdawn (company = product = `boxdawn.com` / `boxdawn.ai`) eliminates the two-name overhead for early-stage brand build.

## 0.4.1 — 2026-08-03

### 변경

- 리포트 상단 `## Result` 배너가 두 축을 함께 표시한다: **Waste detection** 과 **Duplicate creation check**. 이전에는 `wasteful=False` 일 때 상단이 `no waste detected` 만 찍고 duplicate creation 결과는 하단에만 있어서, 중복 생성이 탐지된 트레이스에서도 상단이 "낭비 없음" 으로 읽혔다. 이번 릴리스는 그 자기 모순을 없앤다.
- `## Result: WASTE DETECTED` 헤더가 `## Result` + `Waste detection: N wasteful span(s).` 로 통일. cascade=True / cascade=False 두 브랜치가 같은 문면을 쓴다.
- Duplicate creation check 요약은 항상 세 숫자 (`differ` / `same` / `no_id`) 를 분리 표시한다. 절대 하나의 합계로 접지 않는다.
- Framed as **"Detection, not confirmed impact."** — cascade waste 와 duplicate creation 을 같은 신뢰도 층으로 취급하지 않는다.

### 무변경 (sha256 검증)

- 탐지 로직 — cascade / structural / semantic / `_ID_BRIDGE_MAPPING` / `scan_id_bridge_candidates` 무수정.
- 동결 파라미터 — φ=0.514345, N=2, model rev `e8f8c211…`.
- `waste_details` · `between_window_counts` · `id_bridge_candidates` · `waste_span_count` · `wasteful` 다섯 필드의 report.json sha256, 두 검증 트레이스 (grok-4_2 line 83, claude-4-sonnet-0514_1 line 4) 에서 전부 동일.
- Duplicate creation check 섹션 본문 (`ID_BRIDGE_PRODUCTION_PREREG.md` §1.4 frozen) — 섹션 헤더, 서두 문단, per-candidate 3-way 문면 (`differ` / `same` / `no_id`) 무수정.
- report.json 스키마 · CLI 인터페이스 무변경.
- `tests/test_between_window.py` §3.2 금지어 가드 (`confirmed waste` / `verified waste` / `proven waste` / …) 유지. "provable" 단어 렌더러에 미사용 유지.

### 테스트 갱신 (회귀 아님, 계약 변경)

- `test_coverage_line_a_present_in_waste_detected` · `test_coverage_line_c_renders_in_waste_detected`: 배너 문자열이 `Result: WASTE DETECTED` → `## Result` + `wasteful span` 로 이동해서 assertion 업데이트.
- `test_readme_example_has_coverage_banner` · README `Result:` fenced 예제: 새 문면에 맞게 regex 와 예제 텍스트 동시 갱신.
- 사전등록 없이 진행된 변경이라 §3 예측 목록이 없었다. 다음부터 문면 변경 시 깨질 테스트를 먼저 열거한다.

### 릴리스 이유

pip-installed 사용자의 3-command 재현 시나리오 (`pip install clew-custos && ... && python -m clew analyze case.jsonl`) 가 정정된 배너를 보려면 새 배포가 필요하다. v0.4.0 이 이미 PyPI 에 있으므로 v0.4.1 로 올린다.

---

## 0.4.0 — 2026-08-01

### ★ Breaking

- **`Span` model gains an optional `raw_output_text` field** (`ce0996c`).
  `Span` still uses `ConfigDict(extra="forbid")`, so **an older version of `clew` cannot open a trace JSON that this version wrote.** This version still opens files produced by older versions (the new field defaults to `null`). The break is one-directional.

  Impact: if you `capture_to_file(...)` (or otherwise persist a `Trace` JSON) with 0.4.0 and then try to load that file with an older `clew` install, `load_trace(...)` raises `ValidationError`. Upgrade the reader to 0.4.0 or newer.

  Rationale: `raw_output_text` preserves the tool span's original response bytes so `id_bridge` extraction survives `preprocess_trace`'s `extract_output_text` step. Full context in `openinference_output_text_fix_PREREG.md` v3 §2.1 (local design doc).

### New features (user-visible)

- **OpenInference adapter — LangChain and CrewAI traces.** `ingest_from_otel_json` (SDK JSON array, Format A) and `ingest_from_openinference_json` (nested dict, Format C) both route to a common `ingest_otel_spans` path with `_agent_or_node_id_of` per-span-kind mapping and `_extract_tool_output` envelope shim (LangChain `{"type":"tool","data":{"content":…}}` unwrap; CrewAI `text/plain` raw). Full lineage recorded in `docs/OPENINFERENCE_ADAPTER_PREREG.md`.
- **`clew.yaml` — user tool registration (Phase 1).** Four categories: `read_only`, `side_effect`, `payload_dependent`, `declarative`. Discovery order: `--config` flag > walk-up from the trace file > `~/.clew/config.yaml`. Overrides against Clew's built-in mappings are logged to stderr rather than silently accepted.
- **`clew.yaml` — `entity_id` path registration (Phase 2).** `entity_id: response.ticket.id` (dot-path only; arrays, wildcards, and JSONPath rejected). `entity_id` is only valid on `category: side_effect`; suspicious tails (`request_id`, `session_id`, `correlation_id`, `transaction_id`, …) trigger a one-line stderr warning. Runtime extraction-failure ratios print per tool, with an envelope-prefix hint pointing at the framework path table when any failure is present.
- **Duplicate creation check report section.** A dedicated section under waste details lists side-effect tool pairs and classifies each as `differ` (two distinct entity IDs → real duplicate creation), `same` (same ID → likely idempotent), or `no_id` (extraction failed). The check is additive: `waste_span_ids`, `between_window_counts`, and the frozen 159/76/3197 Toolathlon distribution are bit-identical.
- **Tool mapping coverage banner** with the top 5 unrecognized tool names surfaced alongside the coverage percentage. The banner splits `built-in` vs `user-registered` when both are present, and carries an explicit footnote that precision bounds were measured on the built-in mappings only.
- **`between_window` — 5-value sub-classification of `idempotent`.** Report tells you *which evidence* supports the no-state-change reading: `declarative`, `no_side_effect`, `payload_dependent`, `targeted_writes`, `high_volume`. The 5 counts are frozen at `1,226 / 888 / 405 / 248 / 1,024` on the Toolathlon reference set.
- **`raw_output_text` safety net.** `id_bridge` extraction now reads `raw_output_text or output_text`, so a preprocessed `output_text` on the LangChain/OpenInference path no longer silently loses entity IDs. See the Breaking note above for schema impact.

### Documentation

- **README: entity_id path per framework table** (`2f15167`) with the four instrumentors measured against a dict-returning tool: LangChain / CrewAI / OpenAI Agents use `ticket.id`; LlamaIndex needs `raw_output.ticket.id` because its `FunctionTool` serializes returns as `{"blocks":[…], "raw_output":<orig>, …}`.
- **Tier 1 pre-registration and results published to `docs/`.** `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` and `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` land the judgment criteria and the resulting per-framework classification. Both the criteria and the results explicitly record §2.1 R2 (our non-empty `output.value` rule) as stricter than the OpenInference spec — the discrepancy is documented as a known adapter policy, not a spec claim.
- Clopper-Pearson labels standardized on **"95% two-sided (2.5% each tail)"** across all docs (`775883b`). Prior "90% CI" labels were incorrect; underlying numeric bounds were already correct.

### Honesty boundaries (existing rules, restated for the release)

- No "savings" or "confirmed waste" phrasing anywhere in report text or docs.
- Frameworks are listed by measured name only: **"OpenInference 계측 3 개 프레임워크에서 실측 확인 — LangChain, CrewAI, LlamaIndex."** OpenAI Agents SDK, Anthropic (direct SDK), and AutoGen are recorded separately as "current instrumentor cannot be read by 0.4.0" — the underlying SDKs are not evaluated.
- The phrase "여러 프레임워크" ("multiple frameworks") is banned, per `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` §4.1.
