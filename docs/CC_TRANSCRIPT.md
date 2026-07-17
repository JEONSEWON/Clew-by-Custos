# CC_TRANSCRIPT — Claude Code 원본 transcript 리콘 결과

**Scope**: 이 문서는 **제품 입력 포맷** 명세다. SWE-chat 파생 데이터셋(`conversations.parquet`) 이 아니라 Claude Code 원본 JSONL (`~/.claude/projects/<slug>/<uuid>.jsonl`) 을 대상으로 한다.

**Fold-back 규칙 (SPEC 규칙 7)**: 외부 사실을 raw 로 확인한 후 SPEC 에 반영. 코드 어댑터 작성 전 리콘 결과부터 문서화한다.

**근거 스크립트**: `field_test/diagnostics/recon_cc_transcript.py` (Q1~Q6 · Q3-A/B · Q4-A/B/C).
**리콘 표본**: `~/.claude/projects/` 전 9 프로젝트, 20 세션 파일 (2026-06-18 ~ 2026-07-17). 세부 통계는 최근 완료 세션 1개 (`f96aee88-...`, 779 라인) 기준. 파일 크기 상위 아님 (규모 교란 회피).

**transcript 커밋 금지**: 실 작업 내용이라 레포에 원본 데이터 포함하지 않는다. 스크립트만 커밋.

---

## §21.1 — thinking 평문 부재 (검증됨)

**사실**: Claude Code assistant 메시지의 `type=thinking` content 블록은 `thinking` 필드가 빈 문자열이고, 대신 `signature` (base64 blob) 이 저장된다.

블록 구조 (Q4-A raw):
```json
{"type": "thinking", "thinking": "", "signature": "EsYCCokBCA8YAipAF6BPF7A61wbfDyfQNiYI9bcg...(len=444)"}
```
- keys: `['signature', 'thinking', 'type']`
- `type`: str len=8
- `thinking`: str len=0
- `signature`: str len=444

**전수 (Q4-B, 9 프로젝트 / 20 파일)**:
- thinking 블록 총 553건
- `thinking` 텍스트 non-zero **1건** (52자, 2026-06-30T12:28:27Z)
- `redacted_thinking` 블록: 0건

**시간 분포 (Q4-C)**:
- 2026-06: n=57, min=0, max=52, nonzero=1
- 2026-07: n=496, min=0, max=0, nonzero=**0**
- ts_min: 2026-06-18T15:04:44Z / ts_max: 2026-07-17T10:48:03Z

**결론**: Claude Code 는 thinking 평문을 저장하지 않는다. signature blob 만 남긴다. 2026-07 기준 100% 0자.

**함의**:
- SWE-chat 의 `assistant_thinking` = 128건 (37,978 assistant 행의 0.34%) 는 **파이프라인 손실이 아니다.** 원본에도 없다.
- "왜 다시 읽었나 판정 불가" 는 **데이터셋 한계가 아니라 벤더 구조 한계.** 원본 transcript 를 확보해도 이 한계는 유지된다.
- SWECHAT_SPEC.md 의 정직 경계 서술은 이 사실에 의해 근거 강화된다 (링크만, 아래 §21.5 교차 참조 참조).

---

## §21.2 — 토큰 usage 존재 (SWE-chat 과 다름)

**사실**: assistant 턴 344/344 (100%) 에 `message.usage` 딕셔너리가 부착된다.

**필드 (Q3-A)**:
```
input_tokens / output_tokens
cache_creation_input_tokens / cache_read_input_tokens
cache_creation.{ephemeral_1h_input_tokens, ephemeral_5m_input_tokens}
server_tool_use.{web_search_requests, web_fetch_requests}
service_tier / inference_geo / iterations / speed
```

**샘플 raw**:
```json
{"input_tokens": 6, "cache_creation_input_tokens": 11968,
 "cache_read_input_tokens": 18483, "output_tokens": 152, ...}
```

**output_tokens (nonzero 344/344)**: min=90, median=629, max=20223.

**tool 턴 (user role + tool_result) 에는 usage 미부착.**

### §21.2 미검증 가설 — tool_result 비용 귀속

