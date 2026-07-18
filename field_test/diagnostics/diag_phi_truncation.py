"""field_test/diagnostics/diag_phi_truncation.py

φ 무판별력 가설 확인 (진단, 커밋 금지 예정 없음 — 도구 자체는 커밋).

배경: §22.8.8 waste #3 origin/cand sha256 불일치 (24,872B vs 32,163B) 인데 cos=1.0000.
가설: paraphrase-multilingual-MiniLM-L12-v2 는 max_seq_length ≈ 128 토큰. 잘림.

규율:
- 정의/φ/코드 수정 금지. Embedder / cascade / structural 모두 건드리지 않음.
- raw 출력. 결론 금지.

대상 세션: f96aee88-df87-41a6-8f6e-be05d3928018 (§22.6/§22.7/§22.8.8 동일).

Usage:
    python field_test/diagnostics/diag_phi_truncation.py --q 1   # 모델 max_seq_length
    python field_test/diagnostics/diag_phi_truncation.py --q 2   # 실제 잘림 여부
    python field_test/diagnostics/diag_phi_truncation.py --q 3   # 세션 전체 영향 규모
    python field_test/diagnostics/diag_phi_truncation.py --q 4   # 반증 실험
    python field_test/diagnostics/diag_phi_truncation.py --q 5   # sha256 게이트 시뮬레이션
"""
from __future__ import annotations

import argparse
import hashlib
import statistics
import sys
import warnings
from pathlib import Path

TARGET_JSONL = (
    Path.home()
    / ".claude/projects/C--Users-User-Desktop-Custos---clwe-project"
    / "f96aee88-df87-41a6-8f6e-be05d3928018.jsonl"
)
MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
REV = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CACHE_DIR = Path.home() / ".cache/clew/embeddings"
PHI = 0.514345

WASTE = {
    "1": ("toolu_01FpniGnXxoE4AXg1R5SodkT", "toolu_01JRtN5gD5Kasqx6s5uZ7eZA"),
    "2": ("toolu_01FpniGnXxoE4AXg1R5SodkT", "toolu_019vePnaQrtbXGzKLNvF7pUn"),
    "3": ("toolu_016ruLyijuJSr2qDxWRagJen", "toolu_01FyRBDgmMtoMk83jhGPbfpY"),
    "4": ("toolu_017bFHLqnQgAawh1jtWVMy3g", "toolu_01YSSm43o4VmMzA17sX8Cqqb"),
}


def _load_trace():
    from clew.ingest.claude_code import ingest_claude_code_jsonl
    warnings.simplefilter("ignore")
    return ingest_claude_code_jsonl(TARGET_JSONL)


def _get_span_by_tool_use_id(trace, tid: str):
    for s in trace.spans:
        if s.span_id == tid:
            return s
    return None


def _load_model():
    """읽기 전용 로드. Embedder 를 만들지만 embed 하지 않고 내부 모델만 꺼낸다."""
    from clew.detect.semantic import Embedder
    emb = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)
    emb._load_model()  # noqa: SLF001 (진단)
    return emb, emb._model


