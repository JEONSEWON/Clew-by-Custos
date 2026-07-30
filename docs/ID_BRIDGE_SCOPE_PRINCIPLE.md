# ID Bridge Scope Principle

**작성 시각 (UTC)**: 2026-07-31T00:00:00Z
**HEAD 해시**: `docs/id-bridge-scope-principle` (feat/id-bridge-production 위 stack)
**선행**: B1 (`docs/ID_BRIDGE_PRODUCTION_PREREG.md`).
**대체 관계**: 본 문서는 이전 draft `docs/ID_MAPPING_EXPANSION_PREREG.md` 를
git rename 해 승격한 것이다. 그 draft 의 판정 대기 항목 (Q2.1-Q2.3) 은
아래 §3 에서 종결된다.

---

## §1 — 원칙 (evergreen)

> **ID 비교는 생성(CREATE) 계열 도구에만 적용한다.**
> **조회·열기·목록 도구는 응답에 ID 를 반환하더라도 대상이 아니다.**
>
> 근거: 새 엔티티를 발급하는 연산만이 "두 응답의 ID 차이" 로부터
> "중복 생성" 을 관찰할 수 있다. 조회는 두 번 호출해도 같은 엔티티를
> 가리키므로 ID 차이가 생기지 않고, 열기는 두 번 호출해도 두 개의
> 엔티티가 생기는 것이 아니라 두 개의 핸들이 생기므로 ID 차이가
> "중복 생성" 을 뜻하지 않는다.

이 원칙은 앞으로 `_ID_BRIDGE_MAPPING` 확대 검토 시 **1차 필터**다.
어떤 도구가 후보로 올라오면 먼저 이 원칙을 통과해야 한다:

1. 이 도구 호출이 서버 측에서 새 엔티티를 발급(CREATE)하는가?
2. 응답에 담긴 ID 가 그 새 엔티티의 식별자인가? (세션 로컬 핸들이나
   기존 엔티티의 재조회 결과가 아닌가?)

두 조건 중 하나라도 아니면 매핑 대상 아님.

---

## §2 — 실측과의 정합 (B1 결과 기준)

B1 (`ID_BRIDGE_PRODUCTION_PREREG.md`) 의 Toolathlon 66-file 관측:

| 축 | 값 |
|---|---:|
| Pool (side_effect + mapped) | 3,432 pairs |
| `differ` (두 ID 다름) | 159 (4.63%) |
| `same` (두 ID 같음) | 76 (2.21%) |
| `no_id` | 3,197 (93.16%) |

`differ` 159 는 전부 **생성 계열** 도구 (notion pages create, github issues
create, canvas conversation create 등) 에서 나왔다. `patch/update/enroll`
계열 등 갱신 도구에서는 두 응답의 ID 가 다른 사례가 0건이었다 — 갱신은
기존 엔티티에 대한 것이라 두 번 호출해도 같은 ID 가 반환되고, 서버가
새 엔티티를 만들지 않기 때문이다.

즉 §1 원칙은 사후 추론이 아니라 실측 분포와 정합한다. `differ` 자체가
"서버가 발급한 새 엔티티 ID 두 개" 라는 §1 조건을 만족하는 도구에서만
발생했다.

---

## §3 — 이전 draft §6 판정 대기 항목의 종결

`docs/ID_MAPPING_EXPANSION_PREREG.md` (본 문서로 승격되기 전) 은 (b)
`id_present_unmapped` 149 pairs 를 확대 후보로 제시하고 4개 질문을
남겼다. §1 원칙 적용:

### 3.1 `notion-API-post-database-query` — 102 pairs (Q2.1.a 종결)

이름은 POST 이지만 실제 verb 는 **쿼리(검색)**. `results[0].id` 는
검색 결과 첫 항목의 페이지 UUID 이고, 이 API 호출이 그 페이지를
만든 것이 아니다. 같은 쿼리를 두 번 하면 같은 UUID 리스트가 반환되므로
`same` 으로 판정되지만 — 애초에 생성된 엔티티가 없다. 범주 오류.

**판정: 매핑 대상 아님.**

(§1 조건 1 실패. 부수적으로 Q2.1.b — 이 도구를 `_SIDE_EFFECT_TOOLS`
에서 옮길지 — 는 여기서 답하지 않는다. side_effect membership 은
category / between_window / coverage 재검증을 요구하는 별도 축이다.)

### 3.2 `pptx-open_presentation` — 28 pairs (Q2.2.a 종결)

"열기" 는 생성이 아니다. 같은 파일을 두 번 열면 `presentation_id` 로
서로 다른 세션 핸들 (`presentation_1`, `presentation_2`) 이 반환되지만,
두 개의 프레젠테이션이 만들어진 것이 아니라 같은 파일에 대한 두 개의
읽기 세션이 만들어진 것이다. ID 가 다르다는 사실을 "중복 생성" 으로
판정하는 것은 거짓 양성.

**판정: 매핑 대상 아님.**

(§1 조건 2 실패 — ID 는 서버가 발급했더라도 새 엔티티의 식별자가 아님.)

### 3.3 나머지 5개 OOS 도구 — 19 pairs (Q2.3 종결)

**판정: B3 로 이관.** 볼륨이 작고 (합 19, unprovable 3,197 의 0.59%),
도구별 판정 재료 수집 비용 대비 실익이 낮다. 대상 도구 목록과 응답
샘플은 `field_test/diagnostics/id_bridge_unprovable_breakdown_RESULTS.md`
§4 에 남아있다.

---

## §4 — B2 종결 요약

- 149 pairs 중 **130 pairs (102 + 28) 는 §1 원칙상 매핑 대상 밖**.
- **19 pairs 는 B3 이관**. 별도 사전등록 시 재검토.
- **현 시점 `_ID_BRIDGE_MAPPING` 확대분 = 0.** 26 도구 그대로 유지.
- **코드 변경 없음.** `waste_span_ids`, `between_window_counts`,
  `coverage_stats`, `id_bridge_candidates` 어느 것도 이 결정으로
  변하지 않는다.

---

## §5 — 앞으로의 매핑 확대 절차 (규범)

새 도구가 매핑 후보로 올라오면:

1. **§1 원칙 통과 확인.** 생성 verb 인가, 응답 ID 가 새 엔티티 식별자인가.
2. 통과 시 응답 3건 관측 (unprovable_breakdown 스크립트 재활용).
3. 판정 결과를 신규 사전등록 문서에 명시 (B1 §1.1 mapping 확장 형식).
4. 무영향 축 (`waste_span_ids`, `between_window_counts`, `coverage_stats`)
   불변 재검증 후 merge.

§1 실패 (조회·열기·목록 등) 도구는 위 2-4 로 진행하지 않는다.

---

## §6 — 참조

- `docs/ID_BRIDGE_PRODUCTION_PREREG.md` — B1. 26-tool mapping 및 pool
  정의.
- `field_test/diagnostics/id_bridge_unprovable_breakdown_RESULTS.md` —
  (a) no_id_field / (b) id_present_unmapped / (c) error 분해.
- `field_test/diagnostics/id_mapping_expansion_samples.py` — Q2.1 · Q2.2
  후보 도구 응답 dump (uncommitted, `feedback_diagnostics_uncommitted.md`).
- `memory/feedback_no_hypothetical_case_judgment.md` — CLI 원리-판정
  금지. 본 §3 판정은 각 도구의 실제 응답 관측 후 사용자 판정을 문서화한
  것이지 CLI 가 원리적으로 결정한 것이 아니다.
