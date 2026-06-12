# SPEC.md — Clew MVP (S0) 빌드 스펙

> Claude Code가 이 스펙대로 단계적으로 빌드한다. 목표는 *완제품*이 아니라 **"교정 신호가
> 실제 낭비를 잡나"를 싸게 검증하면서 개발자가 써볼 수 있는 가장 작은 실물**이다.
> (제품 **Clew** = 미로를 추적하는 실. 회사 **Custos**.)

## 0. MVP의 목적 (이것만 달성하면 성공)

1. 실제 멀티에이전트 트레이스에서 **헛도는 cycle/중복 핸드오프를 탐지**하고 추정 낭비
   비용을 리포트한다.
2. 그 탐지가 **진짜 낭비를 잡는지** 정직하게 검증한다(§5).
3. 개발자가 *써볼 수 있는* 형태로 내놓아 반응을 본다.

## 1. 범위

**만든다 ✅**
- 트레이스 1개 형식 인제스트 → 파싱 → cycle 탐지 → 리포트(CLI + JSON/markdown).
- 추정 낭비 토큰/비용 계산.
- 소규모 검증용 라벨 세트 + 평가 스크립트.

**안 만든다 ❌ (아직)**
- 실시간 차단/개입, 웹 대시보드, 계정/과금, 멀티 포맷 동시 지원, DB.

## 2. 입력 (한 형식부터)

- 1순위 권장: **OpenTelemetry / OpenInference spans**(프레임워크 무관 = 우리 thesis와 일치).
  또는 사용자가 실제로 쓰는 형식(LangGraph/LangSmith export, Claude Code 세션 로그) 중 하나.
- 필요한 필드: span id, parent id, name(에이전트/도구), input, output, start/end, token usage(가능 시).
- 없으면: 어댑터 한 개만 먼저(예: LangSmith JSON → 내부 표준 span 트리).

## 3. 탐지 로직 (캐스케이드 — 핵심)

```
trace → span 트리(parent→children) 구성
  │
  ├─ [구조] 반복 후보 탐지
  │     - span "시그니처" 시퀀스(에이전트/도구 이름)에서 반복 부분열 탐지
  │     - 같은 노드가 임계 이상 반복 / 같은 (sender→recipient) 반복 → 후보 cycle 표시
  │     - (구조 단독은 오탐 많음 — 후보만 추리는 게이트 역할)
  │
  └─ [의미] 지역적 중복 확인  ← 후보에 대해서만
        - 반복/형제 span의 *출력* 임베딩 코사인 유사도
        - cos > φ  → "이미 가진 정보 재생성" = 중복(나쁜 cycle)
        - cos 낮음 → "반복하지만 새 내용" = 진전(정상) → 제외
        - 수치/시계열 출력은 코사인 오도 가능 → 값 기반 diff 병행
  │
  └─ 낭비 판정 = 구조 반복 AND 의미 중복
        - 해당 span들의 token usage 합 → 추정 낭비 토큰 × 단가 → $ 낭비
```

설계 원칙(★): **전역 추세(EMA·per-trace max) 쓰지 말 것** — v1의 길이 편향 원인.
국소 쌍 비교만(길이 불변). 파라미터(φ, 반복 임계 등)는 §5 검증 전에 동결.

## 4. 출력

- trace별 리포트: 탐지된 헛도는 cycle 목록 = {위치(span 경로), 반복 횟수, 출력 유사도,
  추정 낭비 토큰/비용}.
- 형식: CLI 요약 + JSON(기계용) + markdown(사람용). 한 줄 총평("이 run에서 ~N 토큰,
  ~$X 낭비 추정").

## 5. 검증 계획 (★ 출시·자랑 *전에* — 누수 없이)

신호가 미검증이므로, "작동한다"를 *증명*한 뒤에만 내세운다.

- **라벨 세트 구성:** 트레이스 수십 개 — 일부는 *의도적으로* 낭비 루프 심기(에이전트가
  같은 일 반복하게), 일부는 깨끗. 각 trace에 "낭비 cycle 있나/어디" 수기 라벨.
- **사전 동결:** 탐지 파라미터(φ, 임계)와 "성공 = ?"를 *라벨 보기 전에* 적는다.
  - 예) 성공 = 심어둔 낭비 루프를 ≥X% 탐지 + 깨끗한 trace 오탐 ≤Y%.
