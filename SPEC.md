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

## 10. 현재 단계 상세 — 3단계: 리포트 & CLI (트레이스→리포트 턴어라운드)

**목표:** 외부에서 받은 트레이스 파일을 리포트로 돌려주는 경로 완성.
아웃리치 약속("트레이스 주면 낭비 리포트로 돌려준다" + "로컬 실행 옵션")의
코드 측 이행. 동결 탐지기(src/clew/detect)·eval·기존 tests 불변.
φ=0.514345·N=2·임베딩 모델 불변 — 리포트는 동결 파라미터를 기본값으로 쓰고
리포트 머리에 그 값을 명시 인쇄한다.

### 범위
1. **파일 인제스트:** 정규 Trace JSON 로더(`Trace` pydantic 직렬화 왕복:
   save_trace/load_trace). + **캡처 헬퍼:** OpenInference 계측 LangGraph 앱에서
   InMemorySpanExporter → ingest_otel_spans → trace.json 저장하는 최소 스니펫/
   유틸(`clew.capture`). 외부 포맷(LangSmith/Langfuse export) 어댑터는 범위 밖
   — 요청자가 생기면 그때 같이 만든다.
2. **report/:** cascade 결과 → (a) 사람용 markdown (b) 기계용 JSON.
   내용: 낭비 스팬 위치(노드 경로), 반복 횟수, 코사인, 추정 낭비 토큰·비용
   (token_count 없으면 "unknown"으로 정직 표기), 한 줄 총평.
   **프라이버시:** output_text 스니펫은 기본 80자 절단 + `--no-snippets`
   옵션(스니펫 완전 제외) — 리포트가 되돌아올 때 민감 데이터 유출 최소화.
3. **CLI:** `python -m clew analyze <trace.json> [--out report.md] [--json out.json]
   [--no-snippets]`. 종료코드: 낭비 탐지 0, 미탐지 0 (분석 실패만 비0).
4. **패키징 최소:** README quickstart — 설치 → 캡처 → 분석 3단계.

### 사전 등록 합격 기준 (결과 보기 전 동결)
- D1 낭비 픽스처(R2형) → CLI 리포트에 낭비 스팬 식별 + 토큰/비용(또는 unknown) 포함
- D2 깨끗 픽스처 → "낭비 미탐지" 리포트 정상 출력
- D3 직렬화 왕복: save_trace→load_trace 후 분석 결과 동일
- D4 기존 테스트 green + 누수 가드 green, detect/ diff 0 (단 stage 경계 가드 2건(test_no_label_leakage.py의 test_dod_report_directory_empty, test_dod.py의 test_dod_detect_modules_present_report_absent)은 §10 진입으로 경계 갱신 — 검증 약화 아님)
- D5 README quickstart의 명령이 실제로 실행됨

**금지:** φ/N/모델 변경(CLI에 임계 오버라이드 옵션 넣지 말 것 — 실험은
field_test/에서만), detect/ 수정, 기준 사후 변경.

## 11. 현재 단계 상세 — 실측 프로브 1차 (self-generated real traces)

**목적:** 실제 LLM(Haiku) 멀티에이전트 트레이스에서 (1) 리포트 파이프라인이
실데이터로 작동하는지 확인하고, (2) φ=0.514345가 실측 출력 분포에서 어떻게
행동하는지 첫 데이터를 얻는다. 이것은 수요 검증이 아니라 채널 자료 + φ-transfer
사전 측정이다. detect/·φ/N/모델 전부 불변.

### 생성물 (field_test/ 샌드박스에만)
- real_app.py: ChatAnthropic(Haiku) 3노드 LangGraph (researcher→summarizer→critic),
  OpenInference 계측.
- 트레이스 4종: (a) clean, (b) repeat_node 낭비 심음, (c) requery_known 낭비 심음,
  (d) pingpong 낭비 심음. 각각 ingest_otel_spans로 변환해 field_test/real_*.json 저장.

