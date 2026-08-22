# Changelog

All notable, user-visible changes to `boxdawn` (previously published on PyPI as `clew-custos`). This file tracks releases going forward — earlier versions are not back-filled because the criteria for what qualifies as user-visible were not established at the time.

## 0.5.2 — 2026-08-22 · 트레이스가 **언제 실행됐는지**를 리포트가 실어 보낸다

리포트에 실리는 시각은 `analyzed`(우리가 분석을 돌린 시각) 하나뿐이었다. 리포트를 시계열로 쌓는 소비자가 그것을 축으로 쓰면, 오래된 트레이스를 오늘 몰아서 분석했을 때 전부 오늘 자리에 찍힌다.

### 추가

- **`trace_started`** — 리포트 JSON 최상위 필드. `min(span.start_time)` 을 UTC 로 정규화한 값이다. `Span.start_time` 은 tz-aware 임이 검증되고 `Trace` 는 span 을 최소 1개 요구하므로 이 값은 항상 존재한다.

공개 트레이스 `davanstrien/agent-race-traces` / `claude-code.jsonl` 에서 두 시각의 거리:

| 필드 | 값 |
|---|---|
| `trace_started` | `2026-05-01T13:22:29Z` |
| `analyzed` | `2026-08-22T07:13:21Z` |

**113일 차이다.** 축을 `analyzed` 로 잡은 시계열은 이 트레이스를 8월에 일어난 일로 그린다.

### 호환성

- 추가 필드다. **임계값·탐지기·판정 기준 변경 없음.** 마크다운 리포트는 무변.
- 같은 트레이스의 이전 리포트와 키 단위로 대조했다: **신규 키 1개 외 차이 없음.** `waste_ratio` 0.659536 · `total_analyzed_cost` 2.5248795 · `total_waste_cost` 1.66524903 · `accuracy_flag` accurate 전부 무변.
- 모르는 키를 무시하는 소비자는 영향받지 않는다.

## 0.5.1 — 2026-08-20 · 리포트가 자기 계산을 정확히 설명하게 만들기

이 릴리스는 탐지 결과가 아니라 **그 결과를 설명하는 말**을 고친다. 네 건 다 계산은 맞고, 문면이 내가 무엇을 재는지 말하지 않거나 낡은 동작을 설명하고 있었다.

### 변경

- **`Waste detection` 라벨이 범위를 밝힌다** → `Waste detection (tool cascade)`. 그 플래그(`wasteful`)는 repeat/pingpong detector 만 반영하고 `context_resend` 를 반영하지 않는다. 그래서 낭비가 전부 context resend 인 트레이스에서 리포트가 `Total waste (detected): $1.665249 (66.0%)` 바로 아래에 `no waste detected` 를 찍었다. 두 진술 다 맞지만 라벨이 범위를 안 담아 서로를 부정하는 것처럼 읽혔다.
- **각주가 실제 가격 산정을 설명한다.** `Attribution assumes Sonnet pricing.` → `Attribution uses per-model rates; unknown models fall back to Sonnet 4.5.` Toolathlon / Exgentic cost table 확장 이후 `pricing.py` 는 alias 로 모델별 요율을 해결하고 모르는 모델만 fallback 한다. 각주가 자기 계산을 오설명하고 있었다.
- **`cost_summary.accuracy_flag` 가 LLM 호출 0건 트레이스에서 `accurate`** 가 된다 (전: `estimated`). 사전등록 기준은 *"모든 LLM 호출이 tier-split 을 가질 때만 accurate"* 이고, 공집합에서 그 전칭명제는 공허하게 참이다. 해당 줄의 주석은 이미 그렇게 적혀 있었고 코드가 반대로 동작했다.
- **어댑터가 표시한 부재(absence) 센티넬을 cascade 가 건너뛴다.** 새 필드 `Span.output_is_absent` (기본 `False`). Claude Code 는 명령이 아무것도 출력하지 않으면 그 자리를 `(Bash completed with no output)` 로 채우는데, 비어 있지 않으므로 tool 출력 불변식을 통과한 뒤 sha256 게이트가 *"출력 없음"* 두 건을 서로의 중복으로 판정한다. 같은 원칙은 non-tool 분기에 이미 있었다. 벤더 문자열은 어댑터에만 산다.

### ★ `tiktoken` 을 의존성으로 선언 — 사용자 수치가 우리 수치와 일치하게 된다