- **누수 금지:** 탐지 코드는 라벨 파일을 읽지 않는다. 라벨은 평가 스크립트에서만 비교.
- 통과해야 README·공개 글에서 "낭비를 잡는다"고 말할 수 있다.

**"원한다"의 기준(출시 후):** 예) 설치 N · "진짜 뭔가 잡아줬다" 피드백 M · 1주 후에도
사용. 이걸 미리 적어 두고, 미달이면 wedge 재검토.

## 6. 제안 파일 구조

```
clew/
  CLAUDE.md            # 상시 컨텍스트(이미 있음)
  SPEC.md              # 이 파일
  README.md            # 짧은 소개(검증 통과 후 "잡는다" 문구 추가)
  src/clew/
    ingest/            # 트레이스 → 표준 span 트리 어댑터
    detect/
      structural.py    # 반복 후보 탐지
      semantic.py      # 지역 중복 확인(임베딩)
      cascade.py       # 둘을 캐스케이드로 결합 + 낭비/비용 산출
    report/            # CLI/JSON/markdown 출력
  eval/
    traces/            # 라벨용 트레이스(심은 것 + 깨끗한 것)
    labels.jsonl       # 수기 라벨(탐지 코드는 접근 금지)
    evaluate.py        # 탐지 vs 라벨 비교
  docs/                # 전략·시장·신호설계 문서들
```

## 7. 빌드 단계 (Claude Code가 순서대로)

1. **데이터 기반 + 검증 하니스** — 정규 스팬 모델(OpenInference/OTel) + LangGraph 어댑터 1개 + 검증 라벨셋 생성 + 성공기준 동결·누수 가드. 상세는 §8. ❗탐지 로직 없음.
2. **structural.py** — 반복 후보 탐지. 샘플에서 후보가 합리적으로 잡히나 눈으로 확인.
3. **semantic.py** — 후보 span 출력 임베딩 + 코사인. (임베딩 모델 1개 고정.)
4. **cascade.py** — 결합 + 낭비 토큰/비용 산출.
5. **report** — CLI/JSON/markdown.
6. **eval** — 라벨 세트 만들고(심은 낭비 + 깨끗), 파라미터·성공기준 동결 후 evaluate.py로
   1회 검증. **여기서 신호가 진짜 잡는지 결정.**
7. 통과 시 README 정리 → 개발자에게 배포(오픈소스 가능) → 사용 반응 수집.

> 각 단계 끝에 "무엇을 검증했나" 한 줄 남기기. 5·6단계의 검증 규율(사전 동결·누수 금지)을
> 절대 건너뛰지 말 것 — 이게 검증 실험을 반복하지 않는 핵심이다.

## 8. 현재 단계 상세 명세 (Active Stage Detail) — 2단계

### 2단계 — 탐지 캐스케이드 (Detection Cascade)

**목표:** 1단계 하니스 위에서 구조→의미 캐스케이드 탐지기를 만들고, 동결된 기준으로
평가 set에 **단 한 번** 측정해 GO/KILL을 정직하게 가린다.

**전제:** 1단계 동결(`stage1-freeze`). `detect/`가 비어있던 상태를 이제 채운다 —
누수 가드는 import *방향*만 강제하므로 `src/clew`는 여전히 `eval/labels`를 못 본다.

