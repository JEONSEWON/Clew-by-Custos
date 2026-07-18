# §23 — Toolathlon 어댑터 사전등록 (2026-07-18, 규칙 8)

**대상 데이터**: [hkust-nlp/Toolathlon-Trajectories](https://huggingface.co/datasets/hkust-nlp/Toolathlon-Trajectories) (HF, CC-BY-4.0, gated).

**왜 별도 어댑터인가**:
- 우리 개발 세션 20개(§22.11.8) 확정 낭비 0. 검증기의 참양성 검출력은 이 코퍼스로 증명 불가.
- Toolathlon 은 17 모델 × 3 런 × 실제 장기 도구사용 트레이스 (task 성공/실패 라벨 포함). arXiv:2602.19008 이 canonical path deviation 이 실패 원인이라고 명명 → 낭비가 실재할 가능성이 높음.
- 리콘(§23.5 근거) 결과 재호출 실재 확인: 108 트레이스 중 39 (36%) 에 (name, args) 재호출 있음, 총 177 candidate.

**리콘 산출물** (규칙 7 부칙, 같은 커밋에 동봉):
- `field_test/diagnostics/recon_toolathlon.py` — 스키마 리콘 (Q1–Q6)
- `field_test/diagnostics/recon_toolathlon_waste.py` — 낭비 실재 확인 (Q1–Q5)

---

## §23.1 — 확정 매핑 (recon 근거)

| Span 필드 | Toolathlon 소스 | 근거 |
|---|---|---|
| `trace_id` | `request_id` (uuid 문자열) | recon Q1 (`request_id`가 유니크) |
| `span_id` | `messages[i].tool_calls[j].id` (예: `toolu_01BFHkVg…`) | recon Q3 (조인 키), 10/10 매칭 |
| `parent_span_id` | synthetic root (`root-<request_id>`) | CC 선례 (`claude_code.py:203`) |
| `agent_or_node_id` | `tool_calls[j].function.name` | recon Q5 (206 유니크 tool 이름) |
| `span_kind` | `"tool"` | 전부 tool 호출 |
| `input_text` | `json.dumps(json.loads(tool_calls[j].function.arguments), sort_keys=True, ensure_ascii=False)` | 원본은 이미 JSON 문자열. §22.2 CC 선례처럼 **재직렬화로 sort_keys 정규화** → sha256 게이트 안정성 |
| `output_text` | 매칭 tool 메시지의 `content` (문자열 그대로) | recon Q2 (list content 없음, flat string). list 형식 발견 시 §22.5 규약 재사용 |
| `start_time` / `end_time` | synthetic (아래 §23.2) | recon Q4 |
| `token_count` | `None` | recon Q5 (`key_stats`는 트레이스 총합만) |
| `model` | 최상위 `modelname_run` | recon Q5 |
| `cost_rate` | `None` (span 단위 불명, `agent_cost`는 트레이스 총합) | recon Q5 |

## §23.2 — synthetic timestamp 규약

**사실**: per-message timestamp 없음 (recon Q5 확인). 최상위 `initial_run_time` / `completion_time` 만 존재하지만 span 단위 배분 불가.

**규약**:
- 기준: `base = 2026-01-01T00:00:00+00:00` (탐지기 정렬만 쓰므로 절대값 무의미, 단조성만 필요)
- `start_time = base + timedelta(seconds = msg_idx * 1000 + sub_idx)`
  - `msg_idx`: `messages` 배열의 인덱스 (0-based)
  - `sub_idx`: 해당 assistant 메시지의 `tool_calls` 배열 내 순서 (0-based)
- `end_time = start_time` (동일)

**정당화**:
- 탐지기 grep 확인 (2026-07-18): `src/clew/detect/structural.py:26,58,86` 는 `start_time` 만 정렬 키로 사용. `end_time` 정렬 없음. `cascade.py:60` 은 compact 창문 검사에만 사용 (Toolathlon 은 compact 없음 → no-op).
- recon Q4 실측: 병렬 호출 메시지 365건 중
  - 같은 msg 안 (name, args) 중복 **0** → sub_idx 로 순서 결정해도 tie-break 걱정 없음
  - 결과 순서 뒤바뀐 케이스 **0** → tool 결과가 tool_calls 배열 순서대로 옴
  → 이 규약이 origin ↔ candidate 순서를 보존한다.

**한계**:
- 이건 근사다. 실제 wall-clock 이 아니므로 gap(초) 는 msg 인덱스 차이 × 1000 (병렬은 +1). 시간 기반 통계(gap describe 등) 는 이 스케일 위에서만 해석 가능.
- §22.11 compact 게이트는 **no-op**: Trace.metadata 에 `compact_boundaries` 를 넣지 않으므로 기존 `.get(key, [])` 경로에서 자동 무시됨. Toolathlon 에는 CC 스타일 compact 개념 없음.

## §23.3 — 역직렬화 주의

**사실** (recon Q1):
- 최상위 11개 필드 **전부 JSON 문자열**. `json.loads()` 필요한 필드: `task_status`, `config`, `tool_calls`, `messages`, `key_stats`, `agent_cost`.
- 순수 문자열: `modelname_run`, `task_name`, `request_id`, `initial_run_time`, `completion_time`.

**어댑터 규약**:
- 각 필드 파싱 실패 시 **조용히 skip 금지, 명시적 `ValueError` raise** (§21.4).
- `tool_calls[j].function.arguments` 는 이미 JSON 문자열. 파싱 후 `sort_keys=True` 로 재직렬화 → sha256 게이트 안정.
- `content` 가 list 형식 (Anthropic content blocks) 인 경우 § 22.5 CC 규약 재사용 (block-by-block 렌더 + 비-text 블록은 `json.dumps` + warn). recon Q2 는 flat string 확인이지만 전 파일 확인은 어댑터 실행 시.

**조인 검증** (§22.4 선례):
- assistant 측 호출 id set = tool 측 결과 tool_call_id set 이 되어야 함.
- orphan 존재 시 명시적 에러 (첫 5개 id 로그).

## §23.4 — 감지 분기

**현재 상태** (`src/clew/__main__.py:30`):
```python
if path.suffix == ".jsonl":
    from clew.ingest.claude_code import ingest_claude_code_jsonl
    return ingest_claude_code_jsonl(path)
```
→ `.jsonl` 확장자는 무조건 CC 로 라우팅. Toolathlon .jsonl 도 여기 걸린다.

**개정**:
- `.jsonl` 진입 후 **첫 줄 JSON 을 peek** 해서 최상위 키로 분기:
  - `modelname_run` AND `task_status` AND `messages` → Toolathlon
  - `sessionId` (CC 마커) → CC
  - 어느 쪽도 아니면 명시적 에러 (최상위 키 앞 5개 로그)
- 두 마커 셋은 **겹치지 않음** (CC 는 `modelname_run` 없음, Toolathlon 은 `sessionId` 없음).

**신규 모듈**: `src/clew/ingest/toolathlon.py`
- 함수: `ingest_toolathlon_jsonl(path: Path) -> Trace`
- 파일 내 각 라인 = 트레이스 1개. **파일당 다중 Trace 반환은 하지 않음** — 어댑터는 "path → single Trace" 계약. 다중 트레이스 파일은 CLI 상위에서 iterate.
- 잠정 결정: `_load_trace_auto` 는 **첫 트레이스만** 반환 (CC 와 계약 동일). 파일 전량 스캔은 별도 헬퍼 `iter_toolathlon_traces(path) -> Iterator[Trace]` 로 노출, `field_test/diagnostics/scan_toolathlon.py` 에서 사용.

## §23.5 — 재실행 전 예측 (결과 보기 전)

**대상**: 받은 파일 `claude-4.5-sonnet-0929_1.jsonl` (108 트레이스). 어댑터 + 3단 게이트 (구조 → sha256 → compact) 를 108 트레이스 전량에 돌린다.

recon 은 잠정 정의 (파이썬 dict 그룹핑) 였다. 어댑터는 clew 구조 게이트 (`find_candidates`, N=2) 를 통해 갈 것이므로 카운트가 다를 수 있다.

| 지표 | recon 잠정 | 예측 |
|---|---|---|
| repeat 후보 (구조 게이트 통과) | 177 | **150 – 177** (동일 정의면 유사, N=2 구조 게이트가 인접성 조건을 더 엄격하게 볼 수 있음) |
| sha256 게이트 통과 (tool kind) | 32 | **25 – 35** (recon 시뮬레이션과 근접해야 함) |
| compact 게이트 no-op 확인 | — | Trace.metadata 에 키 없음 → cascade `.get(..., [])` 통과, 0건 제외 |
| 최종 waste (candidate 스팬 수) | — | **25 – 35** |

**예측 근거**:
- sha256 게이트가 recon 시뮬 (32) 과 근접해야 어댑터 조인이 정확한 것. 크게 벗어나면 어댑터 조인/파싱 버그.
- 빈-인자 (args='') 반복이 다수 포함될 것. playwright browser workflow (`playwright_with_chunk-browser_snapshot_navigate_to_next_span`, args='') 4 세션에서 count 7~13. 이는 "후보이지 확정 낭비 아님" — CC 의 ExitPlanMode 선례처럼 소유자 판정 필요.

**틀리면 틀렸다고 기록**.

### 음성 결과 정의
- waste (sha256 게이트 통과) 가 recon 시뮬 (32) 대비 ±10 이상 벗어나면 어댑터 조인/파싱 차이. 원인 규명 (§23.7 결과 섹션에), 정의 유지.

### 중단 조건
1. 기존 204 테스트 회귀 → 멈춤. 테스트 고쳐 통과 금지.
2. CC / OTel / OpenInference 결과 변화 → 멈춤. Toolathlon 분기는 독립이어야 함 (`_load_trace_auto` 분기 추가 외 다른 어댑터 파일 수정 금지).
3. φ / N / model / sha256 로직 변경 필요 → 즉시 멈춤 (§22.10 규정 재확인).
4. Span 자료구조 확장 필요 → 즉시 멈춤 (§22.11 선례처럼 `Trace.metadata` 만 확장 허용).

---

## §23.6 — 규칙 8 커밋 체인 (사전등록 시각 증명)

이 문서 (§23.1–§23.5) + recon 스크립트 2개 = **사전등록 커밋**.
- push → 서버 timestamp 찍힘.
- 어댑터 구현 코드는 **push 확인 후** 별도 커밋.
- PR / 머지 는 §23 완주 후 feat/cc-adapter 브랜치 통째로 (별도 요청).

## §23.7 — 재실행 결과 (2026-07-18)

**실행**: `python field_test/diagnostics/scan_toolathlon.py data/toolathlon/claude-4.5-sonnet-0929_1.jsonl`
**게이트**: φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2@e8f8c21, sha256 tool-kind ON.
**소요**: wall 0.7s.

### 예측 vs 실측

| 지표 | 예측 (§23.5) | 실측 | 판정 |
|---|---|---|---|
| repeat 후보 (구조 게이트 N=2) | 150–177 | **173** | ✓ 범위 안 |
| sha256 게이트 통과 (tool kind) | 25–35 | **28** | ✓ 범위 안 |
| waste 최종 | 25–35 | **28** | ✓ 범위 안 |

세 예측 모두 적중. recon 잠정치 (177 후보 / 32 sha 동일) 대비 -4 / -4 인데, 이는 구조 게이트가 N=2 인접성 조건으로 recon 의 dict-groupby 보다 좁게 자르기 때문이라 사전등록 예측과 일관.

### 로드 요약

- 파일 라인 수: 108
- 성공적으로 cascade 실행: **107**
- build 예외: **1** — `line#30 [build] ValueError: arguments JSON 파싱 실패 (원문 앞 80자: '{"path": "/workspace/dumps/workspace/format_data.py"')`
  - **원인**: 실데이터의 `filesystem-write_file` arguments 값이 52 자에서 잘림 (task=`quantitative-financial-analysis`, request_id=`671bb135-6a28-4ffa-acac-24374c8aa93b`). Toolathlon 데이터셋 원본 결함.
  - **처리**: 어댑터는 §21.4 대로 명시 raise. 스캔 스크립트가 라인별 catch 로 나머지 107 개 처리 계속.
  - 스캔 스크립트만 관용, 어댑터 계약(1 line → 1 Trace or ValueError)은 변경 없음.

### waste > 0 트레이스 분포 (14 트레이스)

| task_name | eval | waste 수 |
|---|---|---|
| k8s-pr-preview-testing | False | 8 |
| email-paper-homepage | False | 3 |
| reimbursement-form-filler | True | 3 |
| fillout-online-forms | True | 2 |
| (나머지 10 트레이스: 각 1–2 건) | mix | 12 |

**evaluation 별 낭비율**:
- eval=`False` (실패 63): waste 21건, waste-트레이스 11 (17.5%)
- eval=`True` (성공 44): waste 7건, waste-트레이스 3 (6.8%)

실패 트레이스가 성공 트레이스 대비 낭비 트레이스 비율 **2.6배**. arXiv:2602.19008 "canonical path deviation → failure" 방향과 일관 (통계 아님, 관측).

### waste 도구 분포

**args 있음 (27건)** — 상위:
- `filesystem-read_file` 5
- `pdf-tools-read_pdf_pages` 4
- `github-get_file_contents` 4
- `playwright_with_chunk-browser_type` 2
- `k8s-kubectl_get` 2
- `playwright_with_chunk-browser_navigate` 2
- `playwright_with_chunk-browser_wait_for` 2
- (기타 6 tool × 1건)

**args='' or '{}' (1건)**: `playwright_with_chunk-browser_close` args=`{}` × 1

recon 예측: "playwright next_span args='' 반복이 다수 포함될 것" — **틀림**. sha256 게이트가 대부분의 args='' 반복을 걸러냈다 (다른 페이지 → 다른 스냅샷 → sha256 불일치). CC 의 ExitPlanMode 선례처럼 args 없어도 낭비가 되려면 output 동일해야 하는데, playwright next_span 은 매 호출마다 다른 페이지로 진행하는 게 정상 사용법이라 output 이 다름. 결과: playwright next_span 은 waste=0.

### 어댑터 실장 노트 (사전등록 대비 미세 조정)

- `_normalize_arguments`: raw=`""` (빈 문자열) 은 Toolathlon 관례상 "인자 없음" 이므로 `{}` 로 정규화. 사전등록 (§23.3) 은 "파싱 실패 시 raise" 만 명시했는데, 빈 문자열은 파싱 실패가 아니라 관례로 처리. 어댑터 테스트 `test_arguments_parse_failure_raises` 는 "not valid json!!" 같은 진짜 malformed 만 대상.
- 여전히 malformed JSON (line 30 케이스) 은 하드 raise. §21.4 준수.

### 중단 조건 재확인

1. **204 회귀** — 216 통과 (신규 12 포함). 회귀 없음.
2. **CC/OTel/OpenInference 결과 변화** — `_load_trace_auto` 분기 로직만 확장. CC 테스트 `test_auto_dispatch_cc_still_works` 통과. 다른 어댑터 파일 수정 없음.
3. **φ / N / model / sha256 로직 변경** — 없음.
4. **Span 자료구조 확장** — 없음. `Trace.metadata` 에만 `source, task_name, task_status, modelname_run` 추가.

### 병합 방침

- 이 커밋은 `feat/cc-adapter` 브랜치의 §23 결과 커밋 (사전등록 e8da282 → 구현 → 결과).
- push 만. PR 은 별도 요청 (규칙 8 배치 PR 계획).
