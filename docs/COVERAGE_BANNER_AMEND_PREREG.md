# Coverage Banner Amend — Pre-registration (DRAFT)

**작성 시각 (UTC)**: 2026-07-29T00:00:00Z
**HEAD 해시**: `feat/id-bridge-production` (B1 완료, B2 draft 완료)
**작성**: 구현 **전** — draft만. 사용자 승인 대기.
**저자**: 클로드 (사전등록자) / 사용자 (승인자)

---

## §0 — 이 draft 가 하는 것 · 하지 않는 것

**하는 것.** Coverage-transparency PR (`af4594c`) 이 도입한
`_COVERAGE_LINE_A` 배너에 **미인식 도구 이름 (상위 N 개)** 을 노출하는
확장에 대한 문면 · 표시 규칙 · 검증 기준 draft.

**하지 않는 것.**
- 구현 · 코드 변경. Draft만.
- `coverage_stats` JSON 필드 스키마 확장 여부 (별도 조항, §4).
- 커버리지 산출 로직 변경 (재검증 부담 있음). 로직 무변.

---

## §1 — 배경 · 사용자 요청

**현재 배너 (v0.2.x+, `af4594c` merge):**
```
- **Tool mapping coverage for this trace**: 3 of 5 tools recognized (60.0%).
- **Idempotent pairs with unrecognized tool in interval**: 1 of 2.
```

**한계:**
- 60% 라는 숫자만 봐서는 "무엇이 인식 안 됐는지" 알 수 없다.
- 사용자가 이 리포트를 근거로 매핑 확대를 요청하려면 미인식 도구 이름을
  따로 grep 해야 한다.
- Ask GN 의 jrtrang 지적 (`memory/reference_public_traces_2026_07.md`
  §1.3): "audit blind spot 을 정직하게 노출한다"는 서사에서 이름이 없는
  건 절반의 노출.

**사용자 요청 (STEP 3 지시서):**
> 추가: 미인식 도구 이름을 상위 N개까지 노출
> 예: "인식되지 않은 도구 상위 5개: bigquery_run_query, google_calendar-create_event, k8s-port_forward, …"

---

## §2 — N (표시 개수) 결정 근거

**Toolathlon 6,780 traces 실측 (2026-07-29):**

Per-trace unique unrecognized 도구 이름 카운트 분포:

| Bucket | Traces | Share |
|---|---:|---:|
| 0 unrec | 1,530 | 22.6% |
| 1-3 unrec | 4,235 | 62.5% |
| 4-10 unrec | 1,012 | 14.9% |
| 11+ unrec | 3 | 0.04% |
| **Total** | 6,780 | 100% |

- Mean = 1.8, median = 1, max = 13.
- **N=5 커버리지**: 6,780 - 1,012 - 3 ≈ 90% 의 트레이스에서 미인식 전부
  노출. 나머지 15% 는 상위 5개만 노출되고 나머지는 숨겨짐.
- **N=3 커버리지**: 6,780 - (일부 4-10) ≈ 85% 완전 노출. 더 짧지만
  4-10 bucket 이 흔함.

**★ 채택: N=5.**
- 근거 1: 상위 5개면 미인식 이름을 grep 없이 리포트에서 다 볼 수 있는
  트레이스가 90%.
- 근거 2: 마크다운 라인 길이 — 도구 이름 평균 ~30자 × 5 = 150자, comma
  · space 포함 200자 이하. 한 줄에 무리 없음.
- 근거 3: 짝수보다 홀수가 시각적 sparcity 좋음 (기존 UX 관례).

**"11+ unrec" 3 트레이스 대응:** N=5 초과분은 `…` 절단 + "N more" 표시.
사용자가 필요 시 JSON `coverage_stats` (신규 필드 `unrecognized_tool_sample`)
로 이관.

---

## §3 — 배너 문면 · 표시 규칙 (draft)

### §3.1 새 3번째 라인 (Line C) — 조건: `unrecognized_tools > 0`

```
- **Unrecognized tools in this trace (top {n_shown})**: {name1}, {name2}, {name3}, {name4}, {name5}{ellipsis_and_more}
```

- `n_shown` = min(N=5, actual_unrecognized_count)
- Sort key: 트레이스 내 **span 등장 횟수 desc**, tie-break 알파벳순
  ★ 근거: 자주 등장하는 도구가 매핑 gap 의 impact 가 크다. 알파벳순 tie
  break 는 결정론.
- `ellipsis_and_more`:
  - actual > N=5: `", … (+{extra} more)"` 예: `, … (+8 more)`
  - actual ≤ N=5: 빈 문자열

### §3.2 조건: `unrecognized_tools == 0`

Line C 안 render (기존 Line A 만).

### §3.3 문면 원칙

- 금지어 7종 (§3.2 canonical) + "provable" 미사용.
- 사실 진술: 어떤 도구가 미인식이라는 관측만, 그 도구가 어떤 카테고리인
  지에 대한 판정 없음.
- 도구 이름은 backtick 없이 (마크다운 라인이 이미 bold header 아래에 있음).

