# Coverage Transparency 사전등록 — 매핑 상대성의 리포트 노출

**작성 시각 (UTC)**: 2026-07-29T00:00:00Z
**HEAD 해시**: 로컬 `feat/high-volume-tier` (`ac3e3f4`, b23 확장 완료; PR 대기)
**작성**: 구현 **전**
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**선행 merge 필수**: `feat/high-volume-tier` (b23 확장) merge 완료

---

## 선행 근거

- **b23 §0.5 한계 명시 (2026-07-29)**: "not established" 제거로 모든 idempotent pair가 증거 층에 배정되면서, Rule V2 step 2 (미매핑 도구를 "없는 것"으로 취급)의 위험이 리포트 상 가시성이 낮아짐. 사전등록 §0.5에는 "새 어댑터 도입 시 위험"으로 표현됨.

- **Stage 0 실측 (2026-07-29)**:
  - **Toolathlon 매핑 커버리지**: 138 / 523 unique 도구 = **26.4%** (그중 (1) `_BW_SIDE_EFFECT_TOOLS` 62개, (2) `_BW_DECLARATIVE_TOOLS ∪ _IDEMPOTENT_TOOLS` 76개).
  - **리포트-표시 idempotent pair에서 사이에 (3) 미매핑 도구가 있는 비율:**

    | bw enum | pairs | w/ (3) in between | % affected |
    |---|---:|---:|---:|
    | declarative | 1,226 | 428 | 34.91% |
    | no_side_effect | 888 | 189 | **21.28%** |
    | payload_dependent | 405 | 138 | **34.07%** |
    | targeted_writes | 248 | 95 | **38.31%** |
    | **high_volume** | 1,024 | 526 | **51.37%** ← 노출 최대 |
    | 총 idempotent | 3,791 | 1,376 | 36.30% |

  - **표본 실측** (Stage 0 §3):
    - (b-1) seed 47: **7/30** (23.3%) 표본에 (3) 미매핑 노출 — 모집단 21.28%와 근사 (편향 없음)
    - (b-2-2) seed 51: **12/30** (40%) 표본에 (3) 미매핑 노출 — 모집단 34.07%와 근사

- **판정 원리 (재확인)**: (b-2-1) 사전등록 §a — *"동기는 트레이스에서 관측 불가하며 판정 질문의 대상이 아니다 … 결과 (쓰기 대상 vs 재조회 대상, sha256 상태) 로 판정한다."* 즉 (b-1)/(b-2-2)/(b-2-1)/(b-2-3) 판정 결과 (88.43% / 88.43% / 77.93% / 82.78% 하한)는 **결과 기반이므로 유효**. 재검증 불필요.

- **문제 정의**: 판정 결과는 유효하나, `no_side_effect` / `payload_dependent` / 기타 enum 라벨이 뜻하는 바가 **좁아짐**:
  - 이전 이해 (broad): "실제로 상태 변경이 없었다"
  - 정확한 진실 (narrow): "**매핑된** 도구 중 상태 변경이 없었다"

  이 축소를 리포트·README에서 사용자가 인지할 수 있어야 함. 축소를 문면마다 "mapped"를 끼워넣어 표현하면 문면이 뭉개짐. 한 곳에서 못박고 나머지 문면은 그대로 두는 방식이 정확·간결.

**증거 문서 (커밋 안 함, `field_test/diagnostics/` 하위)**: `stage0_unmapped_tools.py/.json`, `stage0_s3_verify_prior_samples.py/.json`, `stage0_s1_recompute_correct_denominator.py/.json`. 본 사전등록 §선행 근거에 요약 인라인.

---

## §0 — 절대 불가침

이 변경은 **리포트 표시 계층 + 문서 문면**만 다룬다. **탐지·분류·카운트 무변**.

### §0.1 무변 파일
- `src/clew/detect/cascade.py`, `structural.py`, `semantic.py` — 무변
- `src/clew/report/_enrich.py` — 무변 (분류 로직 무변; **단** enrichment result가 커버리지 통계를 계산 가능하도록 metadata 확장은 허용 — 상세 §1.5)
- `src/clew/detect/*` 모든 임계 (φ, N, embedding model) — 무변

### §0.2 무변 값
- 5개 `between_window` enum 값 무변, Rule V2 우선순위 무변
- Toolathlon 5개 카운트 (**1,226 / 888 / 405 / 248 / 1,024** = 3,791) — 무변
- `waste_span_ids` bit-identical (PRE = 병합된 `feat/high-volume-tier` 상태 = POST) — 무변
- JSON `between_window_counts` 최상위 필드 값 · JSON `waste_details[].between_window` 필드 스키마 — 무변
- 프리즌 파라미터 무변