### 결과 보기 전 기대 기록 (pre-registration)
- E1: clean 트레이스 → 낭비 미탐지(FP=0) 기대. 만약 FIRE면 = 실측 FP 발견(중요 신호).
- E2: 낭비 심은 3종 → 해당 패턴 탐지 기대. 미탐지면 = 실측 recall 갭.
- E3: 모든 비낭비 쌍의 코사인을 별도 출력 → 분포가 0.48~0.57 대역에 뭉쳐 φ에
  걸리는지(finding3 재현 여부) 관찰만. 재현되든 아니든 φ 손대지 않는다.

### 산출 기록
- field_test/REAL_PROBE_LOG.md: 각 트레이스의 탐지 결과 + 비낭비 쌍 코사인 분포
  (min/median/max, φ 초과 개수) + E1~E3 대조. 판정 근거를 사람이 읽을 수 있게.

**금지:** φ/N/모델 변경, detect/ 수정, 결과 보고 기대 변경. φ가 실측에 안 맞으면
그것은 발견으로 기록하며, 재보정은 별도 사전등록 실험(3~5건 실분포 확보 후)에서만.

## 12. 현재 단계 상세 — 입력 일반화 (프레임워크 무관 진입점)

**목적:** 인제스트 입구를 'LangGraph 앱 객체'에서 'OTel/OpenInference 스팬을
내보낸 JSON 파일'로 일반화한다. 분석 결과 어댑터 코어(otel_spans_to_trace,
preprocess)는 이미 프레임워크 무관이므로, 빠진 것은 'OTel-export JSON 파일을
읽는 진입점'뿐이다. 이 진입점 하나로 OpenInference 계측을 쓰는 모든 프레임워크
(LangGraph·CrewAI·AutoGen·LlamaIndex·PydanticAI·Smolagents·Google ADK +
OpenAI/Anthropic 클라이언트 계측)가 들어온다. 동결 탐지기(detect/)·eval·
φ/N/모델 전부 불변.

### 범위
1. ingest_from_otel_json(path): OTel/OpenInference 스팬 JSON(스팬 배열 또는
   OTLP-JSON) → 내부 ReadableSpan-호환 표현 → otel_spans_to_trace → preprocess.
   기존 otel_spans_to_trace/ingest_otel_spans는 불변(스팬 리스트 입력 유지).
2. CLI 연결: `python -m clew analyze <file>` 가 (a) 직렬화된 Trace JSON,
   (b) OTel-export 스팬 JSON 둘 다 받도록. 형식 자동 감지 또는 --format 플래그.
3. 중립화: source_tag 기본값을 "otel_adapter"로, langgraph.py 모듈 독스트링에서
   "LangGraph 전용" 표현 제거("LangGraph는 지원 프레임워크의 한 예"로). 단
   기존 함수 시그니처·동작은 불변(하위 호환).
4. capture.py의 LangGraph 실행부는 'capture_langgraph'로 명확히 표기/격리.
   범용 경로(JSON 파일)는 capture를 거치지 않음을 문서화.
5. examples/ 에 예제 OTel-export JSON 1개 + README에 "프레임워크별 트레이스
   내보내기" 섹션(CrewAI/AutoGen/LlamaIndex은 OpenInference 계측 → file export).

### 결과 보기 전 합격 기준 (사전등록)
- G1 예제 OTel-export JSON → ingest_from_otel_json → analyze가 리포트 생성
- G2 기존 직렬화 Trace JSON 입력도 여전히 analyze로 작동(하위 호환)
- G3 기존 158 테스트 green + 누수 가드 green, detect/ diff 0
- G4 신규 진입점 회귀 테스트: OTel-JSON 입력 → 기존 ReadableSpan 입력과
     동일한 Trace 산출(동치성)
- G5 README "프레임워크별 내보내기" 섹션 + 예제 파일이 실제로 실행됨

**금지:** φ/N/모델 변경, detect/ 수정, otel_spans_to_trace 기존 동작 변경,
비표준 프레임워크(n8n/Dify) 변환 추가(수요 확인 후 별도 단계).

