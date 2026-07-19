"""requery_known pattern.

Structure: root → start → lookup(tool) → process(chain) → lookup(tool) → finalize
positive: the 2nd lookup uses the same key as the 1st → refetching known info.
clean   : the 2nd lookup uses a different key → a normal 2-step lookup.

Topology is identical between positive and clean (same node sequence and
span_kind).
Waste label: the 2nd lookup in the positive trace.

Clean-pool design:
- Two lookups draw from separate pools (A / B) so they cover different
  domains, formats, and contents.
- KV, natural-language, and mixed forms are shuffled together so that
  structured-schema surface form does not dominate between the two lookups.
  (The calibrate diagnostic found intrusions where 'name=…, plan=…, MRR=$…'
  structured surface was mistaken for semantic similarity by the embedder,
  pushing progression-pair cosines over φ — this blocks that defect.)
"""

from __future__ import annotations

from clew.model import Trace

from .base import GeneratedTrace, make_context, make_trace, span

PATTERN = "requery_known"


# HARD pool (SPEC §8 2.1 + CRITERIA C1): both lookups use the
# 'customer_id=…' form with different values/responses. If structural.py's
# input gate (normalized-identical to the original) is working, this
# produces 0 candidates — the gate-behavior proof. (in1, out1, in2, out2)
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

# MIXED A: 1st-lookup pool — KV, natural language, and mixed forms.
# Domains: user / order / billing / config.
_CLEAN_POOL_MIXED_A: list[tuple[str, str]] = [
    ("order_id=7821", "주문 7821 — 키보드 1개, 2026-01-12 배송 완료, 결제액 8.4만원"),
    ("invoice=INV-2026-031", "청구서 INV-2026-031 상태 paid, 금액 1,240,000원, 결제일 1월 18일"),
    ("doc=spec-v3", "spec-v3 문서는 17쪽 분량, 마지막 수정 2025-11-30, 작성자 인프라팀"),
    ("user=u_99", "u_99 프로필: 가입 6개월, 마지막 로그인 어제 오후, 권한 admin"),
    ("ticket=T-4410", "T-4410 티켓 — 상태 in_progress, 담당 sehee, SLA 24h 남음"),
    ("flag=enable_v2", "기능 플래그 enable_v2 — 현재 50% 롤아웃, 에러율 변화 없음"),
    ("session=s_77ab", "세션 s_77ab는 23분간 유효, 브라우저 Safari, 위치 서울"),
]

# MIXED B: 2nd-lookup pool — ops / infra / contract domains.
# Domain and phrasing are kept separate from pool A.
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
    """Pick one pair from the HARD pool — both lookups use `customer_id=…`
    with different values/responses."""
    return rng.choice(_CLEAN_POOL_HARD)


def _pick_mixed_pair(rng) -> tuple[str, str, str, str]:
    """One item each from MIXED A / B — the two lookups cover different domains."""
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
    # Positive intent: same-key re-lookup → byte-identical output (this is
    # the normal signal). Therefore fixed, no pool — dup cosines across
    # instances clustering at 1.0 is the expected outcome.
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