### §0.3 §3.2 금지어 (7종) — 유지
`confirmed waste`, `verified waste`, `proven waste`, `waste confirmed`, `waste verified`, `guaranteed waste`, `definite waste`. 신규 문면·배너에 금지어 없음이 사전 확인 필요 (§2.1 검증 게이트).

### §0.4 변하는 것
- **리포트에 커버리지 배너 신규 (트레이스별)**
- **JSON 최상위에 `coverage_stats` 필드 신규 (하위호환 — 기존 소비자 무영향)**
- **README에 About 섹션 (Coverage Transparency) 신규 · 한 번 못박기**
- **README `no_side_effect` / `payload_dependent` / `high_volume` 서브섹션의 라벨 정의 문면 약간 조정** — 각 문면에 "mapped"를 끼워넣지 **않고**, About 섹션에서 한 번 못박은 후 그 링크로 처리
- **b23 사전등록 §0.5 (한계) 갱신** — Stage 0 실측 수치 반영 (별도 커밋)

---

## §1 — 변경 내용

### §1.1 리포트 커버리지 배너 (신규 · 두 라인 분리)

**Q1·Q2 사용자 결정 (2026-07-29)에 따라 최종안 확정.**

**Q1 결정 — 위치**: WASTE DETECTED 리포트에서 **category breakdown 뒤·Redundant-invocation candidates 앞**.
- **근거 (사용자 인용)**: *커버리지 이슈는 between_window에만 해당. 카테고리 분류(error_repeat/side_effect/idempotent/unclassified)에서 미매핑은 unclassified로 떨어져서 정직한 동작. 헤더 근처에 두면 리포트 전체가 불확실한 것처럼 과잉 경고가 됨. 과잉 경고는 읽는 사람이 무시하게 만듦.*

**Q2 결정 — 두 라인 분리**:

**라인 A — 커버리지 (항상 표시, waste-0 세션 포함):**
```
- **Tool mapping coverage for this trace**: {recognized} of {unique_in_trace} tools recognized ({pct:.1%}).
```
- **근거 (사용자 인용)**: *커버리지 26%인 사용자가 "no waste detected"만 보면 "우리 깨끗하네"로 읽음. 실제로는 그 사용자 도구의 4분의 3을 우리가 못 보는데도. 잘못된 안심이 잘못된 경고보다 위험함.*
- **★ 위치 (waste-0 경로)**: `## Result: no waste detected` 헤더 뒤, "No wasteful patterns found." 라인 뒤. `_FOOTER` 앞.
- **★ 위치 (WASTE DETECTED 경로)**: category breakdown 뒤, Redundant-invocation candidates 앞.

**라인 B — 영향 pair (idempotent pair ≥ 1일 때만):**
```
- **Idempotent pairs with unrecognized tool in interval**: {pairs_affected} of {idempotent_total}.
```
- **조건**: `cat_counts.get("idempotent", 0) > 0` — 즉 WASTE DETECTED 경로 & Redundant-invocation candidates 블록이 렌더되는 조건과 동일.
- **위치**: 라인 A 바로 뒤.

**★ 구현 주의 (사용자 지시)**: `render_markdown()`의 waste-0 조기 `return` 전에 라인 A가 렌더돼야 함. 테스트 `test_coverage_line_a_present_in_waste_zero` 로 잠금.

**용어**: `recognized` / `unrecognized` (사용자 친화). "mapped"는 내부 용어라 배너에 노출 안 함.

**신규 상수** (`src/clew/report/markdown.py`):
```python
_COVERAGE_LINE_A = (
    "**Tool mapping coverage for this trace**: {recognized} of "
    "{unique_in_trace} tools recognized ({pct:.1%})."
)
_COVERAGE_LINE_B = (
    "**Idempotent pairs with unrecognized tool in interval**: "
    "{pairs_affected} of {idempotent_total}."
)
```