def q1() -> None:
    print("--- Q1. 임베딩 코드 인용 ---\n")
    print("### src/clew/detect/cascade.py (전문)")
    print(Path("src/clew/detect/cascade.py").read_text(encoding="utf-8"))
    print("\n### src/clew/detect/semantic.py::_compute / _load_model")
    text = Path("src/clew/detect/semantic.py").read_text(encoding="utf-8")
    import re
    m = re.search(r"def _compute.*?(?=\n    def [a-z_]+\(|\nclass |\Z)", text, re.DOTALL)
    print(m.group(0) if m else "NOT FOUND")
    m = re.search(r"def _load_model.*?(?=\n    def [a-z_]+\(|\nclass |\ndef |\Z)", text, re.DOTALL)
    print(m.group(0) if m else "NOT FOUND")

    print("\n--- Q1. 실측 (모델 로드) ---")
    _, model = _load_model()
    print(f"model.max_seq_length      = {model.max_seq_length}")
    tok = model.tokenizer
    print(f"model.tokenizer.__class__ = {tok.__class__.__name__}")
    print(f"tokenizer.model_max_length = {tok.model_max_length}")
    print(f"tokenizer.truncation_side  = {getattr(tok, 'truncation_side', '<none>')}")
    print(f"tokenizer.padding_side     = {getattr(tok, 'padding_side', '<none>')}")

    print("\n--- Q1. truncation 설정: encode() 호출부 (semantic.py:79) ---")
    print("    vec = self._model.encode(text, normalize_embeddings=True, convert_to_numpy=True)")
    print("  → truncation 인자 명시 없음. SentenceTransformer.encode 는 내부적으로")
    print("     `self.tokenize(sentences)` 호출 시 model.max_seq_length 로 잘라낸다 (묵시).")


def _tokens(model, text: str) -> list[int]:
    """model.tokenizer.encode(text) 로 토큰 id 리스트."""
    return model.tokenizer.encode(text, add_special_tokens=True)


def q2() -> None:
    """waste #3 실제 토큰 수 + 앞 128 토큰 decode sha256 비교."""
    trace = _load_trace()
    _, model = _load_model()

    o_id, c_id = WASTE["3"]
    o = _get_span_by_tool_use_id(trace, o_id)
    c = _get_span_by_tool_use_id(trace, c_id)
    assert o is not None and c is not None

    msl = model.max_seq_length
    print(f"--- Q2. waste #3 토큰 수 (max_seq_length={msl}) ---")

    o_ids = _tokens(model, o.output_text)
    c_ids = _tokens(model, c.output_text)
    print(f"origin.output_text: chars={len(o.output_text)}  bytes={len(o.output_text.encode('utf-8'))}  tokens={len(o_ids)}  >msl={len(o_ids) > msl}")
    print(f"cand.output_text  : chars={len(c.output_text)}  bytes={len(c.output_text.encode('utf-8'))}  tokens={len(c_ids)}  >msl={len(c_ids) > msl}")

    o_head = o_ids[:msl]
    c_head = c_ids[:msl]
    o_dec = model.tokenizer.decode(o_head, skip_special_tokens=True)
    c_dec = model.tokenizer.decode(c_head, skip_special_tokens=True)

    print(f"\n앞 {msl} 토큰만 decode 후 비교:")
    print(f"  origin_head len chars = {len(o_dec)}")
    print(f"  cand_head   len chars = {len(c_dec)}")
    o_h = hashlib.sha256(o_dec.encode("utf-8")).hexdigest()
    c_h = hashlib.sha256(c_dec.encode("utf-8")).hexdigest()
    print(f"  origin_head sha256 = {o_h}")
    print(f"  cand_head   sha256 = {c_h}")
    print(f"  head_equal (decoded str) = {o_dec == c_dec}")

    # 토큰 id 자체도 비교
    o_ih = hashlib.sha256(",".join(str(x) for x in o_head).encode("utf-8")).hexdigest()
    c_ih = hashlib.sha256(",".join(str(x) for x in c_head).encode("utf-8")).hexdigest()
    print(f"  origin_head token_ids sha256 = {o_ih}")
    print(f"  cand_head   token_ids sha256 = {c_ih}")
    print(f"  head_equal (token ids)  = {o_head == c_head}")

    # 어디서 갈라지나
    diverge = None
    for i, (a, b) in enumerate(zip(o_head, c_head)):
        if a != b:
            diverge = i
            break
    if diverge is None and len(o_head) == len(c_head):
        print(f"  ids 완전 동일 (길이 {len(o_head)})")
    elif diverge is None:
        print(f"  공통 prefix 뒤에 한쪽만 계속됨 (짧은 쪽 길이={min(len(o_head), len(c_head))})")
    else:
        print(f"  token id 갈라지는 위치 = index {diverge} (앞 128 안)")
        print(f"    origin[{diverge}]={o_head[diverge]}  cand[{diverge}]={c_head[diverge]}")

    # 앞 200자 실제 문자열
    print(f"\n  origin.output_text[:200] = {o.output_text[:200]!r}")
    print(f"  cand.output_text[:200]   = {c.output_text[:200]!r}")


