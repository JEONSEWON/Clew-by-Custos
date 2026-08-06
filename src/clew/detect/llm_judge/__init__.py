# Spec: docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md (Rule 8 prereg).
"""LLM-as-judge layer for Clew.

Bounded, opt-in LLM-judge extensions to the deterministic detectors.
v1 covers only Semantic Duplicate (paraphrase-tolerant duplicate detection);
other axes (silent failure, hallucination, tone, convoluted route) are
deferred to future preregs per the prereg §9.
"""

from clew.detect.llm_judge.semantic_duplicate import (
    LLMJudgeMatch,
    LLMJudgeResult,
    find_llm_judge_semantic_duplicates,
)

__all__ = [
    "LLMJudgeMatch",
    "LLMJudgeResult",
    "find_llm_judge_semantic_duplicates",
]
