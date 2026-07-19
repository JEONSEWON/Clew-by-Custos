# Clew — trace file creation and analysis

## How to turn your trace into a Clew input file

Clew accepts the OTel SDK `span.to_json()` array form (Format A) as input.

### Using InMemorySpanExporter (the most common path)

```python
import json
from pathlib import Path
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# 1. instrumentation setup
exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))

# 2. attach a framework instrumentor (e.g. LangChain/LangGraph)
from openinference.instrumentation.langchain import LangChainInstrumentor
LangChainInstrumentor().instrument(tracer_provider=provider)

# 3. run the app
# app.invoke(inputs)  ← spans are captured here

# 4. write out as a Clew input file
spans = exporter.get_finished_spans()
Path("trace.json").write_text(
    json.dumps([json.loads(s.to_json()) for s in spans])
)
```

The same pattern works for every OpenInference-instrumented framework
(**CrewAI, AutoGen, LlamaIndex, PydanticAI**, etc.). Just swap the instrumentor:

```python
# CrewAI
from openinference.instrumentation.crewai import CrewAIInstrumentor
CrewAIInstrumentor().instrument(tracer_provider=provider)

# LlamaIndex
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
LlamaIndexInstrumentor().instrument(tracer_provider=provider)

# OpenAI client
from openinference.instrumentation.openai import OpenAIInstrumentor
OpenAIInstrumentor().instrument(tracer_provider=provider)
```

### LangGraph-specific helper (capture_langgraph)

A one-step helper that runs a LangGraph app object and saves it to file:

```python
from clew.capture import capture_langgraph
trace = capture_langgraph(app, {"topic": "..."}, Path("trace.json"))
```

### If you send spans to a Phoenix/OTLP collector

If you're sending spans to Phoenix (`http://127.0.0.1:6006/v1/traces`) or an OTel
collector, a file-export path is not officially supported today.
**Recommended for now — the InMemoryExporter path**: attach `InMemorySpanExporter`
alongside `OTLPSpanExporter`, save via the method above, then feed the file to Clew.

```python
# attach both exporters in parallel
provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))  # for Clew
provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))  # for Phoenix
```

---

## Running analysis

```bash
# analyze an OTel SDK JSON file
python -m clew analyze trace.json

# existing Clew Trace JSON also works (backward compatible)
python -m clew analyze clew_trace.json

# write a markdown report to file
python -m clew analyze trace.json --out report.md

# also emit a JSON report
python -m clew analyze trace.json --out report.md --json report.json
```

---

## Example file

`examples/sample_otel_trace.json` — a 5-span clean trace (no waste; expected to print "no waste detected").

```bash
python -m clew analyze examples/sample_otel_trace.json
```