def q3() -> None:
    """세션 Read tool_result 25건 (실제로는 span 전체) 토큰 수 describe."""
    trace = _load_trace()
    _, model = _load_model()
    msl = model.max_seq_length

    reads = [s for s in trace.spans if s.agent_or_node_id == "Read"]
    print(f"--- Q3. 세션 Read span n={len(reads)} (max_seq_length={msl}) ---")
    lens = [len(_tokens(model, s.output_text)) for s in reads]
    if lens:
        exceed = sum(1 for x in lens if x > msl)
        print(f"tokens: n={len(lens)} min={min(lens)} p50={int(statistics.median(lens))} "
              f"mean={int(statistics.mean(lens))} max={max(lens)}")
        print(f"  exceed_msl: {exceed}/{len(lens)} ({exceed/len(lens):.1%})")

    print(f"\n--- Q3-b. §22.8.8 waste 4건 origin/cand 토큰 수 ---")
    for k, (o_id, c_id) in WASTE.items():
        o = _get_span_by_tool_use_id(trace, o_id)
        c = _get_span_by_tool_use_id(trace, c_id)
        if o is None or c is None:
            print(f"  waste #{k}: NOT FOUND")
            continue
        o_t = len(_tokens(model, o.output_text))
        c_t = len(_tokens(model, c.output_text))
        print(f"  waste #{k}: origin={o.agent_or_node_id} tokens={o_t} (>msl={o_t > msl})   "
              f"cand={c.agent_or_node_id} tokens={c_t} (>msl={c_t > msl})")


def q4() -> None:
    """반증 실험: 앞 128 토큰만 잘라 embed → cosine. 완전히 다른 파일도 참고."""
    from clew.detect.semantic import Embedder, cosine
    trace = _load_trace()
    emb = Embedder(model_name=MODEL, revision=REV, cache_dir=CACHE_DIR)
    _, model = _load_model()
    msl = model.max_seq_length

    o_id, c_id = WASTE["3"]
    o = _get_span_by_tool_use_id(trace, o_id)
    c = _get_span_by_tool_use_id(trace, c_id)
    assert o is not None and c is not None

    print(f"--- Q4. waste #3 (SWECHAT_SPEC.md Read) ---")
    ov_full = emb.embed(o.output_text)
    cv_full = emb.embed(c.output_text)
    cos_full = cosine(ov_full, cv_full)
    print(f"cosine(full origin, full cand) = {cos_full:.6f}   (φ={PHI})")

    o_ids = _tokens(model, o.output_text)
    c_ids = _tokens(model, c.output_text)
    o_head_str = model.tokenizer.decode(o_ids[:msl], skip_special_tokens=True)
    c_head_str = model.tokenizer.decode(c_ids[:msl], skip_special_tokens=True)
    ov_head = emb.embed(o_head_str)
    cv_head = emb.embed(c_head_str)
    cos_head = cosine(ov_head, cv_head)
    print(f"cosine(origin[:{msl}tok], cand[:{msl}tok]) = {cos_head:.6f}")

    # origin full vs origin head — 잘렸다면 (모델이 앞 128만 봤다면) 두 벡터가 같아야 함
    cos_o_full_head = cosine(ov_full, ov_head)
    cos_c_full_head = cosine(cv_full, cv_head)
    print(f"cosine(origin_full, origin_head[:{msl}]) = {cos_o_full_head:.6f}")
    print(f"cosine(cand_full,   cand_head[:{msl}])   = {cos_c_full_head:.6f}")

    print(f"\n--- Q4-b. 참고: 완전히 다른 두 파일 cosine ---")
    p1 = Path("field_test/SWECHAT_SPEC.md")
    p2 = Path("field_test/run_swechat_waste_scan.py")
    t1 = p1.read_text(encoding="utf-8", errors="replace")
    t2 = p2.read_text(encoding="utf-8", errors="replace")
    print(f"  {p1} chars={len(t1)} tokens={len(_tokens(model, t1))}")
    print(f"  {p2} chars={len(t2)} tokens={len(_tokens(model, t2))}")
    v1 = emb.embed(t1)
    v2 = emb.embed(t2)
    print(f"  cosine(SWECHAT_SPEC.md, run_swechat_waste_scan.py) = {cosine(v1, v2):.6f}   (φ={PHI})")

    # 참고: 짧은 두 다른 문장 (128 토큰 이하 다른 언어)
    a = "안녕하세요, 오늘 날씨가 참 좋네요."
    b = "The mitochondria is the powerhouse of the cell."
    va = emb.embed(a)
    vb = emb.embed(b)
    print(f"  cosine('안녕...', 'The mitochondria...') = {cosine(va, vb):.6f}   (짧고 완전히 다른 문장 대조)")


