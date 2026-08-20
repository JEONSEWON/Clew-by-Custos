# Cascade Absence-Sentinel Amendment — 결과

`docs/CASCADE_ABSENCE_SENTINEL_AMENDMENT_PREREG.md` 구현 결과.
사전등록 = PR #121 (`a809d7d`) · 구현 = `2409644`.
전부 `PYTHONPATH=src` 실행. 사전등록 후 detector 변경은 구현 커밋 하나뿐이다.

## 0. 확정된 결정 (사전등록 §6)

| | 선택 | 비고 |
|---|---|---|
| Q1 센티넬 집합 | **S2** | 정확 일치 `(Bash completed with no output)` + `No matches found` 접두 |
| Q2 구현 방식 | **A** | `Span.output_is_absent` additive · `model.py` 불변식 무변 |
| Q3 리포트 스키마 노출 | **안 함** | `src/clew/report/` 에 span 일괄 직렬화 없음 → 자동 충족 |
| Q4 타 어댑터 훅 | **훅만 · 집합 비움** | 단 `exgentic.py` 는 제외 — §3 참조 |

## 1. 예측 대조 — 7건 중 6건 적중, 1건 오예측

| | 예측 | 실측 | 판정 |
|---|---|---|---|
| P1 | CC 40 세션 31 → 9 | **31 → 9** | 적중 |
| P2 | Corpus B 347 → 347 | **347 → 347** | 적중 |
| P3 | `0c33c4fb` 6 → 0 | **6 → 0** | 적중 |
| P4 | `18c2eb67` 17 → 3 | **17 → 3** | 적중 |
| P5 | 비용 필드 무변 | **완전 무변** (아래) | 적중 |
| **P6** | `union_wr_char` 무변 | **0.989674 → 0.989671** | **오예측** |
| P7 | 스키마·coverage 무변 | 최상위 키 집합 동일 · `coverage_ratio` 동일 | 적중 |

### P5 상세 (`0c33c4fb` · 변경 전/후 JSON 필드 대조)

| 필드 | 전 | 후 |
|---|---|---|
| `total_llm_input_cost` | 21.0948425 | 21.0948425 |
| `total_llm_output_cost` | 2.958225 | 2.958225 |
| `total_analyzed_cost` | 24.0530675 | 24.0530675 |
| `total_waste_cost` | 20.69691232 | 20.69691232 |
| `waste_ratio` | 0.860469 | 0.860469 |
| `accuracy_flag` | accurate | accurate |
| `breakdown.provable_duplicate` | 0.0 | 0.0 |
| `breakdown.context_resend` | 20.69434363 | 20.69434363 |
| `breakdown.redundant_read` | 0.00256869 | 0.00256869 |

### P6 오예측 — 사유와 크기

`union_wr_char` 는 **움직인다.** `per_detector.repeat.waste_bytes` 가 이 트레이스에서
**186** 이었다 (플래그 6건 × 31 바이트). 나는 agent-race 트레이스에서 `repeat` 가 0.0
이었던 것을 일반화했는데, 거기서 0 이었던 이유는 **플래그가 애초에 0건**이어서였다.
플래그가 있으면 바이트도 있다.

| | 전 | 후 | 델타 |
|---|---|---|---|
| `per_detector.repeat.waste_bytes` | 186 | **0** | −186 |
| `union_wr_char` | 0.989674 | **0.989671** | **−3.0e-06** |
| `union_wr_cost` | 0.110887 | 0.110887 | 0 |
| `total_input_bytes` | 69,314,894 | 69,314,894 | 0 |

방향은 낭비를 **덜** 주장하는 쪽이다 (노이즈를 뺐으므로 옳은 방향).
크기는 분모의 약 2.7e-06. 공개 코퍼스 수치는 소수 1자리로 인용하므로
(Corpus A 99.3% char) **공개된 어떤 수치도 움직이지 않는다.**
그러나 "무변" 은 틀린 진술이었다. 사전등록 §5 는
*"플래그된 바이트만큼 변하고 그 크기는 분모의 ~1e-5"* 로 써야 했다.

기타 의도된 변화 (`0c33c4fb`): `wasteful` True→False · `waste_span_count` 6→0 ·
`waste_details` 6행→0행 · `category_counts.unclassified` 6→0.

## 2. 플래그 내용 — 무엇이 사라졌고 무엇이 남았나

### CC (로컬 세션 40건)

`tool spans` 8,641 · 플래그 **31 → 9** · 플래그 보유 세션 7 → 5.

제거된 22건 = 전부 부재 표현:

| 건수 | 문자열 |
|---|---|
| 20 | `(Bash completed with no output)` |
| 2 | `No matches found\n\nFound 0 total occurrences across 0 files.` |

