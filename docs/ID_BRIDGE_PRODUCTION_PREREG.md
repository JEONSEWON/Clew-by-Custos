# ID Bridge Production Migration — Pre-registration

**작성 시각 (UTC)**: 2026-07-29T00:00:00Z
**HEAD 해시**: `feat/coverage-transparency` (커밋 `16d0397`, coverage-transparency PR 대기)
**작성**: 구현 **전**
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**선행 merge 필수**: `feat/coverage-transparency` PR merge 완료 (기술적으로 독립이나 커밋 chain의 base 정리를 위해 순차)

---

## 선행 근거

### id_bridge_scan.py 실측 (Pool A, sha256 무관)

`field_test/diagnostics/id_bridge_scan.py`로 스캔한 결과 (Toolathlon 66 files, 6,780 traces):

- **Pool A** = `find_candidates(trace, N=2)` + `cand.agent_or_node_id ∈ _SIDE_EFFECT_TOOLS`. same-input side_effect pair 전체. sha256 identity gate **미적용**.
- Total Pool A: **3,432 pairs.**
- 3-way 분류 (`id_bridge_scan.py`의 §4 로직):

  | verdict (내부 enum) | count | share |
  |---|---:|---:|
  | `provable_duplicate` (ID 다름) | **159** | 4.63% |
  | `provable_idempotent` (ID 같음) | 76 | 2.21% |
  | `unprovable` (ID 없음/추출 실패) | **3,197** | **93.16%** |
  | **Total** | 3,432 | 100% |

`unprovable` 3,197의 내역 (별도 스캔 `id_bridge_unprovable_breakdown.py`):
- (a) no_id_field: 2,011 (62.9% of unprov)
- (c) error: 1,037 (32.4%)
- (b) id_present_unmapped: 149 (4.7%) ← B2 확장 대상
- (d) other: 0

### 외부 커뮤니케이션 vs 제품 상태 gap

- **GN Ask 답글, LinkedIn 초안, PRD 발표 구성 등에서 "159건은 실제로 두 개 생성됨이 증명됐다"고 사용해옴.**
- **그러나 `src/clew/` grep 결과: `provable`, `unprovable`, `id_bridge`, `entity_id` = 0 hits.**
- `render_markdown` / `render_json` 어느 것도 ID 비교 기반 판정을 호출 안 함.
- 즉 **사용자가 `clew analyze`를 돌리면 이 판정이 리포트에 안 나옴.** 홍보한 차별점이 제품에 없다.

### 발견 — cascade identity gate가 생성 도구에서 역방향으로 작동

**Cascade 로직 (frozen)**:
1. Structural gate — `(node, normalized input)`로 그룹핑, ≥ 2 occurrence면 candidate.
2. Identity gate — `sha256(output_A) == sha256(output_B)` 요구.

**함의**:
- 읽기 도구 (`Read`, `filesystem-read_file` 등): 같은 파일을 두 번 읽으면 응답 동일 → sha256 동일 → waste로 flag. **올바른 방향.**
- 생성 도구 (`notion-API-post-page`, `google_sheet-create_spreadsheet` 등): 같은 인자로 두 번 호출해도 각각 새 entity (다른 ID) 생성 → 응답 다름 → sha256 다름 → **waste에서 제외.** 그러나 실제로 두 개가 생성됨.

즉 cascade의 identity gate는 생성 도구에서 **반대 방향으로 작동** — 실제 duplicate creation을 걸러냄. 이건 결함이 아니라 구조적 사실 (waste = "헛수고한 두 번째 호출"이라는 정의는 sha256 동일 = 같은 결과라는 근거에서 옴).

**함의 (제품 서사):**
Clew에는 논리가 반대인 탐지기 두 개가 필요:

| 탐지기 | 조건 | 뜻 |
|---|---|---|
| **Waste detection (기존)** | sha256 동일 | 같은 결과 → 두 번째가 헛수고 (읽기·조회에 맞음) |
| **Duplicate creation check (B1 신규)** | ID 다름 | 다른 엔티티 → 두 개가 진짜 생성됨 (생성 도구에 맞음) |

두 탐지기가 서로 배타적이며, 각각 자기 대상에 맞음. B1은 후자를 제품에 이관한다.

---

## §0 — 절대 불가침

이 변경은 **리포트 표시 계층 + JSON schema 확장**. **탐지·분류·카운트 무변**.