### v1 탐지 스코프
v1 캐스케이드는 강한 구조 신호로 후보를 좁힐 수 있는 3패턴을 대상으로 한다:
- repeat_node (같은 agent_or_node_id 반복)
- pingpong_aba (A→B→A→B 반복)
- requery_known (같은 입력 키 재조회 — tool 입력 게이트)
regen_handoff(cross-node 재생성)는 v1 범위 밖. 사유: 핸드오프는 정상 파이프라인
(A 1단계 → B 2단계)과 구조적으로 구별되지 않아 강한 구조 신호가 없다. 후보를
'인접한 서로 다른 llm 노드'로 잡으면 모든 핸드오프가 후보가 되어 탐지가
semantic-dominant가 되고, 정당한 refinement 핸드오프(B가 A를 다듬어 발전)가
φ를 넘겨 거짓 양성이 될 위험이 크다. 향후 증분에서만: 핸드오프 후보 경로 +
refinement non-waste 트윈으로 FP 표면을 검증한 뒤 도입.

#### 2.1 후보 생성 — span_kind 인지 규칙 (label-free)
탐지기는 트레이스의 패턴 라벨을 모른다. 후보 생성은 `span_kind` 로만 결정한다.

- 조회/도구류 span(`retrieval`·`tool` kind): 같은 `agent_or_node_id` 가 N회+ 반복돼도,
  재등장의 `input_text` 가 원본(첫 등장)과 정규화 동일(normalized-equal)일 때만 후보 쌍.
  입력이 다르면 후보 아님 — 서로 다른 정당한 조회이므로 구조에서 제외한다.
  (근거: 재조회 낭비의 정의적 신호는 '같은 입력'이지 '같은 노드'가 아니다.
  노드 동일성만으로는 재조회와 서로 다른 조회를 구분 못 해, 의미 레이어에
  템플릿-표면 거짓 양성을 떠넘긴다. 1차 calibrate FAIL(dev_fpr 0.20)이 그 증거.)
- 그 외 kind(`agent`·`llm`·`chain`): 기존대로 노드 반복/토폴로지로 후보를 잡고,
  의미 레이어가 출력 중복을 확인한다. 입력 게이트 적용 안 함.
- `requery_known` clean 데이터셋은 '같은 스키마·다른 값'(예: 다른 `customer_id` 로
  같은 형식 응답) 하드 네거티브를 반드시 포함한다. 이들은 입력이 다르므로
  구조 후보 0개여야 한다(게이트 작동 증명). 전부 다른 도메인으로만 채우는 것
  금지 — eval 이 프로덕션보다 쉬워진다.