생존 9건 (길이 min 4 · p50 90 · max 118): 96자·90자 파일 조각 각 2건(중복 읽기 후보) ·
Edit 성공 확인문 2건 · `Updated task #1 status` · `done` · `<tool_use_error>Cancelled: …`.
**생존분은 이 개정안의 대상이 아니다.** Edit 중복과 파일 조각은 실제 후보로 남는다.

### Corpus B (Toolathlon · 4 파일 · 240 트레이스)

`tool spans` 6,250 · 플래그 **347 → 347** · `by span_kind {'tool': 347}` 동일.
상위 기여 무변: `emails-send_email` 139 · `local-claim_done` 138 ·
`terminal-run_command` 13 · `excel-write_data_to_excel` 9.

**Corpus B 는 단 한 건도 잃지 않았다.** 개정안 범위 판정이 유지된다.

## 3. 사전등록에서 벗어난 것 1건

Q4 는 "Toolathlon / Exgentic 어댑터에 훅" 이었으나 **`exgentic.py` 는 제외했다.**
사유: `llm` · `chain` span 만 만들고 **tool span 을 만들지 않는다**
(`grep 'span_kind="tool"' src/clew/ingest/*.py` → `claude_code.py` ·
`redundancy_bench.py` · `toolathlon.py` 만). 훅을 걸 대상이 없다.
사전등록이 이 사실을 기록하지 않았다.

`redundancy_bench.py` 는 tool span 을 만들지만 손대지 않았다 — 벤더 어댑터가 아니라
벤치 로더이고, 필드 기본값이 False 이므로 동작 무변.

## 4. 동결 가드 — strict xfail (삭제·skip 아님)

`tests/test_build_set_regression.py::test_seed42_manifest_sha_matches_frozen` 발화.
그 테스트 docstring 이 `defaults` 를 잡는 대상으로 명시하므로 **올바른 발화**다.

사전등록 §7.5 · `feedback_intentional_drift` 에 따라 가드를 삭제·skip 하지 않고
`xfail(strict=True)` + 사유를 남겼다. drift 범위는 주장이 아니라 **산출물 단위 검증**:

| 검증 | 결과 |
|---|---|
| 생성 파일 집합 | 전후 동일 (80개) |
| `output_is_absent` 제거 후 내용 비교 | **80개 중 0개 상이** |
| `set_manifest.json` | 단일 키 `traces_combined` 만 상이 |
| `labels.jsonl` | 바이트 동일 |
| 동결 셋에서 `output_is_absent=True` span | **0개** → 새 skip 이 이 셋의 탐지를 바꿀 수 없음 |
| sha | `a205a3d6…` → `a83085c3…` (직렬화 기인) |

`strict=True` 이므로 나중에 재동결하면 XPASS 가 되어 마커를 의도적으로 제거하게 된다.
해소 경로 = `validation/CRITERIA_FROZEN.md` 의 sha 재핀. 그것은 stage1-freeze
재현 앵커 재동결이므로 **별개 결정**이며 이 개정안에 포함하지 않는다.

## 5. 테스트

`PYTHONPATH=src python -m pytest -q` → **706 passed, 1 xfailed** (702 → +5 신규, 1건 xfail 전환).

detector 4건: 부재-대-부재 미플래그 · origin 측 대칭 skip(단측 검사가 놓칠 방향) ·
미표시 span 은 종전 동작 유지(Corpus B 보장의 축소판) · 기본값 False.
어댑터 1건: 6 페이로드 — 정확 일치 · 좌우 공백 · 접두 규칙 · 접두가 아닌 근접 미스(미매칭 확인) ·
평범한 짧은 출력, 각각 placeholder 텍스트가 계속 실려 있는지도 확인.

## 6. 범위 밖 · 미해결

1. **비용 산출 무변.** cascade 도구 출력 가격은 별건 dry-run 이 기각
   (`field_test/diagnostics/_cascade_pricing_dryrun_RESULTS.md`).
2. **Corpus C(Exgentic) 미측정** — tool span 이 없어 이 개정안과 무관하나 확인은 안 했다.
   Corpus B 는 4파일 240 트레이스 표본이고 전량 6,780 이 아니다.
3. **Corpus A 공개 수치 재계산 안 함.** P6 크기(~3e-06)로 보아 소수 1자리 인용은
   불변일 것으로 판단하나 28 세션 전량 재실행으로 확인하지 않았다.
4. **부수 관측 (미해결)**: Corpus B 4파일에서 어댑터가 `ValueError` 로 하드 실패한
   엔트리 **23건** (`tool_calls.function.arguments` JSON 파싱). `iter_toolathlon_traces`
   가 제너레이터이므로 1건이 파일 전체를 중단시킨다. 별건.
5. **`io.save_trace` 는 새 키를 쓴다.** 이후 저장된 트레이스 파일에 `output_is_absent`
   가 실린다. 구 파일은 기본값으로 계속 로드된다. 리포트 JSON 은 무영향(Q3).
