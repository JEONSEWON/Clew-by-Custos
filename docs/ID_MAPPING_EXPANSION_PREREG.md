# B2 — ID Mapping Expansion Pre-registration (DRAFT)

**작성 시각 (UTC)**: 2026-07-29T00:00:00Z
**HEAD 해시**: `feat/id-bridge-production` (커밋 chain 5개 완료, PR 미개설)
**작성**: 구현 **전** — draft만. 사용자 승인 대기.
**저자**: 클로드 (사전등록자) / 사용자 (승인자)
**선행**: B1 (`docs/ID_BRIDGE_PRODUCTION_PREREG.md`) merge 필수.

---

## §0 — 이 draft 가 하는 것 · 하지 않는 것

**하는 것.** `_ID_BRIDGE_MAPPING` (B1 §1.1) 26개를 얼마나 확대할지에 대한
관측적 근거를 정리. 후보 도구 각각의 실제 응답 3건씩을 여기 인용. 확대
가정 하 카운트 이동을 예측.

**하지 않는 것.**
- 어떤 필드가 "엔티티 ID"인지 판정 (사용자 판정 사항).
- 매핑 확대 실행 · 코드 변경. Draft만.
- `waste_span_ids`, `between_window_counts`, `coverage_stats` 어느 것도
  건드리지 않음. B2 도 B1 과 같이 별도 축.

★ CLI 원리-판정 금지 원칙 (`memory/feedback_no_hypothetical_case_judgment.md`):
어떤 필드가 서버 발급 엔티티 ID 인지, 아니면 세션 로컬 핸들 · 요청 메타 ·
쿼리 결과 리스트의 재생성 ID 인지 — 판정은 사용자.

---

## §1 — 후보 도구 목록 (id_bridge_unprovable_breakdown §4 근거)

Pool A 3,432 pairs / 3,197 unprovable 중 `(b) id_present_unmapped` 로
분류된 149 pairs. 사실상 두 도구가 지배 (합 130), 나머지 19는 5개 OOS
도구에 얇게 분포.

| # | Tool | (b) pairs | (b) share of unprovable | 후보 필드 (관측) |
|---|---|---:|---:|---|
| 1 | `notion-API-post-database-query` | 102 | 3.19% | `results[].id` (page UUID) |
| 2 | `pptx-open_presentation` | 28 | 0.88% | `presentation_id` (string) |
| 3 | 그 외 (5개 OOS 도구) | 19 | 0.59% | 개별 판정 필요, 카운트 낮음 |

★ **`(b)` 는 unprovable 3,197 중 149 = 4.7%.** 대부분 (a) no_id_field
2,011 (63%) 과 (c) error 1,037 (32%) 이 차지. 매핑 확대로 옮길 수 있는
파이는 원리적 상한이 149.

---

## §2 — 실제 응답 샘플 (각 도구 3건, 원문 head 인용)

★ 판정 재료. CLI 는 아래 필드 중 어느 것이 엔티티 ID 인지 결정하지
않음. 원본 dump: `field_test/diagnostics/id_mapping_expansion_samples.json`
(uncommitted per `feedback_diagnostics_uncommitted.md`).

### 2.1 `notion-API-post-database-query` (102 pairs)

**샘플 1** (`trace_id=4500b0df…`, span `toolu_014h95D8…`):
```json
{"object":"list","results":[
  {"object":"page","id":"291d1b2a-54b2-810a-b2cb-d2c576f0271c",
   "created_time":"2025-10-19T04:18:00.000Z",
   "parent":{"type":"database_id","database_id":"291d1b2a-54b2-81b6-9a91-eef7882b6b88"},
   ...},
  {"object":"page","id":"291d1b2a-54b2-81ba-b983-ef93896254ec",
   ...}
]}
```

**샘플 2** (`trace_id=4500b0df…`, span `toolu_014PEr4pERngv5CrkVXYA9KP`):
- 샘플 1과 완전히 동일한 body 구조. results[0].id도 같은 UUID.
- 즉 같은 database 를 같은 filter 로 두 번 쿼리 → 같은 페이지 리스트 반환.

**샘플 3** (`trace_id=26ea643d…`, span `toolu_011Hiv6apsVqgyB8uVwYfjUA`):
- 다른 trace, 다른 database. results[0].id = `291d1b2a-54b2-812f-9e27-d0720b012d38`.
- 이 페이지들은 이 tool call 로 "생성"된 게 아니라, 기존 DB 를 쿼리한 결과.

**관측 (판정 유보):**
- `results[].id` 는 이미 존재하는 페이지 UUID. 이 API call 이 페이지를
  만든 게 아님 (verb = query, not create).
- 같은 args 로 두 번 쿼리하면 같은 UUID 리스트가 온다 (샘플 1 vs 2 확인).
- 만약 이 tool 을 매핑에 추가하면, verdict 는 대부분 `same` 이 될 것.
  `differ` 로는 거의 오지 않을 것 (같은 쿼리가 어떤 이유로 서로 다른
  페이지 UUID 리스트를 반환하는 경우는 database 상태 변화 시나리오만).