**계산 로직** (신규 함수, `_enrich.py`에 추가):
```python
def _coverage_stats(trace, enriched_details):
    tool_names = {s.agent_or_node_id for s in trace.spans if s.span_kind == "tool"}
    recognized = {t for t in tool_names
                  if t in _BW_SIDE_EFFECT_TOOLS
                  or t in _BW_DECLARATIVE_TOOLS
                  or t in _IDEMPOTENT_TOOLS}
    unrecognized = tool_names - recognized

    idem_total = 0
    pairs_affected = 0
    for ed in enriched_details:
        if ed.category != "idempotent":
            continue
        idem_total += 1
        # between-tool spans (strict window)
        between = [s for s in trace.spans
                   if s.span_kind == "tool"
                   and ed.detail.origin.end_time <= s.start_time
                     < ed.detail.candidate.start_time]
        if any(s.agent_or_node_id in unrecognized for s in between):
            pairs_affected += 1
    return {
        "unique_tools_in_trace": len(tool_names),
        "recognized_tools": len(recognized),
        "coverage_ratio": len(recognized) / len(tool_names) if tool_names else 1.0,
        "idempotent_pairs_total": idem_total,
        "pairs_with_unrecognized_in_between": pairs_affected,
    }
```

**★ 정의 (frozen)**:
- **`unique_tools_in_trace`** = trace의 tool-kind span에서 유일 도구 이름 수 (재조회 대상 포함).
- **`recognized`** = (1) `_BW_SIDE_EFFECT_TOOLS` ∪ (2) `_BW_DECLARATIVE_TOOLS ∪ _IDEMPOTENT_TOOLS` 중 어느 하나에 속함.
- **`unrecognized`** = 위 세 목록 어디에도 없음 (= Stage 0의 bucket "(3)").
- **`pairs_with_unrecognized_in_between`** = idempotent pair 중, `origin.end_time <= s.start_time < candidate.start_time` 조건을 만족하는 tool-kind span 중 하나라도 unrecognized인 pair.

### §1.2 JSON 리포트 확장 (하위호환)

**최상위에 `coverage_stats` 신규 필드**:
```json
{
  "trace_id": "...",
  "wasteful": true,
  "waste_span_ids": [...],
  "between_window_counts": { ... },       // 무변
  "coverage_stats": {                     // 신규
    "unique_tools_in_trace": 40,
    "recognized_tools": 18,
    "coverage_ratio": 0.45,
    "idempotent_pairs_total": 88,
    "pairs_with_unrecognized_in_between": 22
  },
  "waste_details": [ ... ]                // 무변
}
```

- 기존 소비자 (5-enum count / waste_span_ids / waste_details) 무영향 — 신규 필드 무시.
- Waste-0 세션에서도 `coverage_stats` 표시. `idempotent_pairs_total: 0`, `pairs_with_unrecognized_in_between: 0`.

### §1.3 About 섹션 (README) — 한 번 못박기

**위치**: README §"Idempotent sub-classification (`between_window`)" 서브섹션 바로 뒤에 신규 서브섹션 `### Tool mapping coverage` 추가.

**문면 (draft — 최종 확정은 §2 검증 게이트 통과 후)**:

```markdown
### Tool mapping coverage

The `between_window` classification is **relative to Clew's tool mapping** — the set of tool names Clew recognizes as state-changing, read-only, or declarative. Tools that are not in any of these lists are counted as if they were absent from the interval.

**On the Toolathlon benchmark (2026-07-29 measurement):**
- 138 of 523 unique tool names are recognized (**26.4% coverage**).
- Of the 3,791 report-shown idempotent pairs, 1,376 (36.30%) had at least one unrecognized tool in the interval.

Per-tier breakdown:

| tier | pairs | with unrecognized tool | share |
|---|---:|---:|---:|
| `declarative` | 1,226 | 428 | 34.9% |
| `no_side_effect` | 888 | 189 | 21.3% |
| `payload_dependent` | 405 | 138 | 34.1% |
| `targeted_writes` | 248 | 95 | 38.3% |
| **`high_volume`** | **1,024** | **526** | **51.4%** |

**What this means for verdicts.** Verdicts are based on `sha256(output_A) == sha256(output_B)`, which is a **result-based** check ((b-2-1) §a). If the reread output is unchanged, the pair is flagged regardless of whether an unrecognized tool sat between the calls. So the hand-labeled TRUE rates (30/30, 30/30, 28/30, 29/30) and their Clopper-Pearson lower bounds (88.43% / 88.43% / 77.93% / 82.78%) are unaffected by mapping coverage — they were always about result identity, not about tool inventory.

**What this means for tier labels.** The tier a pair lands in *does* depend on mapping. A pair with an unrecognized state-changing tool in the interval will land in `no_side_effect` instead of `targeted_writes` or `payload_dependent`. That is a label-precision limitation, not a false verdict.

**Coverage on your own trace.** The report banner at the top shows this trace's coverage. If the number is low and matters to you, add the missing tools to the mapping — see [`docs/COVERAGE_TRANSPARENCY_PREREG.md`](docs/COVERAGE_TRANSPARENCY_PREREG.md) for the tool categorization convention and the (currently manual) extension procedure. A tool-registration path (`clew.yaml`) is on the roadmap.
```