### §3.4 위치

Line A / Line B 뒤, Redundant-invocation candidates 앞. 기존
COVERAGE_TRANSPARENCY_PREREG §1.1 Q1 결정의 자연 확장.

### §3.5 waste-0 브랜치에서도 렌더

Line A 가 waste-0 에서도 렌더되는 것과 동일 논리
(`COVERAGE_TRANSPARENCY_PREREG.md` §1.1 Q2). Line C 도 render.

---

## §4 — JSON schema 확장 (draft, 별도 조항)

**옵션 A — 이름 없음 (현행 유지):**
- JSON `coverage_stats.recognized_tools` = int, `unique_tools_in_trace` = int.
- 이름 정보 없음 → 프로그래밍 소비자는 JSON 만 파싱하면 미인식 이름을
  알 수 없다.

**옵션 B — 신규 배열 필드:**
```json
"coverage_stats": {
  "unique_tools_in_trace": 10,
  "recognized_tools": 7,
  "coverage_ratio": 0.7,
  "idempotent_pairs_total": 4,
  "pairs_with_unrecognized_in_between": 2,
  "unrecognized_tool_names": ["snowflake-list_tables", "canvas-canvas_health_check", ...]
}
```
- 배열 정렬 = 배너와 동일 (occurrence desc, tie alpha).
- **전체 목록** (배너 top-5 절단과 무관). 프로그래밍 소비자는 완전 목록
  접근 필요.
- 하위호환: 신규 key 이므로 옛 파서 무영향.

**★ 채택 (draft): 옵션 B.** 근거: JSON 은 인간이 보는 게 아니라 도구가
소비하는 것. 절단하면 grep 이 안 됨. 배너는 UX, JSON 은 감사 원본.

---

## §5 — 검증 기준

**① 무영향 축:**
- `waste_span_ids`, `between_window_counts` — 무변.
- `coverage_stats.unique_tools_in_trace`, `.recognized_tools`,
  `.coverage_ratio`, `.idempotent_pairs_total`,
  `.pairs_with_unrecognized_in_between` — 계산 로직 무변, 값 무변.
- `id_bridge_candidates` — 무변 (별도 축).

**② 새 필드 / 새 라인:**
- `test_coverage_line_c_present_when_unrecognized_gt_zero`
- `test_coverage_line_c_absent_when_zero_unrecognized`
- `test_coverage_line_c_names_sorted_by_occurrence_desc`
- `test_coverage_line_c_ellipsis_when_more_than_5`
- `test_coverage_line_c_no_ellipsis_when_le_5`
- `test_coverage_line_c_renders_in_waste_zero`
- `test_json_unrecognized_tool_names_field_present`
- `test_json_unrecognized_tool_names_full_not_truncated`
- `test_no_over_claim_wording_in_line_c`

**③ 문면 grep:**
- 금지어 7종 + "provable" 부재 (렌더 + 상수).

**④ README 예시 갱신 (b23 §5 상시 규칙):**
- 실 세션 렌더 예시에 Line C 포함.
- `test_readme_example_has_coverage_line_c`.

**⑤ Toolathlon 스냅샷 (선택):**
- 6,780 traces 스캔 시 Line C 노출률 = 77.4% (0-unrec 1,530 제외 후).
- 이 % 를 README 통계 표에 추가 (COVERAGE_TRANSPARENCY 서브섹션).

---

## §6 — KILL 조건

- `waste_span_ids` / `between_window_counts` / `coverage_stats` (기존 5개
  필드) 값 변경. 배너 확장은 표시 계층 확장만 — 계산 무변.
- Line C 문면에 금지어 · "provable" 검출.
- 정렬 결정론 실패 (같은 입력 → 다른 순서).

---

## §7 — 커밋 체인 draft

승인 후:
1. `docs(prereg): coverage banner amend (top-N unrecognized names)` — 
   본 문서 확정판.
2. `feat(report): coverage banner Line C + unrecognized_tool_names JSON` — 
   `_COVERAGE_LINE_C` 상수 신규, `render_markdown` · `render_json` 확장.
3. `test(report): line C rendering + JSON schema + wording guard` — 
   §5 pytest.
4. `docs(readme): update coverage banner example with Line C` — 
   b23 §5 규칙 준수.

각각 별개 커밋. squash 금지.

---

## §8 — 후속 · 별도 축

- **매핑 확대 (`clew.yaml` user-registration path)** — 로드맵. 미인식 이름
  노출만으로는 확대 안 됨. 사용자 등록 UX 는 별도 사전등록.
- **B1 · B2 (ID bridge)** — 무관 축. 이 확장으로 id_bridge_candidates 도
  영향 없음.

---

## §9 — 참조

- `docs/COVERAGE_TRANSPARENCY_PREREG.md` — Line A · Line B 도입.
- `field_test/diagnostics/greyzone_expansion_baseline.py` — sha256 baseline.
- `memory/feedback_observed_not_confirmed.md` — 관측 서술 원칙.
- `memory/reference_public_traces_2026_07.md` — audit blind spot 서사.