## 14. 현재 단계 상세 — Format C (OpenInference flat export) 입력 지원

**[정정 사유]** §14 최초 가정(OTLP proto-JSON resourceSpans/Base64)은 구간1
실제 TRAIL 덤프에서 반증됨. 실제 형식은 flat hex + dotted-key라 범위를 실제
형식에 맞춰 정정함. 진짜 OTLP proto-JSON(resourceSpans)은 실제 파일을 확보한
적이 없어 이번 범위에서 제외(추후 실제 파일 확보 시 별도 단계).

**목적:** Phoenix/OpenInference exporter가 내보내는 Format C 형식(flat 스팬
배열, hex string ID, dotted-key flat dict attributes)을 입력으로 받는다.
TRAIL 공개 데이터셋이 이 형식이며, stage12에서 '미지원, 명확히 거절'로 분류된
경로를 정식 지원한다. 동결 탐지기(detect/)·eval·φ/N/모델 전부 불변.
otel_spans_to_trace 기존 동작 불변.

**핵심 규율:** 실제 TRAIL 덤프 확인된 구조에만 맞춘다. 확인되지 않은 구조는
가정하지 않는다.

**Format C 실제 구조 (구간1 덤프 기준):**
- 최상위: flat 스팬 배열 (resourceSpans 중첩 없음)
- span_id / trace_id / parent_span_id: hex string, flat 위치
- attributes: dotted-key flat dict (`{"openinference.span.kind": "AGENT", "output.value": "..."}`)
- timestamp 단위: 실제 덤프에서 확인된 형식에 따름

### 범위
1. ingest_from_openinference_json(path): Format C → Trace.
   - flat 스팬 배열 순회 (resourceSpans 중첩 없음)
   - hex string span_id/trace_id/parent_span_id → 우리 ID 형식
   - dotted-key flat dict attributes에서 openinference.span.kind,
     output.value, input.value, llm.token_count.total 추출
   - 내부적으로 ingest_otel_spans(shims) 경유해 preprocess 1회 보장
2. _load_trace_auto 확장: Format A(OTel SDK flat 배열, context 중첩) /
   Format C(OpenInference flat 배열, hex 최상위) / 직렬화 Trace JSON
   세 형식 자동 감지.
   - Format A: 첫 스팬에 `"context"` 키 존재
   - Format C: 첫 스팬에 `"context"` 없고 `"span_id"` 최상위 존재
   - 직렬화 Trace: 최상위 `"trace_id"` + `"spans"` 키
   - `"resourceSpans"` / `"resource_spans"` 키 → 아직 미지원, 명확한 에러 유지
3. 기존 Format A / 직렬화 Trace 경로 불변(하위 호환).
4. 진짜 OTLP proto-JSON(resourceSpans 중첩, Base64 ID): 실제 파일 미확보.
   해당 키 감지 시 "OTLP proto-JSON은 미지원(실제 파일 확보 후 별도 단계)"
   에러 메시지 유지.

### 결과 보기 전 합격 기준 (사전등록)
- H1 TRAIL 실제 트레이스(작은 것) → ingest_from_openinference_json → analyze 리포트 생성
- H2 기존 Format A 입력 여전히 작동(하위 호환)
- H3 기존 직렬화 Trace 입력 여전히 작동
- H4 기존 171 테스트 green + 누수 가드 green, detect/ diff 0
- H5 Format C 동치성: 같은 논리적 트레이스를 Format A와 Format C로 각각
     넣었을 때 동일 Trace 산출(가능한 범위에서 — span 수·kind·output_text)
- H6 깨진 Format C(필수 필드 누락) → 명확한 에러 메시지

**금지:** φ/N/모델 변경, detect/ 수정, TRAIL 형식을 상상으로 가정(실제 덤프
확인 필수), 낭비 라벨 없는 TRAIL로 정확도/F1 산출, resourceSpans 미확인
구조 구현.