- **문제**: `notion-API-post-database-query` 는 `_SIDE_EFFECT_TOOLS` 에
  포함되어 있음 (`src/clew/report/_enrich.py:163`). 이는 POST verb 근거.
  실제 read/query 성격. 이 도구를 side_effect 로 두는 게 옳은지 별도
  검토 필요 (본 draft 밖).

**사용자 판정 필요 사항:**
- Q2.1.a: `results[].id` 를 (query 결과의 페이지 UUID 를) "엔티티 ID" 로
  ID-bridge 로직에 넘길지. Yes → `same` 카운트 +102 (원리 상한). No →
  변화 없음.
- Q2.1.b: 별도 축의 문제 — 이 도구가 `_SIDE_EFFECT_TOOLS` 에 남아야 하는지.
  read 로 옮기면 B1 pool 에서 제외돼 이 102 는 자연히 사라짐.

---

### 2.2 `pptx-open_presentation` (28 pairs)

**샘플 1** (`trace_id=1a2398cd…`, span `function-call-11393134185883677249`):
```json
{
  "presentation_id": "presentation_1",
  "message": "Opened presentation from Compile.pptx with ID: presentation_1",
  "slide_count": 26
}
```

**샘플 2** (같은 trace, span `function-call-12271918267083776354`):
```json
{
  "presentation_id": "presentation_2",
  "message": "Opened presentation from Compile.pptx with ID: presentation_2",
  "slide_count": 26
}
```

**샘플 3** (같은 trace, span `function-call-11393134185883677249` — 샘플 1과 같은 span_id 재출현):
- 샘플 1과 동일.

**관측 (판정 유보):**
- `presentation_id` 값이 `"presentation_1"`, `"presentation_2"` — 서버 발급
  UUID 가 아니라 **세션 로컬 카운터** 모양. 같은 파일을 두 번 열면 슬롯
  1 · 슬롯 2 로 각각 다른 핸들 부여.
- `message` 는 "Opened presentation from Compile.pptx" — 같은 파일에서
  두 번 open 이 실제로 두 개의 파일 사본 · 세션을 만드는가, 아니면 같은
  read-only view 를 두 번 여는가는 이 응답만으로 알 수 없음 (도구 내부
  스펙 필요).

**사용자 판정 필요 사항:**
- Q2.2.a: `presentation_id` 를 엔티티 ID 로 취급할지. Yes → 대부분
  `differ` (동일 args 로 열 때마다 새 슬롯 부여 → 다른 ID). 이 경우
  `differ` +28 로 이동. 하지만 실제로 두 개의 파일이 만들어진 것인지는
  별도 확인.
- Q2.2.b: `presentation_id` 가 세션 로컬 핸들이라면, "duplicate creation"
  판정 근거로 부적합. `no_id` 유지가 맞음.

---

### 2.3 나머지 5개 OOS 도구 (합 19 pairs)

★ 저빈도. 확대 실익 vs 재검증 부담 균형이 나쁨. B2 는 위 두 도구에
집중. 나머지는 B3 로 별도 이관 or 미실행.

