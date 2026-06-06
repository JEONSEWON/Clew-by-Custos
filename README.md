# Clew

> 멀티에이전트 트레이스에서 헛도는 cycle을 추적하는 *실타래*. 회사 **Custos**.

**현재 상태: 1단계 — 데이터 기반 + 검증 하니스.**
탐지 로직은 아직 들어있지 않다. 1단계는 "신호가 진짜 낭비를 잡는지 정직하게 확인할
판"을 까는 것까지다 — 정규 스팬 모델, LangGraph 어댑터, paired 검증 라벨셋, 라벨 보기
전에 동결된 성공/중단 기준, 그리고 누수 가드.

자세한 맥락은 `CLAUDE.md` · `SPEC.md` · `validation/CRITERIA_FROZEN.md` 참조.

## 실행 환경

Windows / macOS / Linux 동일. Python 3.11+ 필요. `uv`가 있으면 자동으로 사용,
없으면 `pip`로 폴백.

```
python tasks.py install        # 의존성 설치
python tasks.py test           # 모든 테스트
python tasks.py generate-set   # 검증 라벨셋 생성 (seed=42, 4 패턴 × 10쌍)
python tasks.py check-leak     # 누수 가드만
python tasks.py dod            # 1단계 DoD 자동 점검
python tasks.py all            # install → generate-set → test → check-leak
```

`uv`가 설치된 경우 직접 호출도 가능:
```
uv sync --extra adapter --extra dev
uv run pytest -v
uv run python -m eval.generators.build_set --seed 42 --pairs-per-pattern 10 --out-dir eval/
```

## 디렉터리

```
src/clew/
  model.py             정규 스팬 트리 (pydantic v2)
  ingest/langgraph.py  OpenInference/OTel → 정규 Trace
  detect/              ← 1단계에서 비어있어야 함 (탐지는 2단계)
  report/              ← 1단계에서 비어있어야 함

eval/
  generators/          합성 라벨셋 빌더 (4 패턴 × paired design)
  traces/              생성된 트레이스 (gitignored, seed로 재생성)
  labels.jsonl         라벨 (탐지 코드 접근 금지)
  set_manifest.json    seed/카운트/페어 (sha256은 CRITERIA에 박힘)
  evaluate.py          2단계 평가 진입점 (현재 스텁)

validation/
  CRITERIA_FROZEN.md   성공/중단 기준 — 라벨 분석 전 동결

tests/                 모든 게이트 테스트
```

## 1단계 규율

`SPEC.md §4`의 6개 규율과 `CLAUDE.md §4`가 우선한다. 핵심:

- 결과를 본 뒤 `CRITERIA_FROZEN.md`를 수정하지 않는다.
- `src/clew/`는 `eval/labels*`를 import/read하지 않는다 — 누수 가드가 강제.
- "낭비를 잡는다"라는 표현은 2단계 GO 통과 후에만 README/공개 글에 쓴다.
- `eval/generators/patterns/`의 positive/clean 트윈은 *동일 구조 토폴로지*를 갖는다
  (테스트 강제) — 구조 단독 탐지기가 GO를 띄우는 자기기만 차단.
