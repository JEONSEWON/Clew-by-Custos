"""field_test/real_app.py — Real ChatAnthropic(Haiku) LangGraph factory functions.

Five graph factories for the real-trace probe experiment (SPEC §11).
API key read from os.environ["ANTHROPIC_API_KEY"] — never hardcoded.
src/clew is import-only (zero diff).
"""
from __future__ import annotations

import os
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END

_HAIKU = "claude-haiku-4-5-20251001"

# Queries for requery_clean negative control (different inputs per call)
_REQUERY_CLEAN_QUERIES = ["quantum computing basics", "quantum hardware advances"]


def _make_llm() -> ChatAnthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return ChatAnthropic(model=_HAIKU, max_tokens=512, temperature=0, api_key=api_key)


@tool
def fake_search(query: str) -> str:
    """Simulated search tool returning fixed content."""
    return (
        f"Search result for '{query}': "
        "Quantum computing leverages quantum mechanical phenomena such as superposition "
        "and entanglement to process information fundamentally differently from classical bits. "
        "Key applications include cryptography, optimization, and drug discovery simulation."
    )


# ── State schemas ──────────────────────────────────────────────────────────

class CleanState(TypedDict):
    topic: str
    research: str
    summary: str
    critique: str


class LoopState(TypedDict):
    topic: str
    research: str
    loop_count: int
    summary: str
    critique: str


class RequeryState(TypedDict):
    query: str
    result: str
    loop_count: int
    summary: str
    critique: str


class PingPongState(TypedDict):
    topic: str
    research: str
    critique: str
    ping_count: int


# ── Factory 1: clean (E1 baseline) ────────────────────────────────────────

def make_clean_app():
    """researcher → summarizer → critic (3 LLM calls, no waste)."""
    llm = _make_llm()

    def researcher(state: CleanState) -> dict:
        msg = llm.invoke(f"Research this topic and provide a factual overview: {state['topic']}")
        return {"research": msg.content}

    def summarizer(state: CleanState) -> dict:
        msg = llm.invoke(f"Summarize in 3 bullet points: {state['research']}")
        return {"summary": msg.content}

    def critic(state: CleanState) -> dict:
        msg = llm.invoke(f"Evaluate this summary and identify gaps: {state['summary']}")
        return {"critique": msg.content}

    g = StateGraph(CleanState)
    g.add_node("researcher", researcher)
    g.add_node("summarizer", summarizer)
    g.add_node("critic", critic)
    g.set_entry_point("researcher")
    g.add_edge("researcher", "summarizer")
    g.add_edge("summarizer", "critic")
    g.add_edge("critic", END)
    return g.compile()


# ── Factory 2: repeat_node (E2) ───────────────────────────────────────────

def make_repeat_node_app():
    """researcher loops twice (same prompt) → summarizer → critic (4 LLM calls).

    Both researcher invocations share agent_or_node_id='researcher' →
    find_repeat_candidates(n=2) fires.
    """
    llm = _make_llm()

    def researcher(state: LoopState) -> dict:
        msg = llm.invoke(f"Research this topic: {state['topic']}")
        return {"research": msg.content, "loop_count": state["loop_count"] + 1}

    def summarizer(state: LoopState) -> dict:
        msg = llm.invoke(f"Summarize in 3 bullet points: {state['research']}")
        return {"summary": msg.content}

    def critic(state: LoopState) -> dict:
        msg = llm.invoke(f"Evaluate this summary and identify gaps: {state['summary']}")
        return {"critique": msg.content}

    def should_loop(state: LoopState) -> str:
        return "researcher" if state["loop_count"] < 2 else "summarizer"

    g = StateGraph(LoopState)
    g.add_node("researcher", researcher)
    g.add_node("summarizer", summarizer)
    g.add_node("critic", critic)
    g.set_entry_point("researcher")
    g.add_conditional_edges("researcher", should_loop, {"researcher": "researcher", "summarizer": "summarizer"})
    g.add_edge("summarizer", "critic")
    g.add_edge("critic", END)
    return g.compile()


