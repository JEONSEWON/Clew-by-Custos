# Spec: docs/VERIFICATION_JUDGE_PREREG.md §2 (frozen).
"""Frozen prompt for the verification axis of the LLM judge.

DO NOT modify this file without a new prereg. Per Rule 8 the rubric is a locked
artifact: any change to wording, output shape, or truncation length requires a
supersede prereg. That applies with particular force here, because §7 of the
pre-registration says re-prompting after seeing the number is the thing
pre-registration exists to prevent.

Separate from `prompts.py` rather than added to it. That file is the frozen
rubric of the semantic-duplicate axis, and the two axes must be able to move
independently without either one's freeze being an obstacle to the other's.
"""

# Prereg §2: tool outputs are truncated to 2,000 chars each.
#
# Not a cost measure. Tool outputs are the bulk of a trace and they are not
# evidence about whether a check was run, while a truncated output still shows
# that it ran. A `pytest` invocation whose first 2,000 characters are visible
# has demonstrably been executed.
TOOL_OUTPUT_MAX_CHARS = 2000

# Prereg §2: the whole rendered view is bounded too. The labelled candidates
# run to 357 KB at the largest, and a judgement made on a silently dropped tail
# is a judgement nobody can reproduce, so the cut is explicit and the renderer
# says in the text that it happened.
VIEW_MAX_CHARS = 120_000
TRUNCATION_NOTICE = "\n\n[view truncated here: the session continues]\n"


SYSTEM_PROMPT = (
    "You judge whether an AI coding agent checked the code it changed. "
    "You are given one session as an ordered list of the agent's actions. "
    "Answer only from what the session shows. "
    "Running a test runner, executing the edited file, importing it and "
    "exercising it, compiling it, or reading back a result all count as "
    "checking. Editing a file and never running anything that would reveal a "
    "mistake does not count as checking. "
    "Inspecting the filesystem, reading a file, or searching text is not "
    "checking. Saying that something will be tested is not checking. "
    "Quote the command or action that decided your answer, verbatim from the "
    "session. If nothing in the session decided it, say so in the evidence "
    "field rather than inventing one."
)


USER_TEMPLATE = (
    "Session:\n{session}\n\n"
    "Did the agent check the code it changed, by any means?\n\n"
    "Return a JSON object and nothing else:\n"
    "{{\"checked\": <true|false>, "
    "\"evidence\": \"<the command or action that decided it, verbatim from "
    "the session, or an explanation if none>\", "
    "\"confidence\": <0.0-1.0>}}"
)


def build_verification_message(session_view: str) -> str:
    """Frozen prompt assembly. The view is bounded by `VIEW_MAX_CHARS`."""
    view = session_view
    if len(view) > VIEW_MAX_CHARS:
        view = view[:VIEW_MAX_CHARS] + TRUNCATION_NOTICE
    return USER_TEMPLATE.format(session=view)