### §0.1 무변 파일 · 값
- `src/clew/detect/cascade.py`, `structural.py`, `semantic.py` — 무변
- `src/clew/report/_enrich.py`의 기존 함수 (`enrich`, `_classify_category`, `_classify_between_window`) — 무변
- Rule V2, 5개 `between_window` enum, `_BW_*` 목록들 — 무변
- **`waste_span_ids` bit-identical** (baseline post-coverage-transparency, `cand=5c0c94d6…`, `pair=742b51a7…`)
- **`between_window_counts` 무변** (declarative=1226, no_side_effect=888, payload_dependent=405, targeted_writes=248, high_volume=1024)
- **`coverage_stats` 무변** (직전 PR의 5개 필드)
- JSON 기존 필드 무변, 프리즌 파라미터 무변

### §0.2 §3.2 금지어 (7종) — 유지
`confirmed waste`, `verified waste`, `proven waste`, `waste confirmed`, `waste verified`, `guaranteed waste`, `definite waste`.
**추가 금지어 (신규):** 렌더 문면에 **`provable`** 단어 미사용 (관측 서술 원칙). 내부 enum 이름은 유지 가능.

### §0.3 Pool 정의 차이 — 명시적 기록

**두 풀은 서로 다르며 포함 관계가 아니다:**

| 풀 | 정의 | 크기 (Toolathlon) |
|---|---|---:|
| **Cascade waste** | structural gate + **sha256 identity gate 통과** + 카테고리 무관 | **8,042** pairs |
| **B1 신규 풀** | `find_candidates` (same-input) + `cand ∈ _SIDE_EFFECT_TOOLS`, sha256 **무관** | **3,432** pairs |

- **교집합**: 두 풀의 side_effect pair 중 sha256 동일인 것. 이건 B1에서 `provable_idempotent` 76건에 해당 (전부 cascade에도 포함).
- **B1 - cascade**: sha256 다른 same-input side_effect pair. 이게 `provable_duplicate` 159 + `unprovable` 3,197의 대부분을 차지 (전부는 아님 — sha256 동일이지만 ID 다른 케이스는 논리상 불가, 그러나 sha256 동일 + no_id 케이스는 cascade에도 있고 B1에도 있음).
- **Cascade - B1**: read/declarative/idempotent 도구 pair, side_effect 아닌 나머지.

이 두 풀을 리포트에서 **별도 섹션으로 표시**한다. 하나가 다른 하나를 대체하지 않는다.

### §0.4 변하는 것

- `_enrich.py`에 새 데이터·함수 추가 (id_mapping, extract_id, 3-way classify) — 기존 로직 무변
- `EnrichedDetail` 무변, 신규 dataclass `IdBridgeCandidate` 추가
- `markdown.py`에 신규 섹션 `## Duplicate creation check` 렌더링
- `json_report.py`에 최상위 array `id_bridge_candidates` 신규 (하위호환)
- README에 서브섹션 신규 — "왜 두 개의 탐지기가 있는가"

---

## §1 — 변경 내용

### §1.1 ID_MAPPING 26개 (id_bridge_scan.py → _enrich.py 이관)

`id_bridge_scan.py` line 34-67의 `ID_MAPPING` dict를 그대로 이관.

```python
# In _enrich.py, new constant:
_ID_BRIDGE_MAPPING: dict[str, tuple[str, str]] = {
    # notion
    "notion-API-post-page":                 ("path",       "id"),
    "notion-API-patch-page":                ("path",       "id"),
    "notion-API-patch-block-children":      ("array_path", "results.0.id"),
    # google
    "google_sheet-create_spreadsheet":      ("path",       "spreadsheetId"),
    "google_forms-create_form":             ("path",       "formId"),
    # github (commit sha)
    "github-create_or_update_file":         ("path",       "commit.sha"),
    "github-delete_file":                   ("path",       "commit.sha"),
    "github-create_branch":                 ("path",       "object.sha"),
    "github-push_files":                    ("path",       "object.sha"),
    "github-merge_pull_request":            ("path",       "sha"),
    "github-add_issue_comment":             ("path",       "id"),
    # github (URL tail)
    "github-create_pull_request":           ("regex_url",  r"/pull/(\d+)"),
    "github-update_issue":                  ("regex_url",  r"/issues/(\d+)"),
    # canvas (14 entries)
    ...
    # woocommerce (3 entries)
    ...
}
```

