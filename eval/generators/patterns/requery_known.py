"""requery_known 패턴.

구조: root → start → lookup(tool) → process(chain) → lookup(tool) → finalize
positive: 2회차 lookup이 1회차와 동일 키 → 이미 가진 정보를 재조회.
clean   : 2회차 lookup이 다른 키 → 정상적인 2회 조회.

토폴로지는 positive/clean 동일(같은 노드 시퀀스·span_kind).
낭비 라벨: positive의 2회차 lookup.

clean 풀 설계:
- 두 lookup이 서로 다른 도메인·형식·내용을 갖도록 분리된 풀(A·B)에서 각각 선택.
- 정형 스키마 표면이 두 lookup 사이에서 지배하지 않도록 KV·자연어·혼합 형식 섞음.
  (calibrate 진단에서 'name=…, plan=…, MRR=$…' 정형 표면이 임베딩에서 의미 유사도로
  오인되어 진전 쌍 코사인이 φ를 넘는 침투가 확인됨 — 그 결함을 차단.)
"""

from __future__ import annotations

from clew.model import Trace

from .base import GeneratedTrace, make_context, make_trace, span

PATTERN = "requery_known"


# HARD 풀(SPEC §8 2.1 + CRITERIA C1): 두 lookup 모두 'customer_id=…' 형식·
# 값/응답 다름. structural.py 의 입력 게이트(원본과 정규화-동일)가 작동하면
# 후보 0 — 게이트 작동 증명용. (in1, out1, in2, out2)
_CLEAN_POOL_HARD: list[tuple[str, str, str, str]] = [
    ("customer_id=12345", "name=Alice, plan=Pro, MRR=$59",
     "customer_id=67890", "name=Bob, plan=Free, MRR=$0"),
    ("customer_id=20001", "name=Carol, plan=Team, MRR=$199",
     "customer_id=30050", "name=Dave, plan=Pro, MRR=$59"),
    ("customer_id=44002", "name=Eve, plan=Free, MRR=$0",
     "customer_id=55003", "name=Frank, plan=Enterprise, MRR=$999"),
    ("customer_id=70010", "name=Grace, plan=Pro, MRR=$59",
     "customer_id=80020", "name=Heidi, plan=Free, MRR=$0"),
    ("customer_id=91111", "name=Ivan, plan=Free, MRR=$0",
     "customer_id=92222", "name=Judy, plan=Pro, MRR=$129"),
]

# MIXED A: 1회차 풀 — KV·자연어·혼합 섞음. user/order/billing/config 도메인.
_CLEAN_POOL_MIXED_A: list[tuple[str, str]] = [
    ("order_id=7821", "주문 7821 — 키보드 1개, 2026-01-12 배송 완료, 결제액 8.4만원"),
    ("invoice=INV-2026-031", "청구서 INV-2026-031 상태 paid, 금액 1,240,000원, 결제일 1월 18일"),
    ("doc=spec-v3", "spec-v3 문서는 17쪽 분량, 마지막 수정 2025-11-30, 작성자 인프라팀"),
    ("user=u_99", "u_99 프로필: 가입 6개월, 마지막 로그인 어제 오후, 권한 admin"),
    ("ticket=T-4410", "T-4410 티켓 — 상태 in_progress, 담당 sehee, SLA 24h 남음"),
    ("flag=enable_v2", "기능 플래그 enable_v2 — 현재 50% 롤아웃, 에러율 변화 없음"),
    ("session=s_77ab", "세션 s_77ab는 23분간 유효, 브라우저 Safari, 위치 서울"),
]

# MIXED B: 2회차 풀 — 운영/인프라/계약 도메인. A와 도메인·표현 분리.
_CLEAN_POOL_MIXED_B: list[tuple[str, str]] = [
    ("incident_id=INC-44", "장애 INC-44는 EU 리전 한정으로 5분간 지속 후 자동 복구"),
    ("repo=core-svc", "core-svc 저장소 main 브랜치 — 어제 3 커밋, 빌드 통과"),
    ("contract=C-918", "C-918 계약 만료까지 47일, 자동갱신 옵션 켜져 있음"),
    ("region=ap-northeast-2", "ap-northeast-2 리전 가용성 99.97%, 지난주 짧은 네트워크 지터 1건"),
    ("agent=billing-bot", "billing-bot 가동 중 — 처리량 시간당 약 1,200건, 오류 0.2%"),
    ("metric=p95_latency", "p95 지연이 320ms에서 410ms로 상승, 트래픽 증가가 주 요인"),
    ("dataset=feedback_q1", "feedback_q1 데이터셋 8,431 행, 결측치 1.4%, 마지막 갱신 4월 2일"),
    ("threshold=alert_cpu", "alert_cpu 임계는 0.78로 설정, 최근 24시간 트리거 없음"),
]