## 15. 현재 단계 상세 — E3 오탐 진단 (실제 트레이스 다건 수집)

**목적:** 의미 레이어 오탐(E3)의 실제 패턴을 데이터로 정의한다. TRAIL 여러
트레이스(GAIA + SWE-Bench)를 현재 동결 도구 그대로 돌려, FIRE 각 건을 사람이
원문으로 판정(진짜 낭비/오탐/애매)하고 오탐의 공통 원인을 수집한다. 이것은
'진단'이며 개선이 아니다. detect/·φ/N/모델 전부 불변. 아무것도 고치지 않는다.

**핵심 규율:**
- 판정은 사람이 output_text 원문을 읽고 한다. 도구가 자동 판정하지 않는다.
- 고칠 방법(상대비교/베이스라인차감/역할게이트 등)을 미리 정해놓고 데이터를
  해석하지 않는다. 데이터가 원인을 말하게 한다.
- GAIA와 SWE-Bench 둘 다 포함(한 종류 편향 방지).
- 정확도/F1 산출 금지(외부 낭비 라벨 없음). '몇 건 FIRE, 사람 판정 분류'만.

### 범위
1. TRAIL에서 트레이스 N개(제안: GAIA 5 + SWE-Bench 5 = 10개, 크기 다양하게) 수집.
2. 각 트레이스를 python -m clew analyze로 돌려 FIRE 수집.
3. field_test/E3_DIAGNOSIS.md 자동+수동 기록:
   - 트레이스별: 스팬 수, FIRE 건수, 각 FIRE의 pattern/cosine/origin·candidate
     의 output_text 원문(500자)+input_text+node/kind
   - 사람 판정란(비워둠 — 내가 채운다): 각 FIRE가 진짜낭비/오탐/애매 중 무엇
   - 비낭비 쌍 코사인 분포(트레이스별 min/median/max, above-φ 비율)
4. 집계: 총 FIRE 수, (사람 판정 후) 오탐 비율, 오탐들의 공통 특성 관찰란.

### 결과 보기 전 기록 (사전등록)
- 이 단계는 '진단'이므로 합격/불합격 기준이 없다. 대신 산출 목표를 못 박는다:
  "FIRE 최소 5건 이상 수집 + 각 건 사람 판정 + 오탐의 공통 원인 가설 1개 이상
  데이터에서 도출." 5건 미만이면 트레이스를 더 수집한다.

**금지:** φ/N/모델/detect 수정, 도구 자동 판정, 고칠 방법 선정(다음 단계),
정확도 산출, 한 종류(GAIA만/SWE만) 편향.

## 16. 현재 단계 상세 — E3 개선: 부모 AGENT 게이트 (구조 레이어)

**목적:** E3 오탐(stage15에서 7/7 확증)의 진원지는 구조 레이어가 '서로 다른
AGENT의 같은 이름 스팬(예: CodeAgent의 Step 1 vs ToolCallingAgent의 Step 1)'을
repeat_node 후보로 올린 것이다. 해법: "같은 부모 AGENT 아래 있는 스팬끼리만
repeat_node 후보"로 제한하는 구조적 게이트. 이는 output_text 문자열이나
프레임워크별 이름에 의존하지 않는 OpenInference 일반 구조 신호다.

**이번 단계는 처음으로 detect/를 수정한다.** 따라서 안전장치를 최대로 건다.

### 사전등록 합격 기준 (결과 보기 전)
- I1 [오탐 제거] stage15의 TRAIL 7건 FIRE가 게이트 적용 후 0건이 된다.
- I2 [합성 회귀 무손상] 기존 합성 평가(F1 0.857, FPR 0)가 게이트 적용 후에도
     유지된다(F1 하락 없음). 이게 깨지면 게이트가 정당한 탐지를 막는 것이다.
- I3 [진짜 낭비 미손실] 게이트가 '같은 AGENT 내 진짜 repeat'는 여전히 잡는지
     확인하는 테스트. 같은 부모 AGENT 아래 실제 중복 스팬을 만든 픽스처로
     여전히 FIRE하는지 단언.