# ── Factory 3: requery_known (E2) ─────────────────────────────────────────

def make_requery_known_app():
    """fake_search called twice with same query → tool input gate fires (2 LLM + 2 tool calls).

    searcher node runs once; fake_search invoked twice with identical input →
    find_repeat_candidates input gate passes → cascade fires.
    No chain-node self-loop: only tool spans repeat.
    """
    llm = _make_llm()

    def searcher(state: RequeryState) -> dict:
        _result1 = fake_search.invoke(state["query"])
        result2 = fake_search.invoke(state["query"])
        return {"result": result2, "loop_count": 2}

    def summarizer(state: RequeryState) -> dict:
        msg = llm.invoke(f"Summarize this search result in 3 bullet points: {state['result']}")
        return {"summary": msg.content}

    def critic(state: RequeryState) -> dict:
        msg = llm.invoke(f"Evaluate this summary and identify gaps: {state['summary']}")
        return {"critique": msg.content}

    g = StateGraph(RequeryState)
    g.add_node("searcher", searcher)
    g.add_node("summarizer", summarizer)
    g.add_node("critic", critic)
    g.set_entry_point("searcher")
    g.add_edge("searcher", "summarizer")
    g.add_edge("summarizer", "critic")
    g.add_edge("critic", END)
    return g.compile()


# ── Factory 4: requery_clean (negative control) ───────────────────────────

def make_requery_clean_app():
    """fake_search called twice with DIFFERENT queries → tool input gate rejects (2 LLM + 2 tool calls).

    searcher node runs once; fake_search invoked twice with different inputs →
    find_repeat_candidates input gate rejects → cascade does NOT fire.
    No chain-node self-loop: only tool spans repeat, gate is the sole arbiter.
    """
    llm = _make_llm()

    def searcher(state: RequeryState) -> dict:
        _result1 = fake_search.invoke(_REQUERY_CLEAN_QUERIES[0])
        result2 = fake_search.invoke(_REQUERY_CLEAN_QUERIES[1])
        return {"result": result2, "loop_count": 2}

    def summarizer(state: RequeryState) -> dict:
        msg = llm.invoke(f"Summarize this search result in 3 bullet points: {state['result']}")
        return {"summary": msg.content}

    def critic(state: RequeryState) -> dict:
        msg = llm.invoke(f"Evaluate this summary and identify gaps: {state['summary']}")
        return {"critique": msg.content}

    g = StateGraph(RequeryState)
    g.add_node("searcher", searcher)
    g.add_node("summarizer", summarizer)
    g.add_node("critic", critic)
    g.set_entry_point("searcher")
    g.add_edge("searcher", "summarizer")
    g.add_edge("summarizer", "critic")
    g.add_edge("critic", END)
    return g.compile()


# ── Factory 5: pingpong (E2) ──────────────────────────────────────────────

def make_pingpong_app():
    """researcher → critic → researcher → critic (A→B→A→B, 4 LLM calls).

    Both researcher invocations share agent_or_node_id='researcher',
    both critic invocations share 'critic' →
    find_pingpong_candidates fires on the 4-span window.
    """
    llm = _make_llm()

    def researcher(state: PingPongState) -> dict:
        msg = llm.invoke(f"Research this topic: {state['topic']}")
        return {"research": msg.content, "ping_count": state["ping_count"] + 1}

    def critic(state: PingPongState) -> dict:
        msg = llm.invoke(f"Critique this research output: {state['research']}")
        return {"critique": msg.content}

    def should_route(state: PingPongState) -> str:
        return "researcher" if state["ping_count"] < 2 else END

    g = StateGraph(PingPongState)
    g.add_node("researcher", researcher)
    g.add_node("critic", critic)
    g.set_entry_point("researcher")
    g.add_edge("researcher", "critic")
    g.add_conditional_edges("critic", should_route, {"researcher": "researcher", END: END})
    return g.compile()
