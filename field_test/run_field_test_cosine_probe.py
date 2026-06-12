"""field_test/run_field_test_cosine_probe.py

RAW vs EXTRACTED cosine 분리 진단.
가설 (a) JSON 스캐폴드 부풀림 vs (b) phi-transfer 문제를 수치로 분리.
그래프 실행 없음 — 직전 런(run_field_test_router_fp.py) output_text 하드코딩.
수정 없음. 숫자 보고 후 멈춤.
src/clew 은 read-only import 만.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from clew.detect.semantic import Embedder, cosine

# ── Frozen params ──────────────────────────────────────────────────────
PHI   = 0.514345
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV   = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE = Path(".cache/embeddings")

# ── 직전 런(run_field_test_router_fp.py) collapse 후 researcher output_text ──
# 이 값이 cascade가 실제 임베딩하는 텍스트
RAW_1 = '{"research": "첫 번째 조사 결과: 멀티에이전트 낭비의 기술적 원인 분석.", "loop_count": 1}'
RAW_2 = '{"research": "두 번째 조사 결과: 비용 구조와 토큰 소비 패턴 검토.", "loop_count": 2}'
RAW_3 = '{"research": "세 번째 조사 결과: 루프 종료 조건 및 핸드오프 최적화 방향.", "loop_count": 3}'

# ── 앵커 (phi 위치 감각 — 판정에 사용 안 함) ───────────────────────────
# HIGH: run_field_test_waste.py 패러프레이즈 쌍 (이미 cosine 0.927 확인)
ANCHOR_HIGH_A = (
    "멀티에이전트 AI에서 토큰 낭비 주요 원인: "
    "(1) 동일 정보 재조회 — 에이전트가 이미 확보한 정보를 같은 도구로 다시 요청한다. "
    "(2) 출력 재생성 — 다음 에이전트가 직전 에이전트의 결과를 동일 내용으로 다시 작성한다. "
    "(3) 루프 미종료 — 탈출 조건 없이 완료된 작업을 계속 반복한다."
)
ANCHOR_HIGH_B = (
    "AI 멀티에이전트 시스템의 낭비 원인 요약: "
    "(1) 중복 조회 — 이미 가진 데이터를 반복해서 가져온다. "
    "(2) 결과 재작성 — 이전 에이전트 출력을 동일한 의미로 재생성한다. "
    "(3) 무한 반복 — 작업이 끝났음에도 루프가 계속 실행된다."
)
# LOW: 완전 다른 도메인 두 문장
ANCHOR_LOW_A = "오늘 오후 서울 기온은 28도로 맑고 건조한 날씨가 예상된다."
ANCHOR_LOW_B = "데이터베이스 인덱스는 쿼리 성능을 높이지만 쓰기 비용을 증가시킨다."


def extract(raw: str) -> str:
    """JSON 상태딕 → research 필드 값만 추출."""
    try:
        return json.loads(raw)["research"]
    except (json.JSONDecodeError, KeyError):
        return raw


def strip_prefix(text: str) -> str:
    """'N번째 조사 결과: ' 공유 접두사 제거 — ': ' 첫 등장 이후 substring."""
    idx = text.find(": ")
    if idx == -1:
        return text
    return text[idx + 2:]


def vsign(val: float, phi: float) -> str:
    return f"> phi ({'▲' if val >= phi else ''})" if val >= phi else f"< phi ({'▽'})"


def main():
    embedder = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE)

    # ── 3가지 표현 구성 ────────────────────────────────────────────────
    raws      = [RAW_1,        RAW_2,        RAW_3]
    extracted = [extract(r)    for r in raws]
    stripped  = [strip_prefix(e) for e in extracted]

    # ── [REPRESENTATIONS] ──────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("[REPRESENTATIONS] 3가지 표현 텍스트 (육안 확인)")
    print(f"{'='*70}")
    labels = ["R1", "R2", "R3"]
    for i, (r, e, s) in enumerate(zip(raws, extracted, stripped)):
        print(f"\n  {labels[i]}:")
        print(f"    RAW      : {r}")
        print(f"    EXTRACTED: {e}")
        print(f"    STRIPPED : {s}")

    # ── 임베딩 사전 계산 ───────────────────────────────────────────────
    emb_raw  = [embedder.embed(t) for t in raws]
    emb_ext  = [embedder.embed(t) for t in extracted]
    emb_str  = [embedder.embed(t) for t in stripped]

    pairs = [(0, 1, "R1 vs R2"), (0, 2, "R1 vs R3"), (1, 2, "R2 vs R3")]

    # ── [COSINE-MATRIX] ────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"[COSINE-MATRIX]  phi={PHI}")
    print(f"{'='*70}")
    hdr = f"  {'pair':10s} | {'RAW':7s} {'vs phi':10s} | {'EXTRACTED':9s} {'vs phi':10s} | {'STRIPPED':8s} {'vs phi':10s}"
    print(hdr)
    print("  " + "-"*9 + "-+-" + "-"*17 + "-+-" + "-"*19 + "-+-" + "-"*18)

    results = []
    for i, j, label in pairs:
        c_raw = cosine(emb_raw[i], emb_raw[j])
        c_ext = cosine(emb_ext[i], emb_ext[j])
        c_str = cosine(emb_str[i], emb_str[j])
        results.append((label, c_raw, c_ext, c_str))
        print(
            f"  {label:10s} | {c_raw:.4f}  {vsign(c_raw, PHI):10s} "
            f"| {c_ext:.4f}    {vsign(c_ext, PHI):10s} "
            f"| {c_str:.4f}   {vsign(c_str, PHI):10s}"
        )

    # ── [ANCHORS] ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"[ANCHORS]  phi={PHI}  (판정에 사용 안 함 — 위치 감각)")
    print(f"{'='*70}")
    c_high = cosine(embedder.embed(ANCHOR_HIGH_A), embedder.embed(ANCHOR_HIGH_B))
    c_low  = cosine(embedder.embed(ANCHOR_LOW_A),  embedder.embed(ANCHOR_LOW_B))
    print(f"  HIGH (패러프레이즈): cosine={c_high:.4f}  {vsign(c_high, PHI)}  (기대: > phi)")
    print(f"  LOW  (무관 도메인): cosine={c_low:.4f}  {vsign(c_low, PHI)}  (기대: < phi)")

    # ── [VERDICT] ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("[VERDICT]")
    print(f"{'='*70}")

    raw_fires  = sum(1 for _, c, _, _ in results if c >= PHI)
    ext_fires  = sum(1 for _, _, c, _ in results if c >= PHI)
    str_fires  = sum(1 for _, _, _, c in results if c >= PHI)

    print(f"  phi 초과 쌍 수:  RAW={raw_fires}/3  EXTRACTED={ext_fires}/3  STRIPPED={str_fires}/3")

    # RAW → EXTRACTED 변화
    raw_to_ext = [(label, c_r, c_e) for label, c_r, c_e, _ in results]
    drops = [(l, r, e) for l, r, e in raw_to_ext if r >= PHI and e < PHI]
    stays = [(l, r, e) for l, r, e in raw_to_ext if e >= PHI]

    print()
    if len(drops) > 0 and ext_fires == 0:
        print("  → 판정 (a): EXTRACTED 후 모든 쌍 phi 아래.")
        print("    JSON 스캐폴드(구조 키 + loop_count)가 유사도를 부풀림.")
        print("    어댑터가 output.value에서 실제 내용을 추출하지 않는 것이 원인.")
    elif ext_fires > 0 and ext_fires < 3:
        print(f"  → 판정 혼합: EXTRACTED 후 {ext_fires}쌍 phi 초과 잔존.")
        print("    (a) 부분 기여 확인 + (b) phi-transfer 문제도 존재 가능.")
        for l, r, e in stays:
            print(f"    잔존 쌍 {l}: RAW={r:.4f} → EXTRACTED={e:.4f} (여전히 > phi)")
    elif ext_fires == 3:
        print("  → 판정 (b): EXTRACTED 후에도 모든 쌍 phi 초과.")
        print("    JSON 스캐폴드 제거로 유사도 변화 없음.")
        print("    phi가 실측 non-redundant 분포에 transfer 안 됨.")
        print("    실제 non-redundant 출력 코퍼스로 분포 재측정 필요.")
    else:
        print("  → RAW에서 phi 초과 없음 — 예상 밖 결과. 로그 확인 필요.")

    # EXTRACTED vs STRIPPED 차이
    print()
    print("  공유 접두사('N번째 조사 결과:') 기여:")
    for label, c_r, c_e, c_s in results:
        delta = c_e - c_s
        direction = "↑ 접두사가 유사도 올림" if delta > 0.02 else (
            "↓ 접두사 제거시 오히려 내려감" if delta < -0.02 else "≈ 미미")
        print(f"    {label}: EXTRACTED={c_e:.4f} → STRIPPED={c_s:.4f}  Δ={delta:+.4f}  {direction}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