**★ Frozen at this pre-registration.** 이후 B2 (매핑 149건 확대)는 별도 사전등록. 여기서는 id_bridge_scan.py의 26개 그대로.

### §1.2 `extract_id()` 함수

`id_bridge_scan.py` line 89-155 로직 이관. 세 케이스:
1. `unwrap_output` — Toolathlon envelope 처리
2. `regex_url` — URL 안 정수 추출
3. `path` / `array_path` — JSON 파싱 + JSONPath 순회

**시그니처:**
```python
def extract_entity_id(tool: str, output_text: str) -> str | None:
    """Return extracted ID string, or None if the tool is not in the mapping
    or the specific JSONPath fails on this response. Deterministic; no LLM."""
```

### §1.3 신규 pool 스캔 (`_scan_id_bridge_candidates()`)

같은 파일에 새 함수:

```python
@dataclass
class IdBridgeCandidate:
    origin_span_id: str
    candidate_span_id: str
    tool: str
    verdict: str  # "differ" | "same" | "no_id"  (내부 enum)
    origin_id: str | None
    candidate_id: str | None

def scan_id_bridge_candidates(trace: Trace) -> list[IdBridgeCandidate]:
    """Same-input side_effect pair scan. Independent of cascade.

    Pool = find_candidates(trace, N=2) filtered to cand ∈ _SIDE_EFFECT_TOOLS.
    For each pair, extract IDs from origin/candidate outputs and classify.

    Does NOT feed waste_span_ids. Does NOT feed between_window_counts.
    Purely additive report layer.
    """
    from clew.detect.structural import find_candidates
    out: list[IdBridgeCandidate] = []
    for origin, cand in find_candidates(trace, 2):
        if cand.span_kind != "tool":
            continue
        tool = cand.agent_or_node_id
        if tool not in _SIDE_EFFECT_TOOLS:
            continue
        o_id = extract_entity_id(tool, origin.output_text)
        c_id = extract_entity_id(tool, cand.output_text)
        if o_id is None or c_id is None:
            verdict = "no_id"
        elif o_id == c_id:
            verdict = "same"
        else:
            verdict = "differ"
        out.append(IdBridgeCandidate(
            origin_span_id=origin.span_id,
            candidate_span_id=cand.span_id,
            tool=tool,
            verdict=verdict,
            origin_id=o_id,
            candidate_id=c_id,
        ))
    return out
```

**★ 내부 enum 이름** — `"differ"` / `"same"` / `"no_id"` (짧음, 관측적). 렌더 문면과 겹치지 않게.

**★ 왜 category=side_effect (`_classify_category`) 대신 `_SIDE_EFFECT_TOOLS` membership 사용:**
- `_classify_category`는 이미 존재하지만 `EnrichedDetail`을 요구.
- B1 pool은 cascade + enrich를 거치지 않은 raw find_candidates 대상.
- 두 축을 독립적으로 유지하려면 low-level filter (`_SIDE_EFFECT_TOOLS` set membership)가 자연.

### §1.4 문면 (사용자 확정, frozen)

**섹션 헤더**: `## Duplicate creation check`

**섹션 서두 (필수 문단, 관측 서술)**:

```
The waste detector above requires both responses to be byte-identical.
That is the right test for reads — a re-read that returns the same
content is a redundant call. For creation tools it is reversed: if a
document really was created twice, the two responses carry different
entity IDs, so the waste detector excludes them by construction. This
section scans that excluded pool separately.
```

- "provable" 단어 미사용
- 관측 서술: "the waste detector requires... / this section scans..." (사실 진술)
- 금지어 7종 없음

**Per-candidate 문면 (frozen, 3-way):**

| verdict | 문면 |
|---|---|
| `differ` | `Both calls returned entity IDs, and they differ: {origin_id} / {candidate_id}.` |
| `same` | `Both calls returned the same entity ID: {origin_id}.` |
| `no_id` | `This tool's response contains no entity ID; whether a second entity was created cannot be determined from the trace.` |

**Per-candidate 렌더 형식 (draft):**
```
### 1. {tool}
- origin span → candidate span
- {verdict wording (one of the three above)}
```

**집계 라인 (섹션 상단, verdict distribution):**
```
- **candidates**: N pairs total
  - {differ_count} with different entity IDs ← real duplicates
  - {same_count} with the same entity ID ← API deduplicated
  - {no_id_count} without extractable entity ID ← cannot determine
```