(id_bridge_unprovable_breakdown_RESULTS.md §4 표: "others (rest) 19
mixed"). 개별 도구명은 raw dump 확인 필요.

---

## §3 — 확대 시 예상 카운트 이동 (원리 상한, 판정 결과 조합별)

**★ 무영향 · 절대 불가침 축** (B1 §2.1 KILL 조건과 동일):
- `waste_span_ids` bit-identical.
- `between_window_counts`.
- `coverage_stats`.

이 셋은 B2 어떤 시나리오에서도 변하지 않음 — B2 는 `_ID_BRIDGE_MAPPING`
확대만 하고 pool 정의 (side_effect membership) 는 안 건드림.

**변할 수 있는 것: id_bridge_candidates verdict 분포.**

시나리오 A — Q2.1.a=No / Q2.2.a=No (매핑 확대 없음):
- Pool 3,432 / differ 159 / same 76 / no_id 3,197. **B1 과 동일.**

시나리오 B — Q2.1.a=Yes / Q2.2.a=No (notion query만 추가):
- Pool 3,432. differ 159 (변화 없음, 쿼리 결과가 매번 같은 UUID 반환하므로
  거의 `same`). same 76 + 102 = **178**. no_id 3,197 - 102 = **3,095**.

시나리오 C — Q2.1.a=No / Q2.2.a=Yes (pptx만 추가):
- Pool 3,432. **differ 159 + 28 = 187 (판정에 따라 달라짐)**. same 76
  (변화 없음). no_id 3,197 - 28 = **3,169**.
- ★ 단, presentation_id 가 세션 로컬 핸들이면 이 이동은 사실을 왜곡함
  (duplicate creation 이 아닌데 differ 로 잡음 → false 발견).

시나리오 D — 둘 다 Yes:
- differ 187, same 178, no_id 3,067. 합 3,432.

★ **B1 §1.5 재현 gate 는 B2 이후 재정의됨.** B2 merge 시 §1.5 프리즌
분포는 시나리오별로 다시 락 걸어야 함 (별도 사전등록 조항).

---

## §4 — 검증 기준 (B2 승인 후 구현 시 적용)

**① 무영향 축 (강제):**
- `waste_span_ids` cand_sha256 = `5c0c94d6…d47d4` (B1 baseline 과 동일).
- `pair_sha256` = `742b51a7…5fd45a0`.
- `between_window_counts` = {1226, 888, 405, 248, 1024}.
- `coverage_stats` = B1 baseline 동일.

어느 하나라도 어긋나면 코드 오류. 롤백.

**② 새 카운트 (승인된 시나리오 기준):**
- 시나리오별 새 distribution (§3) 을 pytest 로 락.
- 예: 시나리오 B 승인 시 `test_id_bridge_toolathlon_distribution_post_expansion`
  = 3,432 / 159 / 178 / 3,095.

**③ 문면 (frozen):**
- `Duplicate creation check` 섹션 문면 무변 (B1 §1.4 그대로).
- 매핑 확대는 **어떤 도구가 mapping 에 있는지의 문제**이지 렌더 문면의
  문제가 아님.
- 금지어 7종 + "provable" 미사용 유지.

**④ 새 테스트:**
- `test_extract_entity_id_notion_query_returns_first_result_id`
- `test_extract_entity_id_pptx_open_presentation` (판정 결과에 따라
  포함/제외)
- `test_scan_id_bridge_pool_size_stable_post_expansion` — pool 3,432
  무변 (매핑 확대는 pool 정의를 안 건드림).

**⑤ 판정 근거 문서화:**
- B2 승인 답변에 Q2.1.a, Q2.1.b, Q2.2.a, Q2.2.b 결정 근거 명시.
- 도구 벤더 문서로 뒷받침 시 URL 인용 (Notion API, pptx-tools spec).

---

## §5 — KILL 조건

- `waste_span_ids` / `between_window_counts` / `coverage_stats` 무변 실패.
- Pool 크기 (3,432) 변경 발생 → pool 정의 (side_effect membership) 실수로
  변경된 것. 롤백.
- 어떤 새 mapping entry 가 pool 밖의 도구에 대해 정의됨 (즉
  `_SIDE_EFFECT_TOOLS` 에 없는 도구를 mapping 에 추가) — B2 범위 초과.

---

## §6 — 판정 대기 항목 (사용자에게)

**Q2.1.a** — `notion-API-post-database-query.results[0].id` 를 ID-bridge
로직에 넘길지. Yes / No.
- Yes 근거 후보: 쿼리 결과의 첫 페이지 UUID 는 안정적 (같은 쿼리 → 같은
  결과). "duplicate creation" 관점에서 `same` verdict 는 의미 있음 —
  "쿼리를 두 번 했지만 새로 생긴 페이지는 없다" 서사.
- No 근거 후보: 이 도구는 read/query. 그 도구를 duplicate creation check
  로 보는 것 자체가 category 오류.

**Q2.1.b** — `notion-API-post-database-query` 를 `_SIDE_EFFECT_TOOLS` 에서
`_IDEMPOTENT_TOOLS` 로 이동할지. 
- Yes 시: 이 도구는 B1 pool 에서 자연히 제거. 102 사라짐. 하지만
  category / between_window / coverage 계산에 영향 (side_effect → idempotent).
  ★ 이건 별도 재검증 축. **B2 범위 밖.** 필요 시 별도 사전등록.

**Q2.2.a** — `pptx-open_presentation.presentation_id` 를 엔티티 ID 로
취급할지.
- ★ 이 응답만으로는 세션 로컬 핸들인지 서버 발급 ID 인지 판정 불가.
  도구 스펙 문서 확인 필요. 사용자가 판정.

**Q2.3** — 나머지 5개 OOS 도구 (19 pairs) 는 B3 로 이관할지 / 이번 B2
에 함께 포함할지.

---

## §7 — 커밋 체인 draft (Rule 8)

승인 후:
1. `docs(prereg): b2 id mapping expansion (frozen decisions)` — 본 문서
   확정판 (판정 결과 반영).
2. `feat(report): id-bridge mapping expansion` — `_ID_BRIDGE_MAPPING` 
   entries 추가.
3. `test(report): mapping expansion coverage + distribution lock` — 
   시나리오별 pytest.
4. (선택) `docs(readme): id-bridge coverage update` — README 의 
   "26 tools currently mapped" → 새 숫자로.

**★ 판정 없이 코드 작성 금지.** 이 draft 는 판정 재료 제출까지.

---

## §8 — 참조

- `docs/ID_BRIDGE_PRODUCTION_PREREG.md` — B1 (본 draft 의 base).
- `field_test/diagnostics/id_bridge_unprovable_breakdown_RESULTS.md` — 
  (b) 149 tool-by-tool 분해 근거.
- `field_test/diagnostics/id_mapping_expansion_samples.py` — 본 draft §2
  의 응답 3건씩 dump 스크립트 (uncommitted).
- `field_test/diagnostics/id_mapping_expansion_samples.json` — dump 원본
  (uncommitted).
- `memory/feedback_no_hypothetical_case_judgment.md` — CLI 원리-판정 금지.
- `memory/feedback_diagnostics_uncommitted.md` — diagnostics 미커밋 원칙.
