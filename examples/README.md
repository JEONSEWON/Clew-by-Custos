# Clew — 트레이스 파일 생성 및 분석

## 내 트레이스를 Clew 입력 파일로 만드는 법

Clew는 OTel SDK `span.to_json()` 배열 형식(Format A)을 입력으로 받는다.

### InMemorySpanExporter를 쓰는 경우 (가장 흔한 경로)

```python
import json
from pathlib import Path
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# 1. 계측 설정
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))

# 2. 프레임워크별 계측기 연결 (예: LangChain/LangGraph)
from openinference.instrumentation.langchain import LangChainInstrumentor
LangChainInstrumentor().instrument(tracer_provider=provider)

# 3. 앱 실행
# app.invoke(inputs)  ← 여기서 스팬이 캡처됨

# 4. Clew 입력 파일로 저장
spans = exporter.get_finished_spans()
Path("trace.json").write_text(
    json.dumps([json.loads(s.to_json()) for s in spans])
)
```

동일 패턴이 **CrewAI, AutoGen, LlamaIndex, PydanticAI** 등 OpenInference 계측 지원
프레임워크 전체에 적용된다. 계측기만 교체하면 된다:

```python
# CrewAI
from openinference.instrumentation.crewai import CrewAIInstrumentor
CrewAIInstrumentor().instrument(tracer_provider=provider)

# LlamaIndex
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
LlamaIndexInstrumentor().instrument(tracer_provider=provider)

# OpenAI 클라이언트
from openinference.instrumentation.openai import OpenAIInstrumentor
OpenAIInstrumentor().instrument(tracer_provider=provider)
```

### LangGraph 전용 헬퍼 (capture_langgraph)

LangGraph 앱 객체를 직접 실행하고 파일로 저장하는 원스텝 헬퍼:

```python
from clew.capture import capture_langgraph
trace = capture_langgraph(app, {"topic": "..."}, Path("trace.json"))
```

### Phoenix/OTLP collector로 보내고 있는 경우

Phoenix(`http://127.0.0.1:6006/v1/traces`)나 OTel collector로 스팬을 보내는 경우,
현재는 파일 export 경로가 공식 지원되지 않는다.
**현재는 InMemoryExporter 경로 권장**: `OTLPSpanExporter` 대신 `InMemorySpanExporter`를
추가로 달고 위 방법으로 파일 저장 후 Clew에 입력.

```python
# 두 exporter 병렬 연결
provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))  # Clew용
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))  # Phoenix용
```

---

## 분석 실행

```bash
# OTel SDK JSON 파일 분석
python -m clew analyze trace.json

# 기존 Clew Trace JSON도 그대로 동작 (하위 호환)
python -m clew analyze clew_trace.json

# 마크다운 리포트 파일로 저장
python -m clew analyze trace.json --out report.md

# JSON 리포트 추가 출력
python -m clew analyze trace.json --out report.md --json report.json
```

---

## 예제 파일

`examples/sample_otel_trace.json` — 5-span 클린 트레이스 (낭비 없음, "no waste detected" 기대).

```bash
python -m clew analyze examples/sample_otel_trace.json
```