### §1.5 기대 분포 명시 (frozen — 구현 후 검증 기준)

Toolathlon 66 파일 재렌더 시:

- Total candidates: **3,432**
- differ: **159** (4.63%)
- same: **76** (2.21%)
- no_id: **3,197** (93.16%)

**★ 93%가 `no_id`로 나오는 게 정상 동작.** 헤드라인 verdict (`differ`)가 드물게 발동함을 사전등록에 명시. 구현 후 이 분포가 재현되지 않으면 구현 오류.

**★ `no_id` 라인이 사실상 가장 값진 부분** — Ask GN에서 jrtrang이 짚은 "대부분의 중복이 추적 자체가 안 되는 구간에 있다"에 정확히 대응. 리포트에서 이 사각지대를 정직하게 노출.

### §1.6 기존 표시와의 관계 · 렌더 정책 (Q1~Q4 확정)

**결정 1 (사용자 §5): 기존 안내와의 관계 = 추가 (대체 아님).**

- `_CATEGORY_CAUSES` (기존 리포트의 category 원인 안내)는 리포트 전체에서 한 번 표시. 내용: "무엇을 봐야 하나"의 일반 원인.
- `Duplicate creation check` 섹션은 pair별 구체 판정. 정보 층위가 다름.

**결정 2 (Q1) — 섹션 위치**: **waste span 상세 (`## Wasted Span Details`) 뒤, `_POSSIBLE_CAUSES` 앞.**

근거 (사용자 인용): *"리포트가 '발견 → 설명' 순서인데, 중복 생성 검사는 발견이다. 별도 풀이라 waste 목록과 섞이면 안 되지만, 설명 구역으로 밀 것도 아니다."*

즉 리포트 순서:
```
## Result: WASTE DETECTED (or no waste detected)
[banner, category breakdown, coverage stats, aggregate]
## Wasted Span Details
[per-waste-span]
## Duplicate creation check          ← B1 신규, "발견" 구역
## Possible causes                    ← 설명
## What each category typically points to
## About categories
[footer]
```

**결정 3 (Q2) — Pool 비었을 때**: **"0 candidates" 명시 (섹션 렌더).**

근거 (사용자 인용): *"검사했는데 없는 것과 검사 안 한 것은 다르다."*

Pool 비면 (side_effect same-input pair 자체가 0인 경우) 섹션 헤더 + 서두 문단 + "0 candidates found in this trace." 라인만 렌더. 그 아래 per-candidate 상세는 없음.

**결정 4 (Q3) — Waste-0 세션에서도 섹션 렌더**: **렌더.**

근거 (사용자 인용, ★ 강한 논리):
> waste=0이어도 중복 생성은 있을 수 있다. 풀이 다르다.
>
>     cascade waste = 0   (결과가 다 달라서 걸러짐)
>     중복 생성    = 3   (ID가 달라서 진짜 두 개 생김)
>
> 이런 세션이 실제로 가능하다. 그리고 그럼 그 섹션이 유일한 발견이 된다.
> 생략하면 "낭비 없음"만 보이고 진짜 사고를 놓친다. 커버리지 배너 때랑 같은 논리인데, 여기가 더 심각하다 — 배너는 불확실성을 숨기는 것이었고, 이건 **발견 자체를 숨기는 것.**

**★ 실행 주의**: `render_markdown()`의 `if not cr.wasteful:` 조기 return 전에 `Duplicate creation check` 섹션이 렌더돼야 함. Coverage 배너와 동일 패턴. 테스트 `test_id_bridge_section_present_in_waste_zero_when_pool_nonempty` 로 잠금.

**결정 5 (Q4) — Entity ID 표시 = 전체 노출 (truncation 없음).**

근거 (사용자 인용): *"감사 목적이다. 사용자가 그 ID로 실제 문서를 찾아가서 지워야 하는데, 잘린 ID는 쓸모가 없다. Notion UUID 36자, 스프레드시트 44자면 마크다운에서 문제없다."*

- Per-candidate 렌더에서 `origin_id`, `candidate_id`를 verbatim 노출.
- 최대 예상 길이: github sha 40자, notion UUID 36자, google spreadsheet ID 44자. 마크다운에서 문제 없음.
- JSON `id_bridge_candidates[].origin_id` / `.candidate_id` 도 verbatim.

