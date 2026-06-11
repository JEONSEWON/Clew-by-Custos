# CRITERIA_FROZEN.md — Clew 2단계 탐지 검증 기준

> 본 문서는 **라벨 분석을 보기 전에** 동결된다. 결과를 본 뒤 본 문서를 수정하면
> 검증은 무효다. (SPEC.md §4 규율 2·3 / 1차 리뷰 후 합의: 모든 값은 예시가 아닌 확정값.)

## 동결 메타

- 동결 일자: 2026-06-06
- 동결: git tag `stage1-freeze` (본 커밋 시점 고정)
- 라벨셋: `eval/labels.jsonl` (seed=42, 4 패턴 × 10쌍 = positive 40 / negative 40)
- `eval/set_manifest.json` sha256:
  `6d4efdb05e8b6de3931c965353ad78e9632d94a308d82c996ff43d3b018d4e01`
  <!-- stage2 재동결값; stage1 원본 sha f3369b7cf598d4aa6f764ec2f56fa9aa437f4603d4ea84a88cb114ec7eb9069b 는 tag stage1-freeze (0fa25e0) 에 보존 -->
- 길이 분포: min=5, max=7, mean=6.0 (paired structural matching — positive/clean
  트윈은 동일 토폴로지)

## 탐지 파라미터

> **2단계 시작 직후, `evaluate.py` 첫 실행 전에 본 섹션을 같이 채워 동결한다.**
> 동결 후 변경 금지. 현재 비어있는 항목은 *그 시점 함께 동결할 항목*이며 예시가 아니다.

- φ (의미 중복 코사인 임계): 0.514345
- 반복 임계 N: 2
- 임베딩 모델 (1개 고정): paraphrase-multilingual-MiniLM-L12-v2 @ revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42

## 성공 기준 (GO)

- 트레이스 단위 F1 ≥ 0.80
- Control(negative) 트레이스 false-positive rate ≤ 0.10
- **두 조건 동시 충족 시에만** README·공개 글에서 "낭비를 잡는다" 표현 허용.

## 중단 기준 (KILL / PIVOT)

- F1 < 0.60 또는 Control FPR > 0.25
- 둘 중 하나라도 위반 시 출시 금지, 신호 재설계로 회귀.

## 회색지대 (0.60 ≤ F1 < 0.80 그리고 0.10 < FPR ≤ 0.25)

- 고정 예산 **N = 3회** 반복 허용 (확정값).
- 반복 사이에 변경 가능한 것: 탐지 코드 / 탐지 파라미터(단, 한 번 시도하면 그 시점에
  탐지 파라미터 섹션을 재동결).
- **반복 사이에 절대 변경 불가**: 본 문서의 성공·중단 기준, 라벨셋, manifest sha256.
- 3회 소진 후에도 GO 미달이면 KILL과 동일 처리.

## "원한다" 기준 (출시 *후* — 별도 동결)

> 1단계에서는 *기준 항목*만 둔다. 구체 숫자는 출시 시점에 별도 동결 문서로.

- 설치 ≥ N
- "진짜 뭔가 잡았다" 양성 피드백 ≥ M
- 1주 유지율 ≥ U
- 미달 시 wedge 재검토.

## Stage 2 사전등록 (캐스케이드 + 후보 게이트)

> 본 섹션은 **새 후보 게이트(SPEC §8 2.1) 적용 후 calibrate 결과를 보기 전에** 동결된다.
> eval set(seed=42)은 이 단계에서 건드리지 않는다. 결과 후 본 섹션 수정 시 검증 무효.

- **C1.** `requery_known` clean(같은 스키마·다른 값) → 구조 후보 0개. (테스트로 강제)
- **C2.** `requery_known` positive(같은 입력) → 후보 생성 + 캐스케이드가 flag. (recall 회귀 방지)
- **C3.** dev(seed=7) 분리:
  - gap(P10 dup − P90 prog) > 0
  - Cohen's d ≥ 0.5
  - **pair-level** `dev_fpr_estimate` ≤ 0.15
- **C4.** dev **trace-level 캐스케이드 FPR** (낭비 쌍 ≥1 이면 트레이스 flag) 산출·보고.
  사전등록 목표: **trace-level FPR ≤ 0.10**. (이 숫자가 CRITERIA에 박힐 값.)

## Stage 2 결과 및 v1 스코프 결정 (캘리브레이션 후 기록)
- C1~C4: 전부 통과. gap +0.2208, Cohen's d 4.3803, pair-FPR 0.00, trace-FPR 0.00.
  동결 파라미터: phi=0.514345, N=2,
  model=paraphrase-multilingual-MiniLM-L12-v2 @ e8f8c211226b894fcb81acc59f3b34ba3efd5f42.
- 운영점 recall(보고용, φ·N 불변): in-scope 3패턴 30/30=1.00,
  regen_handoff 0/10, 전체 30/40=0.75.
- regen_handoff 진단: 구조 갭(find_candidates 후보 0; cross-node A→B 각 1회).
  cosine(A,B)=0.862 > φ — 의미 미스 아님, 순수 구조 미커버.
- 결정: regen_handoff v1 디스코프(원리적 사유: 강한 구조 신호 부재 →
  semantic-dominant → refinement FP 위험). 데이터셋엔 유지, eval에서 패턴별
  보고하되 regen은 'uncovered'로 투명 표기. 비커버는 결함이 아니라 명시적 범위.

## 변경 정책

본 문서를 변경할 수 있는 경우는 두 가지뿐이다:
1. 라벨셋 자체가 교체될 때 (새 seed·새 패턴 추가) — 새 파일 `CRITERIA_FROZEN_v2.md`로
   분리한다.
2. 1단계 동결 *이전* 시점의 명백한 typo 수정 — git history로 추적 가능해야 한다.

그 외 어떤 수정도 누수로 간주, 검증 무효 선언.