★ 이 서브섹션이 **"매핑 상대성"에 대한 유일한 진술**. 다른 서브섹션·문면에는 "mapped"를 끼워넣지 않는다. About 링크로 참조.

### §1.4 `high_volume` 서브섹션 문면 조정 (README)

**기존 (b23 확장 후):**
> - **`high_volume`** — a state-changing tool is present AND ≥ 20 tool spans lie between the calls. **Hand-labeled sample: 29/30 TRUE** (95% two-sided Clopper-Pearson lower bound ≈ 82.78%). One case was a same-target repeated write with unchanged content (a `.tex` file rewritten three times with the same sha256). Grouped separately from `targeted_writes` (28/30, 77.93% lower bound) — its evidence is stronger, so it renders in a higher tier. See [`docs/GREYZONE_B23_EXTENSION_PREREG.md`](docs/GREYZONE_B23_EXTENSION_PREREG.md).

**변경 (Coverage Transparency 반영):**
> - **`high_volume`** — a state-changing tool is present AND ≥ 20 tool spans lie between the calls. **Hand-labeled sample: 29/30 TRUE** (95% two-sided Clopper-Pearson lower bound ≈ 82.78%). One case was a same-target repeated write with unchanged content (a `.tex` file rewritten three times with the same sha256). Grouped separately from `targeted_writes` (28/30, 77.93% lower bound) — its evidence is stronger, so it renders in a higher tier. **This tier has the highest mapping-coverage dependence of the five** — 51.4% of `high_volume` pairs on Toolathlon had at least one unrecognized tool in the interval (structural consequence of the ≥ 20 threshold — the wider the interval, the higher the chance an unrecognized tool appears). The 29/30 verdict itself is result-based (`sha256` identity) and unaffected by that dependence. See [`docs/GREYZONE_B23_EXTENSION_PREREG.md`](docs/GREYZONE_B23_EXTENSION_PREREG.md) and [`docs/COVERAGE_TRANSPARENCY_PREREG.md`](docs/COVERAGE_TRANSPARENCY_PREREG.md) §1.4.

**★ 다른 두 문면 (`no_side_effect`, `payload_dependent`, `targeted_writes`)** — 각 문면에 커버리지 이슈를 반복 언급하지 **않는다**. About 섹션 §1.3에서 한 번 못박음.

### §1.5 b23 사전등록 §0.5 갱신 (별도 커밋)

**추가 문단** (기존 §0.5 문단 뒤에 append):

```markdown
**Stage 0 measurement (2026-07-29).** The limitation above was measured to already occur on the current datasets:
- Toolathlon mapping coverage: **138 / 523 unique tools = 26.4%**.
- Of report-shown idempotent pairs, share with ≥ 1 unrecognized tool in the interval:
  - `declarative` 428 / 1,226 (34.9%)
  - `no_side_effect` 189 / 888 (**21.3%**)
  - `payload_dependent` 138 / 405 (34.1%)
  - `targeted_writes` 95 / 248 (38.3%)
  - `high_volume` **526 / 1,024 (51.4%)** ← highest exposure
- Verification samples showed the same shape (b-1 seed 47: 7/30 = 23.3%; b-2-2 seed 51: 12/30 = 40.0%). Sample rates match population rates — hand-labeling was not biased.

Verification results (88.43% / 88.43% / 77.93% / 82.78% lower bounds) remain valid — the decision principle is result-based per (b-2-1) §a, so `sha256` identity, not mapping coverage, produced the TRUE labels. What narrows is only the tier-label meaning: `no_side_effect` etc. describe "no state change **via mapped tools**" rather than "no state change" in the absolute sense. This narrowing is surfaced explicitly by the report banner and README About section introduced in `docs/COVERAGE_TRANSPARENCY_PREREG.md`.
```

### §1.6 리포트 CLI 문면 — 무변

`_BW_OBS_*` 상수 (`_BW_OBS_DECLARATIVE`, `_BW_OBS_NO_CHANGE`, `_BW_OBS_TARGETED_WRITES`, `_BW_OBS_HIGH_VOLUME`) — **무변**. per-pair 문면에 "mapped"를 끼워넣지 않는다. 배너가 한 곳에서 못박음.