### §1.7 JSON schema 확장 (하위호환)

**신규 최상위 array `id_bridge_candidates`:**

```json
{
  "trace_id": "...",
  "wasteful": true,
  "waste_span_ids": [...],
  "between_window_counts": { ... },     // 무변
  "coverage_stats": { ... },            // 무변 (직전 PR)
  "id_bridge_candidates": [             // 신규
    {
      "origin_span_id": "...",
      "candidate_span_id": "...",
      "tool": "notion-API-post-page",
      "verdict": "differ",
      "origin_id": "290d1b2a-...",
      "candidate_id": "290d1b2a-..."
    },
    ...
  ],
  "waste_details": [ ... ]              // 무변
}
```

**★ side_effect가 아닌 pair에는 array 항목 자체를 생략.** null 필드 아님. Waste-0 세션에서도 array (빈 array []) 존재.

**하위호환:**
- 기존 소비자 (waste_span_ids / waste_details / between_window_counts / coverage_stats) 무영향.
- 신규 필드 array이므로 파싱 안 하는 소비자에게 무영향.

### §1.8 README 서브섹션 신규

**위치**: `### Tool mapping coverage` (직전 PR) 뒤에 신규 `### Duplicate creation check`.

**문면 (draft):**

```markdown
### Duplicate creation check

Clew ships two detectors with opposite logic:

| Detector | Trigger | Meaning |
|---|---|---|
| **Waste detection** | Both responses byte-identical | Same result — the second call was redundant. Right for reads. |
| **Duplicate creation check** | Two entity IDs differ | Different entities — two things really were created. Right for creation tools. |

The waste detector excludes creation-tool pairs by design — if two `notion-API-post-page` calls create two different pages, they carry different IDs, so byte identity fails and the detector doesn't flag them. The `Duplicate creation check` section in the report scans that excluded pool separately, using per-tool entity-ID extraction (26 tools currently mapped).

**On the Toolathlon benchmark** (2026-07-29 measurement):
- 3,432 same-input side-effect pairs scanned.
- 159 (4.63%) had different entity IDs → real duplicate creations.
- 76 (2.21%) had the same entity ID → API deduplicated.
- 3,197 (93.16%) had no extractable entity ID → this section reports that as an audit blind spot rather than a verdict.

The 93% `no_id` share is the honest scope: most tools don't return entity IDs in their responses (emails send success strings, SQL writes return row counts, filesystem operations return "ok"). This section makes that blind spot visible rather than hiding it. Tool mapping expansion is tracked separately.
```

---

## §2 — 검증 기준

### §2.1 필수 검증 (전부 통과해야 릴리스)

1. **waste_span_ids bit-identical** — `cand_sha256 = 5c0c94d6…d47d4`, `pair_sha256 = 742b51a7…5fd45a0`. Baseline post-coverage-transparency와 동일.

2. **between_window_counts bit-identical** — 5 enum 카운트 무변 (`1226 / 888 / 405 / 248 / 1024`).

3. **coverage_stats bit-identical** — 직전 PR의 5개 필드 무변.

4. **★ id_bridge 분포 재현 (§1.5 기대 분포)** — Toolathlon 66 파일 스캔 시:
   - `sum(candidates) = 3,432`
   - `differ = 159`
   - `same = 76`
   - `no_id = 3,197`
   신규 테스트 `test_id_bridge_toolathlon_distribution_reproduces_pool_a`.

5. **전체 pytest** (277 + 신규).