- I4 [φ 불변] φ/N/모델 전부 불변. 이 개선은 구조 레이어 게이트지 임계값
     조정이 아니다. φ를 건드리면 실패.
- I5 [기존 테스트 무손상] 185 테스트 여전히 green(게이트로 인해 깨지는 기존
     테스트가 있으면 그 테스트가 뭘 검증하던 건지 먼저 보고).

### 게이트 정의 (일반적, 문자열 비의존)
- 두 스팬이 repeat_node 후보가 되려면 '가장 가까운 조상 AGENT span'이 동일해야
  한다. 부모 AGENT가 다르면 후보에서 제외.
- AGENT 조상이 없는 스팬(단일 에이전트/평면 트레이스)의 처리 규칙도 명시
  (기존 동작 보존 — 게이트가 단일 에이전트 케이스를 망가뜨리면 안 됨).

**금지:** φ/N/모델 변경, output_text 문자열 기반 필터, 부모 '이름' 문자열 매칭
(span_id/구조로만), 7건에 맞춘 하드코딩, 합성 F1 하락 감수.

## 17. 현재 단계 상세 — 실측 낭비 탐색 (TRAIL 확장 + 진위 판정)

**목적:** "우리 도구가 실제 트레이스에서 진짜 낭비를 잡는가"를 확인한다. 지금까지
실측 진짜 낭비 발견 0건(합성·프로브는 심은 것, TRAIL 7건은 전부 오탐→stage16에서
게이트로 제거). stage16 게이트 적용 상태로 TRAIL을 더 많이 돌려, 남는 FIRE가
있으면 사람이 진짜 낭비/오탐/애매를 판정한다. detect/·φ 전부 read-only(이미
stage16 반영됨). 아무것도 고치지 않는다 — 탐색·판정만.

**핵심 규율:**
- 판정은 사람이 output_text 원문을 읽고 한다. 도구 자동 판정 금지.
- "낭비를 못 찾음"도 정당한 결론이다(=벤치마크엔 낭비 드묾 → 경로2 필요).
- FIRE가 나오면 stage16 게이트를 통과한 것이므로 '같은 에이전트 내 반복'일
  가능성이 높다. 그래도 진짜 낭비인지는 원문으로 확인.
- 정확도/F1 산출 금지(외부 낭비 라벨 없음).

### 범위
1. TRAIL을 30~50개로 확장(기존 10개 + 추가). GAIA/SWE 섞고 크기 다양.
   진짜 낭비는 큰 트레이스(스팬 많음)에 있을 가능성 → 중대형 위주 포함.
2. 각 트레이스를 stage16 게이트 적용된 현재 도구로 분석. FIRE 수집.
3. field_test/WASTE_HUNT.md 기록:
   - 트레이스별: 스팬 수, FIRE 건수, 처리 시간
   - 각 FIRE: pattern, cosine, origin/candidate의 output_text(500자)+input_text
     +node/kind+부모 AGENT(게이트 통과했으니 같은 AGENT일 것)
   - 사람 판정란(비워둠): 진짜낭비/오탐/애매
   - 집계: 총 FIRE, (판정 후) 진짜 낭비 건수

### 산출 목표 (사전등록)
- 목표는 '진짜 낭비 1건 이상 발견 또는 명확한 부재 확인'.
- FIRE가 나오고 사람이 '진짜 낭비'로 판정하면 → 실측 첫 낭비 증거(기록).
- FIRE 0건이거나 전부 오탐이면 → "TRAIL 벤치마크엔 우리가 잡는 낭비 패턴이
  드물다"를 결론으로 기록, 경로2(실제 프로덕션 워크로드) 근거가 됨.

**금지:** φ/detect 수정, 도구 자동 판정, 없는 낭비를 억지로 낭비라 판정,
FIRE 안 나온다고 무한정 트레이스 추가(50개 상한. 그래도 없으면 결론).