#### 2.2 semantic.py — 의미 중복 확인
- 입력: 2.1의 후보 쌍.
- **로컬 다국어 임베딩 모델 1개**(한국어 포함 → 다국어 필수, API 키 불요, 결정론).
  후보: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`(가볍고 패러프레이즈 특화) /
  `intfloat/multilingual-e5-small`. 최종 선택은 dev set 분리도로(평가 set 무관).
- 후보 쌍의 `output_text` 코사인 유사도 ≥ φ → 의미 중복 확정.
- 파라미터: φ 코사인 임계 (dev set에서 결정·동결).

#### 2.3 cascade.py — 결합 + 비용
- 낭비 판정 = **구조 후보 AND 의미 중복(코사인 ≥ φ).** (둘 중 하나만으론 불충분 — v1 교훈.)
- 낭비 스팬의 `token_count × cost_rate` = 추정 낭비 비용.
- trace 판정: 낭비 스팬 ≥1 → trace = wasteful.
- 출력: trace별 `{낭비 스팬, 중복도, 추정 낭비 토큰/비용}`.

#### 2.4 파라미터 동결 절차 (★ 순서 엄수)
1. 임베딩 모델 1개 선택(라벨·평가 set 무관 근거).
2. **dev set 생성**: `build_set --seed <42 아님, 예: 7>` — 평가 set과 구조 동일, 내용 다름.
3. dev set에서 패러프레이즈 쌍 vs 무관 쌍의 코사인 분포 관찰 → φ 결정, 반복 임계 N 결정.
4. φ·N·임베딩 모델을 `CRITERIA_FROZEN.md`의 "탐지 파라미터"(현재 TBD) 섹션에 박고 **git commit**.
5. 그 다음에야 평가 set(seed=42, `stage1-freeze` 동결)에 `evaluate` 실행.
6. ★ **평가 set은 파라미터 결정에 절대 쓰지 않는다.**

#### 2.5 evaluate.py — 평가 (1단계 스텁 → 채움)
- `labels.jsonl` + 평가 set 트레이스 로드 → cascade 실행 → trace-level F1, control(negative) FPR 산출.
- CRITERIA GO/KILL과 대조해 판정 출력.
- ★ **evaluate가 유일한 라벨 reader.** cascade/structural/semantic엔 라벨 절대 안 넘김.
- 회색지대(0.60≤F1<0.80 또는 0.10<FPR≤0.25)면 CRITERIA의 N=3 예산 안에서만 재조정 —
  단 **집계 지표(F1·FPR)만 관찰**, 개별 라벨·어느 트레이스가 틀렸는지는 비관찰(평가 set 과적합 차단).
  3회 소진 후에도 GO 미달이면 KILL.

#### 2단계 완료 정의 (DoD)
- [ ] structural.py + 단위 테스트(후보 탐지, 라벨 미참조)
- [ ] semantic.py + 단위 테스트(임베딩 결정론, 코사인)
- [ ] cascade.py + 단위 테스트(구조 AND 의미, 비용 산출)
- [ ] 임베딩 모델·φ·N을 dev set에서 결정 후 CRITERIA에 동결 커밋
- [ ] evaluate.py로 평가 set **단 1회** 측정 → F1/FPR → GO/KILL 판정 기록
- [ ] 누수 가드 여전히 green(detect 채워졌어도 src/clew→eval/labels 의존 0)

## 9. 현재 단계 상세 — 2.5단계: 인제스트 필드-하드닝

**목표:** 필드 테스트로 진단·확정된 3개 결함을 ingest/preprocessing 레이어에서 수정.
동결 탐지기(src/clew/detect)·eval·기존 tests는 불변. φ·N·임베딩 모델 불변
(φ-transfer는 실분포 재보정 사안 — 본 단계 범위 밖).

### 변환 3종 (적용 순서 고정)
1. **token-bearing 플래그 (collapse 전 계산):** 원본 span 트리에서
   `has_llm_or_tool_child` 를 계산해, llm/tool 자식이 없는 chain span
   (라우터/제어흐름)을 탐지 단위에서 제외. 근거: 토큰 0 span은 정의상
   토큰 낭비가 아니다. ※ collapse 후 계산 금지 — 접고 나면 작업 노드도
   tokenless로 보인다.
2. **collapse_to_logical_nodes 정식 승격:** llm 서브스팬을 부모 chain
   노드로 접되, 접기 *전*에 llm 토큰/비용을 부모에 합산(비용 스토리 보존).
   tool span은 절대 접지 않음(requery 입력 게이트 대상). tool이 llm의
   자식인 ReAct 구조면 tool을 노드로 re-parent. 그래프 루트 유지.
3. **내용 추출:** 어댑터가 output.value JSON에서 내용만 추출해 clean
   `output_text` 생성(JSON 스캐폴드의 코사인 부풀림 ~0.2 제거).
   비JSON이면 원문 유지.

### 사전 등록 합격 기준 (결과 보기 전 동결)
- R1 깨끗한 실제-계측 트레이스 → FP = 0
- R2 repeat_node 심은 트레이스 → TP fire 유지
- R3 라우터 적대 케이스(같은 값 반복 반환) → FP 소거
- R4 비중복 researcher 쌍 → 추출 후 cosine이 RAW 대비 하락
- 기존 테스트 149개 전부 green + 누수 가드 green  (§9 작성 당시 "146"은 오기 — 실제 베이스라인 149, 베이스라인 변경 아님)
- R1~R5는 영구 회귀 테스트로 남긴다(신규 테스트 파일, 기존 테스트 수정 금지).
- 공식 인제스트 경로: `ingest_otel_spans()` (= otel_spans_to_trace + preprocess_trace). `otel_spans_to_trace()`는 raw 변환 전용.

**금지:** φ/N/모델 변경, detect/ 수정, 기준 사후 변경, 예시에 맞춘 임계 조정.
