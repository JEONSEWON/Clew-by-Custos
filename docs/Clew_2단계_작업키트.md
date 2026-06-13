# Clew — 2단계 작업 키트

> 1단계 동결(tag `stage1-freeze`, commit 0fa25e0) 위에서 진행.
> 세 부분: (A) SPEC.md §8 2단계 교체본 · (B) CLI 명령 — §8 갱신 + CLAUDE.md 활성 단계 · (C) plan 프롬프트.
> ★ 2단계의 핵심 규율: **탐지 파라미터(φ·N·임베딩 모델)는 dev set에서 결정, 평가 set은 단 1회.**

---

## (A) SPEC.md — §8 전체 교체본 (1단계 → 2단계)

> `## 8. 현재 단계 상세 명세 ...` 절 전체를 아래로 교체. (1단계 상세는 git tag로 이미 박제됨.)

### 8. 현재 단계 상세 명세 (Active Stage Detail) — 2단계

#### 2단계 — 탐지 캐스케이드 (Detection Cascade)

**목표:** 1단계 하니스 위에서 구조→의미 캐스케이드 탐지기를 만들고, 동결된 기준으로
평가 set에 **단 한 번** 측정해 GO/KILL을 정직하게 가린다.

**전제:** 1단계 동결(`stage1-freeze`). `detect/`가 비어있던 상태를 이제 채운다 —
누수 가드는 import *방향*만 강제하므로 `src/clew`는 여전히 `eval/labels`를 못 본다.

##### 2.1 structural.py — 구조 후보 탐지
- 입력: 정규 `Trace`. **`start_time` 시간순으로 정렬된 노드 시퀀스**로 작업(트리 깊이 아님 — 1단계 트레이스가 평평한 fan-out 구조임).
- 후보 유형:
  - 반복 노드: 같은 `agent_or_node_id`가 N회+ 등장 → (원본=첫 등장, 후보=재등장) 쌍.
  - 핑퐁: 같은 노드쌍이 A→B→A→B 교대 → 2회차 A·B를 후보로.
  - requery는 "반복 tool 노드"의 특수형으로 자연 포착(같은 tool 재등장).
- 출력: 후보 쌍 리스트 `[(origin_span, candidate_span), ...]`. ★ **라벨 미참조.**
- 파라미터: 반복 임계 N (dev set에서 결정·동결).

##### 2.2 semantic.py — 의미 중복 확인
- 입력: 2.1의 후보 쌍.
- **로컬 다국어 임베딩 모델 1개**(한국어 포함 → 다국어 필수, API 키 불요, 결정론).
  후보: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(가볍고 패러프레이즈 특화) /
  `intfloat/multilingual-e5-small`. 최종 선택은 dev set 분리도로(평가 set 무관).
- 후보 쌍의 `output_text` 코사인 유사도 ≥ φ → 의미 중복 확정.
- 파라미터: φ 코사인 임계 (dev set에서 결정·동결).

##### 2.3 cascade.py — 결합 + 비용
- 낭비 판정 = **구조 후보 AND 의미 중복(코사인 ≥ φ).** (둘 중 하나만으론 불충분 — v1 교훈.)
- 낭비 스팬의 `token_count × cost_rate` = 추정 낭비 비용.
- trace 판정: 낭비 스팬 ≥1 → trace = wasteful.
- 출력: trace별 `{낭비 스팬, 중복도, 추정 낭비 토큰/비용}`.

##### 2.4 파라미터 동결 절차 (★ 순서 엄수)
1. 임베딩 모델 1개 선택(라벨·평가 set 무관 근거).
2. **dev set 생성**: `build_set --seed <42 아님, 예: 7>` — 평가 set과 구조 동일, 내용 다름.
3. dev set에서 패러프레이즈 쌍 vs 무관 쌍의 코사인 분포 관찰 → φ 결정, 반복 임계 N 결정.
4. φ·N·임베딩 모델을 `CRITERIA_FROZEN.md`의 "탐지 파라미터"(현재 TBD) 섹션에 박고 **git commit**.
5. 그 다음에야 평가 set(seed=42, `stage1-freeze` 동결)에 `evaluate` 실행.
6. ★ **평가 set은 파라미터 결정에 절대 쓰지 않는다.**

##### 2.5 evaluate.py — 평가 (1단계 스텁 → 채움)
- `labels.jsonl` + 평가 set 트레이스 로드 → cascade 실행 → trace-level F1, control(negative) FPR 산출.
- CRITERIA GO/KILL과 대조해 판정 출력.
- ★ **evaluate가 유일한 라벨 reader.** cascade/structural/semantic엔 라벨 절대 안 넘김.
- 회색지대(0.60≤F1<0.80 또는 0.10<FPR≤0.25)면 CRITERIA의 N=3 예산 안에서만 재조정 —
  단 **집계 지표(F1·FPR)만 관찰**, 개별 라벨·어느 트레이스가 틀렸는지는 비관찰(평가 set 과적합 차단).
  3회 소진 후에도 GO 미달이면 KILL.