`tiktoken` 은 0.5.0 까지 **어느 의존성·extra 에도 선언되지 않았다.** `context_resend` 와 `redundant_read` 는 토큰 수를 셀 때 `tiktoken` 을 시도하고 없으면 `len(text) // 4` 로 대체하는데(코드에 명시된 의도된 동작), 선언이 없었으므로 **모든 깨끗한 설치가 대체 경로를 탔다.** 우리 개발 환경에는 tiktoken 이 우연히 있었다. 그래서 우리가 발표한 토큰·비용 수치는 정밀 경로 값이고, 사용자가 같은 트레이스를 돌려 얻는 값은 대체 경로 값이었다.

공개 트레이스 `davanstrien/agent-race-traces` / `claude-code.jsonl` 로 측정한 차이:

| 수치 | 0.5.0 (대체 경로) | 0.5.1 (선언 후) |
|---|---|---|
| `total_waste_cost` | 1.68473586 | **1.66524903** |
| `waste_ratio` | 0.667254 | **0.659536** |
| `context_resend` resent input tokens | 2,069,799 | **2,056,739** |
| `waste_rate.union_wr_cost` | 0.150515 | **0.148774** |
| `total_analyzed_cost` | 2.5248795 | 2.5248795 (무변) |
| resent chunk 수 · 분모 | 1720 / 2,238,628 | 동일 (무변) |
| `waste_rate.union_wr_char` | 0.96584 | 동일 (무변 — 바이트 기반) |

**0.5.0 에서 올라오는 사용자는 토큰·비용 수치가 위 방향으로 바뀐다.** 탐지 판정(무엇이 낭비인지)은 바뀌지 않는다 — 바뀌는 것은 그 낭비를 토큰으로 환산하는 자의 정밀도뿐이다. 바이트 기반 수치(`union_wr_char`)와 개수 기반 수치는 전부 무변이다.

`tiktoken>=0.7,<1.0` (base 의존성). 정확 핀을 쓰지 않은 이유: 재현성은 인코딩 이름이 담보하며 그것은 코드에 동결되어 있다 (`context_resend.py :: _chunk_token_len`, `cl100k_base` · "frozen for v1"). 버전 범위는 라이브러리 존재만 보장한다.

### 사용자가 알아차릴 수 있는 동작 변화

- **Claude Code 트레이스에서 `waste_span_count` · `waste_details` · `category_counts` 가 줄어든다.** 실측: 로컬 40 세션 합계 31 → 9. 사라진 22건은 전부 부재 표현이다 (`(Bash completed with no output)` 20건 · `No matches found…` 2건).
- **`waste_rate.union_wr_char` 가 플래그 해제된 바이트만큼 내려간다.** 실측 한 트레이스에서 0.989674 → 0.989671 (−3.0e-06 · 6 span × 31 바이트). 소수 1자리 인용은 불변.
- **`io.save_trace` 가 쓰는 트레이스 파일에 `output_is_absent` 키가 실린다.** 구 파일은 기본값으로 계속 로드된다. **리포트 JSON 스키마는 변경 없다.**

### 무변경 (실측 대조)

- **비용 계산 전부.** 한 트레이스 전/후 JSON 필드 대조에서 9개 필드 전부 동일: `total_analyzed_cost` 24.0530675 · `total_waste_cost` 20.69691232 · `waste_ratio` 0.860469 · `detector_breakdown` 3개 전부.
- **동결 파라미터** φ=0.514345 · N=2 · embedding model rev `e8f8c211…`.
- **리포트 JSON 스키마** — 전/후 최상위 키 집합 동일. `coverage_stats` 동일.
- **Toolathlon 트레이스의 cascade 탐지** — 240 트레이스 표본에서 347 → 347. 거기서는 부재 센티넬이 없고 플래그가 실제 중복이다 (`emails-send_email` 139건 등).
- **CLI 인터페이스 · 의존성** 무변경.

### 릴리스 이유

네 건 다 계산은 맞으면서 문면이 틀린 사례였다. 같은 계측을 0.4.1 에서 한 번 다뤘다 (`wasteful=False` 일 때 상단이 duplicate creation 을 가렸던 것). 0.5.1 은 그 남은 절반이다 — 라벨 자체가 범위를 담은 것.

사전등록: `docs/CASCADE_ABSENCE_SENTINEL_AMENDMENT_{PREREG,RESULTS}.md`.
해당 PR: #119 · #120 · #122.

## 0.5.0 — 2026-08-17 · Rebrand to Boxdawn

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