def _pick_hard_pair(rng) -> tuple[str, str, str, str]:
    """HARD 풀에서 한 쌍 선택 — 두 lookup 모두 customer_id=… (값·응답 다름)."""
    return rng.choice(_CLEAN_POOL_HARD)


def _pick_mixed_pair(rng) -> tuple[str, str, str, str]:
    """MIXED A·B 에서 각각 하나씩 — 두 lookup이 서로 다른 도메인."""
    in1, out1 = rng.choice(_CLEAN_POOL_MIXED_A)
    in2, out2 = rng.choice(_CLEAN_POOL_MIXED_B)
    return in1, out1, in2, out2


def _topology(
    ctx,
    *,
    lookup1_input: str,
    lookup1_output: str,
    lookup2_input: str,
    lookup2_output: str,
) -> tuple[Trace, str]:
    root_id = ctx.next_span_id()
    start_id = ctx.next_span_id()
    l1_id = ctx.next_span_id()
    process_id = ctx.next_span_id()
    l2_id = ctx.next_span_id()
    finalize_id = ctx.next_span_id()

    spans = [
        span(
            ctx=ctx,
            span_id=root_id,
            parent_id=None,
            agent_or_node_id="run",
            span_kind="chain",
            start_sec=0,
            duration_sec=14,
            output_text="run complete",
        ),
        span(
            ctx=ctx,
            span_id=start_id,
            parent_id=root_id,
            agent_or_node_id="start",
            span_kind="chain",
            start_sec=1,
            output_text="initialize",
        ),
        span(
            ctx=ctx,
            span_id=l1_id,
            parent_id=root_id,
            agent_or_node_id="lookup",
            span_kind="tool",
            start_sec=2,
            input_text=lookup1_input,
            output_text=lookup1_output,
        ),
        span(
            ctx=ctx,
            span_id=process_id,
            parent_id=root_id,
            agent_or_node_id="process",
            span_kind="chain",
            start_sec=5,
            output_text="processed first result",
        ),
        span(
            ctx=ctx,
            span_id=l2_id,
            parent_id=root_id,
            agent_or_node_id="lookup",
            span_kind="tool",
            start_sec=8,
            input_text=lookup2_input,
            output_text=lookup2_output,
        ),
        span(
            ctx=ctx,
            span_id=finalize_id,
            parent_id=root_id,
            agent_or_node_id="finalize",
            span_kind="chain",
            start_sec=12,
            output_text="report ready",
        ),
    ]
    return make_trace(ctx, spans), l2_id


def make_positive(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    # positive 의도: 동일 키 재조회 → byte-identical 출력 (이게 정상 신호).
    # 따라서 풀 사용 없이 고정 — 인스턴스 간 dup 코사인이 1.0 클러스터로 모이는 게 정상.
    trace, l2_id = _topology(
        ctx,
        lookup1_input="customer_id=12345",
        lookup1_output="name=Alice, plan=Pro, MRR=$59",
        lookup2_input="customer_id=12345",
        lookup2_output="name=Alice, plan=Pro, MRR=$59",
    )
    return GeneratedTrace(
        trace=trace, waste_span_ids=[l2_id], pattern=PATTERN, class_="positive"
    )


def make_clean(*, trace_id: str, seed: int) -> GeneratedTrace:
    ctx = make_context(seed=seed, trace_id=trace_id)
    if ctx.rng.random() < 0.5:
        in1, out1, in2, out2 = _pick_hard_pair(ctx.rng)
    else:
        in1, out1, in2, out2 = _pick_mixed_pair(ctx.rng)
    trace, _ = _topology(
        ctx,
        lookup1_input=in1,
        lookup1_output=out1,
        lookup2_input=in2,
        lookup2_output=out2,
    )
    return GeneratedTrace(
        trace=trace, waste_span_ids=[], pattern=PATTERN, class_="negative"
    )