**근거**: 사용자 지시 — "문면마다 'mapped'를 끼워넣지 말고, About 섹션에서 한 번 못박을 것".

---

## §2 — 검증 기준

### §2.1 필수 검증 (모두 통과해야 릴리스)

1. **waste_span_ids bit-identical** — PRE (`feat/high-volume-tier` merge 후) vs POST. `cand_sha256 = 5c0c94d6…`, `pair_sha256 = 742b51a7…` — b21/b23 확장 이후에도 유지된 값.

2. **between_window_counts bit-identical** — 5개 enum 값이 정확히 `declarative=1226, no_side_effect=888, payload_dependent=405, targeted_writes=248, high_volume=1024`. `test_between_window_toolathlon_counts_reproduce_pre_reg_4_1` 통과.

3. **coverage_stats bit-identical (POST vs POST)** — 재실행 시 동일 값. `test_coverage_stats_stable` 신규.

4. **JSON 하위호환** — 기존 소비자가 5-enum count·waste_span_ids·waste_details 파싱 시 무영향. `test_json_backward_compat` 신규.

5. **전체 pytest 통과** (기존 261 + 신규).

6. **신규 테스트** (Q2 결정 반영):
   - `test_coverage_line_a_present_in_waste_zero` — waste-0 세션에도 라인 A (커버리지) 존재. **★ 조기 return 전 렌더 확인.**
   - `test_coverage_line_a_present_in_waste_detected` — WASTE DETECTED 세션에도 라인 A 존재
   - `test_coverage_line_b_absent_when_no_idempotent` — idempotent 카테고리 0건일 때 라인 B는 렌더 안 됨 (side_effect·error_repeat만 있는 세션)
   - `test_coverage_line_b_present_when_idempotent_gt_zero` — idempotent ≥ 1일 때 라인 B 존재
   - `test_coverage_line_ab_order` — 라인 A → 라인 B → Redundant-invocation candidates 순서
   - `test_coverage_line_math` — 특정 픽스처에서 recognized/unique_in_trace/pairs_affected/idempotent_total 값 정확 계산
   - `test_coverage_stats_json_schema` — JSON에 `coverage_stats` 최상위 필드 존재, 5개 하위 필드 (unique_tools_in_trace, recognized_tools, coverage_ratio, idempotent_pairs_total, pairs_with_unrecognized_in_between)
   - `test_coverage_stats_stable` — 동일 트레이스 재실행 시 동일 값
   - `test_no_over_claim_wording_in_banner` — 배너 텍스트에 §3.2 금지어 없음
   - `test_between_window_counts_stable_post_coverage` — coverage 계층 추가가 기존 5개 카운트에 영향 없음
   - `test_readme_example_matches_current_render_structure` — b23 §5 상시 규칙 유지: README 예시가 새 배너 포함해서 실 렌더와 일치

7. **§3.2 금지어 grep guard** — 신규 상수 · 렌더 결과 배너 · README About 섹션 모두

8. **실 세션 렌더** — `09d9abe9-0a02-4bd1-8129-3b864695079d.jsonl` 재렌더:
   - 배너 두 라인 표시 확인
   - 계산된 커버리지 수치가 그 세션의 unique 도구 세트와 일치
   - README 예시 그 결과로 재생성 (§5 상시 규칙 준수)

### §2.2 KILL 조건
- 카운트 하나라도 어긋남 → 즉시 롤백. 규칙 변경 아님 (표시 계층 코드 오류로 처리).
- bit-identical 실패 (waste_span_ids 또는 between_window_counts) → 즉시 롤백.
- 금지어 검출 → 문면 정정 후 재검증. 재검증 실패 시 롤백.
- 배너가 특정 세션 유형에서 미표시 → 롤백.
- coverage_stats 필드 계산 값이 사전 예상 (Toolathlon 26.4%, no_side_effect 21.3% 등)과 어긋남 → 롤백. 코드 오류.

---

## §3 — Toolathlon 예측 카운트 (재확인)

변경 후 Toolathlon 렌더에서:

**JSON `between_window_counts`**: 무변 (1,226 / 888 / 405 / 248 / 1,024 = 3,791)

