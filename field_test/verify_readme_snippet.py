"""field_test/verify_readme_snippet.py — README 스니펫 실제 동작 검증 (API 호출 없음).

README의 InMemorySpanExporter 스니펫을 그대로 복붙해 FakeLLM으로 실행한 뒤
python -m clew analyze로 리포트가 생성되는지 확인한다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ── README 스니펫 그대로 ─────────────────────────────────────────────────────
# (실제 앱 대신 FakeLLM + LangGraph 사용)

import json  # noqa: F811 (README에 있음)
from pathlib import Path as _Path  # noqa: F811
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# 1. 계측 설정 (README 그대로)
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))

# 2. 계측기 연결 (README 그대로 — LangChain/LangGraph 예시)
from openinference.instrumentation.langchain import LangChainInstrumentor
LangChainInstrumentor().instrument(tracer_provider=provider)

# 3. 앱 실행 — FakeLLM으로 API 없이 스팬 생성
from langchain_core.language_models.fake import FakeListLLM
from langgraph.graph import END, StateGraph

class _State(TypedDict):
    topic: str
    result: str

llm = FakeListLLM(responses=["Multi-agent systems improve efficiency by 40% via parallel execution."])

def researcher(state: _State) -> dict:
    out = llm.invoke(state["topic"])
    return {"result": out}

g = StateGraph(_State)
g.add_node("researcher", researcher)
g.set_entry_point("researcher")
g.add_edge("researcher", END)
app = g.compile()
app.invoke({"topic": "impact of multi-agent AI on productivity", "result": ""})
provider.force_flush()

# 4. Clew 입력 파일로 저장 (README 스니펫 그대로)
OUT = _Path("field_test/verify_readme_output.json")
spans = exporter.get_finished_spans()
OUT.write_text(
    json.dumps([json.loads(s.to_json()) for s in spans])
)
LangChainInstrumentor().uninstrument()

print(f"[verify] 캡처된 span 수: {len(spans)}")
print(f"[verify] 저장 경로: {OUT}")

# ── python -m clew analyze 실행 ──────────────────────────────────────────────
result = subprocess.run(
    [sys.executable, "-m", "clew", "analyze", str(OUT)],
    capture_output=True,
    text=True,
    cwd=str(Path(__file__).parent.parent),
)

print(f"\n[verify] 종료 코드: {result.returncode}")
print("=== 리포트 출력 ===")
print(result.stdout)
if result.stderr:
    print("=== stderr ===")
    print(result.stderr)

if result.returncode != 0:
    print("[verify] FAIL — clew analyze가 비정상 종료")
    sys.exit(1)
elif "# Clew Waste Report" in result.stdout:
    print("[verify] PASS — README 스니펫 실제 동작 확인")
else:
    print("[verify] FAIL — 리포트 헤더 없음")
    sys.exit(1)
