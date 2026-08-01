# Changelog

All notable, user-visible changes to `clew-custos`. This file tracks releases going forward — earlier versions are not back-filled because the criteria for what qualifies as user-visible were not established at the time.

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
