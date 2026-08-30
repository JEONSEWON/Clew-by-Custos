# Spec: docs/LLM_JUDGE_SEMANTIC_DUPLICATE_PREREG.md §4 (frozen)
#       + docs/LLM_JUDGE_AMENDMENT_v1.md §1.1 (ephemeral-ID clause added).
"""Frozen prompt template for the LLM judge.

DO NOT modify this file without a new prereg. The rubric is treated as
a locked artifact per Rule 8; any change to prompt wording, output
shape, or truncation length requires a supersede prereg.
"""

# Prereg §4: 4000-char truncation is frozen.
CHUNK_MAX_CHARS = 4000

# Prereg §4: confidence threshold is frozen at 0.85.
CONFIDENCE_THRESHOLD = 0.85


SYSTEM_PROMPT = (
    "You are a strict equivalence judge for LLM message chunks. "
    "Two chunks are \"equivalent\" only if they express the same "
    "request, tool call, or information to the LLM. Formatting "
    "differences (whitespace, punctuation, quotation style) are "
    "equivalent. Ephemeral identifiers that are randomly generated "
    "per invocation (e.g. tool_use_id, message_id, id fields on tool "
    "calls / tool results) are NOT semantic content. ignore them "
    "when judging equivalence. Different content, values, or intent "
    "are NOT equivalent."
)


USER_TEMPLATE = (
    "Chunk A:\n{chunk_a}\n\n"
    "Chunk B:\n{chunk_b}\n\n"
    "Return a JSON object:\n"
    "{{\"equivalent\": <true|false>, \"confidence\": <0.0-1.0>, "
    "\"reasoning\": \"<one-sentence reason>\"}}"
)


def build_user_message(chunk_a: str, chunk_b: str) -> str:
    """Frozen prompt assembly. Truncates each chunk to CHUNK_MAX_CHARS."""
    a = chunk_a[:CHUNK_MAX_CHARS]
    b = chunk_b[:CHUNK_MAX_CHARS]
    return USER_TEMPLATE.format(chunk_a=a, chunk_b=b)