def q5() -> None:
    """§22.8.8 repeat 후보 6건 각각 sha256 비교 (측정만)."""
    from clew.detect.structural import find_repeat_candidates
    trace = _load_trace()
    pairs = find_repeat_candidates(trace, n=2)
    print(f"--- Q5. §22.8.8 repeat 후보 sha256 게이트 시뮬레이션 ---")
    print(f"repeat_candidates n={len(pairs)}\n")

    # 창문 내 target 파일 Edit 검사도 함께 (waste_context 결과 재활용 불가 → 여기선 tool 이름만)
    # 세션 내 Edit/Write/MultiEdit 이벤트 (start_time 순)
    ordered = sorted(trace.spans, key=lambda s: s.start_time)
    edits = [s for s in ordered if s.agent_or_node_id in ("Edit", "Write", "MultiEdit")]

    def _edits_between(o_start, c_start, target_basename: str):
        hits = []
        for e in edits:
            if not (o_start < e.start_time < c_start):
                continue
            # input_text 는 JSON 문자열. file_path 파싱.
            import json
            try:
                inp = json.loads(e.input_text)
                fp = inp.get("file_path") or inp.get("path") or ""
                if Path(fp).name == target_basename:
                    hits.append(e)
            except Exception:
                pass
        return hits

    true_count = 0
    for i, (o, c) in enumerate(pairs, 1):
        oh = hashlib.sha256(o.output_text.encode("utf-8")).hexdigest()
        ch = hashlib.sha256(c.output_text.encode("utf-8")).hexdigest()
        equal = (oh == ch)
        if equal:
            true_count += 1
        target = None
        try:
            import json
            inp = json.loads(c.input_text)
            fp = inp.get("file_path") or inp.get("path") or ""
            target = Path(fp).name if fp else None
        except Exception:
            pass

        line = (
            f"  #{i}: name={c.agent_or_node_id:<6} target={target!r:<40} "
            f"sha256_equal={equal}  o_len={len(o.output_text)} c_len={len(c.output_text)}"
        )
        if target is not None:
            edits_in = _edits_between(o.start_time, c.start_time, target)
            line += f"  edits_in_window={len(edits_in)}"
        print(line)

    print(f"\nsha256_equal True 건수: {true_count}/{len(pairs)}")


HANDLERS = {"1": q1, "2": q2, "3": q3, "4": q4, "5": q5}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True, choices=list(HANDLERS.keys()))
    args = ap.parse_args()
    if not TARGET_JSONL.exists():
        sys.exit(f"target session not found: {TARGET_JSONL}")
    HANDLERS[args.q]()


if __name__ == "__main__":
    main()