6. **신규 테스트**:
   - `test_extract_entity_id_notion_page` — 실제 notion 응답에서 `id` 필드 추출
   - `test_extract_entity_id_github_url` — `/pull/N` regex 추출
   - `test_extract_entity_id_none_when_no_field` — 응답에 필드 없으면 None
   - `test_extract_entity_id_none_on_error_response` — error 응답에서 None
   - `test_scan_id_bridge_pool_matches_side_effect_only` — 신규 pool이 정확히 side_effect 도구만 스캔
   - `test_scan_id_bridge_ignores_cascade_gate` — sha256 다른 pair도 pool에 포함
   - `test_id_bridge_verdict_differ` — 다른 ID 두 개 → differ
   - `test_id_bridge_verdict_same` — 같은 ID 두 개 → same
   - `test_id_bridge_verdict_no_id` — 한 쪽 None → no_id
   - `test_id_bridge_toolathlon_distribution_reproduces_pool_a` — §1.5 분포 재현
   - `test_waste_span_ids_bit_identical_post_id_bridge` — cascade 무변
   - `test_between_window_counts_stable_post_id_bridge` — 카운트 무변
   - `test_json_id_bridge_candidates_field_present` — 최상위 array 존재
   - `test_json_id_bridge_backward_compat_when_no_side_effect` — waste-0 or non-side-effect 트레이스에서 빈 array
   - `test_markdown_duplicate_creation_section_present` — 섹션 헤더 · 서두 문단 렌더
   - `test_markdown_section_shows_zero_candidates_when_pool_empty` — pool = 0일 때 "0 candidates" 라인 명시 (Q2 §1.6 결정 3)
   - `test_markdown_section_present_in_waste_zero_with_pool` — cascade waste = 0이지만 side_effect same-input pair 존재 시 섹션 렌더 (Q3 §1.6 결정 4, 발견 은폐 방지). ★ `render_markdown()`의 조기 return 전 렌더 확인.
   - `test_markdown_id_full_not_truncated` — entity ID verbatim 노출, `…` 절단 없음 (Q4 §1.6 결정 5)
   - `test_no_over_claim_wording_in_id_bridge_section` — §3.2 금지어 + "provable" 부재
   - `test_readme_id_bridge_subsection_matches_current_wording` — b23 §5 상시 규칙 확장

7. **§3.2 금지어 grep + "provable" 미사용 확인** — 신규 소스 · 렌더 결과 · README 전체.

8. **실 세션 렌더** — 09d9abe9 재렌더:
   - 이 세션엔 side_effect pair 없을 가능성 (targeted_writes tier에 targeted_writes 1건 있지만 Read 재조회) → 섹션이 어떻게 렌더되는지 확인.
   - Waste-0 세션에서도 섹션 렌더 여부 결정 (draft §1.4 집계 라인 "0 pairs" 표시할지 섹션 자체 생략할지).

### §2.2 KILL 조건

- 어느 카운트든 §2.1 기대치와 어긋남 → 즉시 롤백. 규칙 오류로 처리.
- Bit-identical 실패 (`waste_span_ids`, `between_window_counts`, `coverage_stats`) → 즉시 롤백. B1은 별도 축이므로 이 셋을 건드리면 코드 오류.
- 금지어 검출 또는 "provable" 렌더 문면 검출 → 문면 정정 후 재검증. 재검증 실패 시 롤백.
- Pool A 3,432 재현 실패 (Toolathlon 스캔) → 코드 오류. 롤백.
- Verdict 분포 (159 / 76 / 3,197) 재현 실패 → ID_MAPPING 이관 오류 가능성. 롤백 · 조사.

---

## §3 — Toolathlon 예측 카운트 (재확인)

**변경 후 Toolathlon 렌더 시:**

| 항목 | 값 | 근거 |
|---|---:|---|
| `waste_span_ids` sha256 | 5c0c94d6… / 742b51a7… | Cascade 무변 |
| `between_window_counts` | 1226/888/405/248/1024 (합 3791) | Rule V2 무변 |
| `coverage_stats.recognized_tools` per file | 무변 | 직전 PR |
| `id_bridge_candidates` array length (합) | **3,432** | Pool A 재현 |
| verdict `differ` | **159** | 4.63% |
| verdict `same` | **76** | 2.21% |
| verdict `no_id` | **3,197** | 93.16% |

**KILL 규칙**: 위 어느 값이든 정의와 어긋나면 코드 오류. 롤백 후 원인 분석 → 재구현.

---

## §4 — 커밋 체인 (Rule 8, squash 금지)

1. `docs(prereg): b1 id-bridge production migration pre-registration`
   - 본 문서 `docs/ID_BRIDGE_PRODUCTION_PREREG.md` 신규
   - 증거 인라인 (id_bridge_scan.py 실측 3-way 분포, cascade identity gate 발견)

2. `feat(report): entity-ID extraction + duplicate-creation candidate scan`
   - `src/clew/report/_enrich.py`:
     - `_ID_BRIDGE_MAPPING` 상수 신규 (26개)
     - `extract_entity_id()` 함수 신규
     - `IdBridgeCandidate` dataclass 신규
     - `scan_id_bridge_candidates()` 함수 신규
   - `src/clew/detect/*` — **무변**
   - `src/clew/report/_enrich.py`의 기존 함수 (`enrich`, `_classify_category`, `_classify_between_window`) — **무변**