##### 2단계 완료 정의 (DoD)
- [ ] structural.py + 단위 테스트(후보 탐지, 라벨 미참조)
- [ ] semantic.py + 단위 테스트(임베딩 결정론, 코사인)
- [ ] cascade.py + 단위 테스트(구조 AND 의미, 비용 산출)
- [ ] 임베딩 모델·φ·N을 dev set에서 결정 후 CRITERIA에 동결 커밋
- [ ] evaluate.py로 평가 set **단 1회** 측정 → F1/FPR → GO/KILL 판정 기록
- [ ] 누수 가드 여전히 green(detect 채워졌어도 src/clew→eval/labels 의존 0)

---

## (B) CLI 명령 — §8 교체 + CLAUDE.md 활성 단계 갱신

`clew/`에 이 키트 파일을 `docs/`에 넣고, `claude` 일반 모드로:

```
docs/Clew_2단계_작업키트.md 를 읽어. 그 안의 "(A) SPEC.md — §8 전체 교체본" 내용으로
SPEC.md의 "## 8. 현재 단계 상세 명세 ..." 절 전체를 교체해줘.
§1~§7과 문서의 나머지는 절대 건드리지 마.
그리고 CLAUDE.md의 "현재 활성 단계 = 1단계 (상세: SPEC.md §8)" 줄을
"현재 활성 단계 = 2단계 (상세: SPEC.md §8)"로 갱신해줘.
교체 후 §8과 CLAUDE.md의 변경된 부분(diff)만 보여줘.
```

---

## (C) plan 프롬프트 — 2단계 빌드 시작 (Plan Mode)

Shift+Tab으로 **Plan 모드** 진입 후:

```
CLAUDE.md와 SPEC.md(특히 §8 2단계, §4 규율)를 먼저 읽어. 1단계는 stage1-freeze로 동결됨.
지금부터 2단계(탐지 캐스케이드)를 구현한다.

구현하지 말고 계획만 세워서 보여줘:
1. structural.py — 시간순 노드 시퀀스에서 후보 쌍(반복 노드/핑퐁/재조회) 탐지 설계 + 테스트.
   ★ 라벨 미참조. 반복 임계 N은 파라미터로 노출(아직 값 미정).
2. semantic.py — 로컬 다국어 임베딩 모델 후보 비교(키 불요·결정론) + 코사인 + φ 임계.
   모델은 dev set 분리도로 고른다. 임베딩 캐시로 결정론·속도 확보.
3. cascade.py — 구조 AND 의미 → 낭비 판정 + token×cost_rate 비용 + trace-level 집계.
4. dev set 경로 — build_set로 seed≠42 dev set 생성, φ·N·모델을 dev에서 결정하는 절차.
5. CRITERIA_FROZEN.md "탐지 파라미터" 섹션(현재 TBD)을 dev 결정값으로 채워 동결 커밋하는 절차.
6. evaluate.py — labels + 평가 set 로드 → cascade → F1/FPR → GO/KILL 판정. evaluate가 유일 라벨 reader.
7. 파일·작업 순서, 각 산출물 테스트, 누수 가드가 여전히 green인지.

규율(절대):
- 평가 set(seed=42)은 파라미터 결정에 쓰지 않는다. φ·N·모델은 dev set에서만 정한다.
- 평가 set 측정은 단 1회. 회색지대면 집계 지표만 보고 N=3 예산 내 재조정(개별 라벨 비관찰).
- 탐지 코드(src/clew)는 eval/labels를 절대 import·read 하지 않는다.
- 파라미터는 평가 전에 CRITERIA에 동결 커밋.
- 성공 단언 말고 테스트·실행 결과로 증명.

계획만 제시하고 내 승인을 기다려. 승인 전엔 파일 생성·수정 금지.
```

---

### 진행 순서 요약
1. (B)로 §8을 2단계로 교체 + CLAUDE.md 갱신 → diff 확인.
2. (C)를 Plan 모드로 투입 → 계획 검토·승인.
3. 승인 후 구현: structural/semantic/cascade → dev set으로 φ·N·모델 결정 → CRITERIA 동결 커밋.
4. 평가 set 단 1회 evaluate → F1/FPR → GO/KILL.
5. 결과에 따라: GO면 제품화 트랙, KILL이면 신호 재설계(v1처럼 정직하게).