5쌍 관찰 (Q3-B, Read tool_result char 수 vs 인접 assistant usage):
```
P#0: read_chars=3542   prev cache_r=30451  |  next cache_r=31544 cache_c=2864
P#1: read_chars=2852   prev cache_r=31544  |  next cache_r=34408 cache_c=2242
P#2: read_chars=757    prev cache_r=34408  |  next cache_r=36650 cache_c=635
P#3: read_chars=659    prev cache_r=36650  |  next cache_r=37285 cache_c=513
P#4: read_chars=1035   prev cache_r=44379  |  next cache_r=45048 cache_c=738
```

**미검증 가설**: `prev.cache_read + prev.cache_creation = next.cache_read` 가 관찰 3쌍에서 성립. tool_result 텍스트가 다음 assistant 턴의 `cache_creation_input_tokens` 에 계상되는 것으로 보인다. char/token 비율 1.19~1.40 (n=5).

**5쌍이다. 전수 검증 전까지 인용 금지 (규율 5).**

**백로그**: 전수 검증을 사전등록 (규칙 8: PR 먼저) 후 "실측 토큰 비용" 측정. 검증되면 낭비 판정에 토큰 값을 붙일 수 있다.

---

## §21.3 — tool_use ↔ tool_result 1:1 조인 (SWE-chat 과 다름)

**사실 (Q6, `f96aee88-...` 세션 기준)**:
- 조인 필드: `tool_use.id` ↔ `tool_result.tool_use_id`
- tool_use 총 180, unique 180
- tool_result 총 180, unique 180
- 중복 tool_use_id: 0
- 고아 (매칭 없는 result / use): 각각 0

**per-tool**:
- Bash: use=108, res_pair_max=1, use_with_>1_res=0
- Read: use=25, res_pair_max=1, use_with_>1_res=0
- Edit=31, Write=11, Grep=4, ToolSearch=1

**함의**:
- SWE-chat 의 Bash 1:N (SPEC §19.1: 1,732 keys, max_dup=5) 은 **파이프라인 산물이다.** 원본은 1:1.
- 1 세션 기준. **다세션 확인은 백로그.**

---

## §21.4 — 벤더 포맷 변경 독립 확증

**Read tool_result 라인 접두 (Q5, `f96aee88-...` 세션)**:

repr / ord:
```
'1\t# SPEC §19 — SWE-chat 실사용 코딩 세션 낭비 밀도 '
ord=[49, 9, 35, 32, 83, 80, 69, 67, ...]
```
- ord[0]=49 (`'1'`), ord[1]=**9 (TAB, U+0009)**
- 화살표(U+2192, ord=8594) **아님**.

**함의**:
- SWE-chat 에서 관찰한 "2026-03-28 벤더 포맷 전환" (SPEC §19.2 사실 A) 이 원본 transcript 로 확증됨.
- 캐시 마커 `unchanged` 17건 검출 → **`File unchanged since last read` 문구는 변경되지 않았다.**

**어댑터 설계 지침**:
- 벤더 출력 포맷은 변한다. 하드코딩 정규식에 의존하지 마라.
- **인식 실패 시 조용히 넘어가지 말고 명시적 에러**를 낸다.
- 근거 사례: `LINE_PREFIX = re.compile(r'^\s*\d+→')` 가 9,941건(15.66%)을 조용히 error 로 오분류 (SPEC §19.2 편차 7 계열).

---

## §21.5 — SWECHAT_SPEC.md 교차 참조

- **§21.1 (thinking 부재)** → `field_test/SWECHAT_SPEC.md` "핵심 한계" (line 147 근방) 의 "assistant_thinking 0.34%" 서술을 이 문서로 갱신 (근거 강화). 내용 복사 금지, 링크로 참조.
- **§21.3 (조인 1:1)** → `field_test/SWECHAT_SPEC.md` §19.1 Bash 1:N 서술 (max_dup=5) 은 파이프라인 산물임이 원본 리콘으로 확증.
- **§21.4 (포맷 전환)** → `field_test/SWECHAT_SPEC.md` §19.2 사실 A 예측(전환 시점) 이 원본으로 확증.

**이 문서 (CC_TRANSCRIPT.md) 가 원본 기준 사실의 단일 출처 (single source).** SWECHAT_SPEC.md 는 파생 데이터셋 분석 결과만 유지.