**JSON `coverage_stats` (신규)** — Toolathlon 세션당 다르되, 전체 벤치마크 합산 시 (모든 세션 total):
- `unique_tools_in_trace`: 세션별 (평균 예상 ~50)
- `recognized_tools`: 세션별 (평균 예상 ~30)
- **coverage_ratio**: 세션 평균 예상 **~60%** (Toolathlon 전체 unique 도구가 523이지만 세션 하나가 그중 일부만 사용)
- `idempotent_pairs_total`: 세션별
- `pairs_with_unrecognized_in_between`: 세션별 (전체 합산 = 1,376 예상)

**markdown 배너**: 세션당 두 라인 표시.

**KILL 규칙**: 어느 카운트든 정의와 어긋나면 코드 오류. 롤백 후 원인 분석 → 재구현.

---

## §4 — 커밋 체인 (Rule 8, squash 금지)

1. `docs(prereg): coverage transparency pre-registration`
   - 본 문서 `docs/COVERAGE_TRANSPARENCY_PREREG.md` 신규
   - 증거 인라인 (Stage 0 실측 3표)

2. `docs(prereg): amend b23 §0.5 with 2026-07-29 measurement`
   - `docs/GREYZONE_B23_EXTENSION_PREREG.md` §0.5 뒤에 §1.5 문단 append
   - 원본 §0.5 문면 무변, 추가만

3. `feat(report): add tool mapping coverage banner + coverage_stats JSON field`
   - `src/clew/report/_enrich.py` — `_coverage_stats()` 함수 신규, 기존 로직 무변
   - `src/clew/report/markdown.py` — `_COVERAGE_BANNER` 상수 신규, `render_markdown()`에 배너 라인 추가
   - `src/clew/report/json_report.py` — `coverage_stats` 필드 신규 (하위호환)

4. `test(report): coverage banner + math + JSON schema + stability`
   - `tests/test_between_window.py` 확장 또는 신규 `tests/test_coverage_transparency.py` — §2.1 #6 7개 신규 테스트

5. `docs(readme): document tool mapping coverage as an About section`
   - README §"Idempotent sub-classification" 뒤에 §"Tool mapping coverage" 서브섹션 신규
   - `high_volume` 서브섹션 문면에 mapping-coverage 의존도 최고 언급 추가
   - README 예시 output 재생성 (09d9abe9 재렌더 결과로 배너 두 라인 포함)

**선행 merge 순서**:
1. `feat/high-volume-tier` (b23) merge 완료
2. 본 확장 브랜치 (`feat/coverage-transparency` 또는 유사) 생성
3. 커밋 5개 → PR → 승인 → merge

---

## §5 — 참조

- `docs/GREYZONE_B23_EXTENSION_PREREG.md` §0.5 (Stage 0 근거)
- `docs/GREYZONE_B21_EXTENSION_PREREG.md` (선행 확장)
- `docs/GREYZONE_EXPANSION_PREREG.md` (Rule V2, enum 정의)
- `field_test/diagnostics/stage0_unmapped_tools.py/.json` (실측)
- `field_test/diagnostics/stage0_s1_recompute_correct_denominator.py/.json` (모집단 정정)
- `field_test/diagnostics/stage0_s3_verify_prior_samples.py/.json` (표본 검증)
- `memory/feedback_observed_not_confirmed.md`
- `memory/feedback_frozen_absolutes.md`
- `memory/feedback_diagnostics_uncommitted.md`

---

## §6 — 결정 남긴 사항 (사전등록 승인 시 함께 결정)

**개방된 선택 (사용자 승인 시 확정):**

**Q1 — 배너 위치**: 리포트 상단 (`WASTE DETECTED` 직후) vs category breakdown 뒤 (Redundant-invocation candidates 앞). 초안은 후자. 다르게 원하면 지시.

**Q2 — Waste-0 세션에서 두 번째 라인**: 항상 표시 (`0 of 0 idempotent pairs...`) vs 조건부 생략. 초안은 항상 표시.

**Q3 — 후속 (본 사전등록 밖) 추적 사항**:
- **B (매핑 확대)**: Stage 0 §3 unique 26 미매핑 도구 손 분류. 그중 상태변경 도구를 `_BW_SIDE_EFFECT_TOOLS`에 추가. 별도 사전등록.
- **C-3 사용자 등록 (`clew.yaml`)**: 사용자가 자기 도구 매핑을 등록할 수 있는 경로. 본 확장 밖.

Q1·Q2 답 (사용자) → §2 검증 진행.

---

_이 문서 이후 사용자 승인 대기. 승인 시 커밋 1 (docs prereg) 부터 시작._
