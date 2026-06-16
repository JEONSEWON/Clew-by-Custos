# Clew

> 멀티에이전트 트레이스에서 헛도는 cycle을 추적하는 *실타래*. 회사 **Custos**.

**현재 상태: Stage 3 완료 + 실측 검증 통과.**
탐지 로직 구현·평가 GO·CLI·실제 LLM 트레이스 검증까지 완료.
검증 결과와 한계는 아래 [검증 결과](#검증-결과) 섹션에 정직하게 기록한다.

자세한 맥락은 `CLAUDE.md` · `SPEC.md` · `validation/CRITERIA_FROZEN.md` 참조.

---

## 실행 환경

Windows / macOS / Linux 동일. Python 3.11+ 필요. `uv`가 있으면 자동으로 사용,
없으면 `pip`로 폴백.

```
python tasks.py install        # 의존성 설치
python tasks.py test           # 모든 테스트 (158+)
python tasks.py generate-set   # 검증 라벨셋 생성 (seed=42, 4 패턴 × 10쌍)
python tasks.py check-leak     # 누수 가드만
python tasks.py dod            # DoD 자동 점검
python tasks.py all            # install → generate-set → test → check-leak
```

`uv`가 설치된 경우 직접 호출도 가능:
```
uv sync --extra adapter --extra dev
uv run pytest -v
```

---

## Quickstart

트레이스 파일을 받아 낭비 리포트로 돌려주는 3단계.

**1. 설치**
```bash
pip install -e ".[adapter,detect]"
```

**2. 캡처 — LangGraph 앱 트레이스를 파일로 저장**
```python
from clew.capture import capture_to_file
from pathlib import Path

# app: compiled LangGraph app
trace = capture_to_file(app, {"topic": "..."}, Path("trace.json"))
```

**3. 분석**
```bash
python -m clew analyze trace.json --out report.md
python -m clew analyze trace.json --json report.json --no-snippets
```

리포트에는 낭비 노드 경로·반복 횟수·코사인·추정 낭비 토큰/비용이 포함됩니다.
`token_count`를 캡처하지 않은 경우 "unknown"으로 표기됩니다.

---

## 디렉터리

```
src/clew/
  model.py               정규 스팬 트리 (pydantic v2)
  ingest/langgraph.py    OpenInference/OTel → 정규 Trace (공식 진입점: ingest_otel_spans)
  detect/
    structural.py        반복 노드·핑퐁 후보 탐지 (입력 게이트 포함)
    semantic.py          코사인 유사도 φ 게이트
    cascade.py           구조→의미 2단 캐스케이드 탐지기
  report/
    markdown.py          Markdown 낭비 리포트 생성
    json_report.py       JSON 낭비 리포트 생성

eval/
  generators/            합성 라벨셋 빌더 (4 패턴 × paired design)
  traces/                생성된 트레이스 (gitignored, seed로 재생성)
  labels.jsonl           라벨 (탐지 코드 접근 금지 — 누수 가드 강제)
  set_manifest.json      seed/카운트/페어 (sha256은 CRITERIA에 박힘)
  evaluate.py            평가 진입점

field_test/
  real_app.py            5종 실제 LangGraph 앱 팩토리 (Haiku 기반)
  run_real_probe.py      E1-E3 실측 프로브 실행 스크립트
  REAL_PROBE_LOG.md      실측 결과 전문 + 정정 기록 + E3 발견

validation/
  CRITERIA_FROZEN.md     성공/중단 기준 — 라벨 분석 전 동결
  EVAL_RUNS.md           평가 실행 기록

tests/                   158+ 게이트 테스트
```

---

## 검증 결과

### 합성 평가 (2단계 GO, 2026-06-09)

동결 파라미터: φ=0.514345, N=2, `paraphrase-multilingual-MiniLM-L12-v2`

| 지표 | 값 |
|------|-----|
| F1 | **0.8571** |
| FPR | **0.0000** |
| TP / FP / TN / FN | 30 / 0 / 40 / 10 |
| 평가 실행 횟수 | 1회 (결과 보기 전 기준 동결) |

v1 탐지 스코프:

| 패턴 | TPR | 상태 |
|------|-----|------|
| repeat_node | 1.0 | ✅ 탐지 |
| pingpong_aba | 1.0 | ✅ 탐지 |
| requery_known | 1.0 | ✅ 탐지 |
| regen_handoff | 0.0 | 🔲 v1 비범위 (구조 신호 없음) |

### 실측 프로브 (E1-E3, 2026-06-16)

실제 Claude Haiku 트레이스 5종, 토픽 'quantum computing basics'.

| 시나리오 | 기대 | 실제 | 결과 |
|----------|------|------|------|
| clean (FP=0 기준) | 미탐지 | 미탐지 | **PASS** |
| repeat_node | 탐지 | 탐지 | **PASS** |
| requery_known | 탐지 | 탐지 | **PASS** |
| requery_clean (음성 대조) | 미탐지 | 미탐지 | **PASS** |
| pingpong | 탐지 | 탐지 | **PASS** |

git tag `real-probe-v1`.

### E3 발견 — 의미 레이어 한계 (정직 기록)

비낭비 스팬 쌍의 코사인 유사도가 전 시나리오에서 φ(0.514) 이상 (above-φ 100%, min 0.59~0.71).
합성 데이터 기반 연구에서 예측한 '0.48~0.57 군집'은 실측에서 재현되지 않음.
같은 토픽 출력의 어휘 공유가 원인으로 추정됨.

**해석:** FP=0은 구조 레이어(반복 후보 미생성)의 결과이며, 의미 레이어(φ 게이트)의 분리력에 의한 것이 아님. φ-transfer 문제가 예상보다 강함.

**한계:** n=1 토픽·5트레이스 관찰. 다른 토픽/도메인에서 달라질 수 있음.

**다음 단계:** 의미 레이어 재설계는 3~5건 추가 실제 트레이스(다른 토픽/도메인) 확보 후 별도 사전등록 실험에서 진행. φ 사후 조정은 하지 않는다.

---

## 검증 규율

`SPEC.md §4`의 6개 규율과 `CLAUDE.md §4`가 우선한다. 핵심:

- 결과를 본 뒤 `CRITERIA_FROZEN.md`를 수정하지 않는다.
- `src/clew/`는 `eval/labels*`를 import/read하지 않는다 — 누수 가드가 강제.
- "F1 0.857"은 *우리가* 합성 데이터로 달성한 값. 외부 연구 결과와 혼동하지 말 것.
- φ=0.514345는 동결값. 실측 결과를 보고 조정하지 않는다.