3. `feat(report): duplicate creation check section + JSON id_bridge_candidates field`
   - `src/clew/report/markdown.py`:
     - `_DUPLICATE_CREATION_HEADER`, `_DUPLICATE_CREATION_INTRO`, `_ID_BRIDGE_VERDICT_DIFFER`, `_ID_BRIDGE_VERDICT_SAME`, `_ID_BRIDGE_VERDICT_NO_ID` 상수 신규
     - `render_markdown()`에 신규 섹션 추가 (waste-0 경로 포함 정책 draft §1.6)
   - `src/clew/report/json_report.py`:
     - `id_bridge_candidates` 최상위 array 신규 (§1.7)
   - 다른 기존 필드 · 상수 무변

4. `test(report): id-bridge extraction + pool + verdict + toolathlon distribution + json + wording guard`
   - `tests/test_id_bridge.py` 신규 (17개 테스트, §2.1 #6)

5. `docs(readme): document the two detectors + duplicate creation check subsection`
   - README에 §"Duplicate creation check" 서브섹션 신규 (§1.8)
   - 두 탐지기 논리 반대 서사 명시
   - 실 세션 렌더 예시 갱신 (Duplicate creation check 섹션 포함, §5 상시 규칙 준수)

**RESULTS 이관 없음** — id_bridge 실측 근거는 본 사전등록 §선행 근거 인라인. `field_test/diagnostics/id_bridge_*.md/py/json` 원본은 커밋 안 함 (`feedback_diagnostics_uncommitted.md` 준수).

**선행 merge**:
1. `feat/coverage-transparency` PR merge (이미 준비됨, 대기)
2. 본 확장 브랜치 (`feat/id-bridge-production` 또는 유사) 생성
3. 5 커밋 → PR → merge

---

## §5 — 후속 작업 (본 사전등록 밖)

**B2 — ID 매핑 149건 확대.** id_bridge unprovable 3,197건 중 `b_id_unmapped` 149건이 매핑 확대 대상 (`notion-API-post-database-query` 102, `pptx-open_presentation` 28 등). 별도 사전등록.
- B1 merge 후 B2 사전등록 → PR.
- B2는 카운트 이동 없음 (같은 축 확대, 재검증 부담 없음).

**옵션 3 관련 후속** — 이전 사용자 제안 "커버리지 배너에 미매핑 도구 이름 노출". Coverage-transparency PR merge 후 amend 형태로 별도 추적. B1과 무관.

**side-effect 매핑 확대** — top 40 손 분류 결과에 따른 매핑 확대. **보류** (재검증 부담 큼, 사용자 지시). B1이 별도 축으로 처리하므로 side-effect 매핑 확대의 시급성이 감소.

---

## §6 — Q1~Q4 확정 (2026-07-29)

**Q1 위치**: waste span 상세 뒤, `_POSSIBLE_CAUSES` 앞 → §1.6 결정 2에 반영
**Q2 Pool 빈 경우**: "0 candidates" 명시 → §1.6 결정 3
**Q3 Waste-0 세션**: 렌더 (발견 은폐 방지) → §1.6 결정 4
**Q4 ID 표시**: 전체 노출 → §1.6 결정 5

Q1~Q4는 사전등록 승인 시점 동결. 이후 수정 시 새 사전등록.

---

## §7 — 참조

- `field_test/diagnostics/id_bridge_scan.py` (원본 로직, 이관 대상)
- `field_test/diagnostics/id_bridge_PREREG.md` §3 (ID 매핑 정의)
- `field_test/diagnostics/id_bridge_RESULTS.md` (3-way 분포 근거)
- `field_test/diagnostics/id_bridge_unprovable_breakdown_RESULTS.md` (unprovable 세부, B2 대상)
- `docs/GREYZONE_B23_EXTENSION_PREREG.md` §5 (README 예시 재생성 상시 규칙)
- `docs/COVERAGE_TRANSPARENCY_PREREG.md` (직전 PR, 리포트 layer 확장 선례)
- `memory/feedback_observed_not_confirmed.md`
- `memory/feedback_frozen_absolutes.md`
- `memory/feedback_diagnostics_uncommitted.md`

---

_이 문서 이후 사용자 승인 대기. Q1~Q4 답 확정 시 커밋 1 (docs prereg) 부터 시작._
