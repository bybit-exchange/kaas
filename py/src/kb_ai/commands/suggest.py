"""Generate follow-up question suggestions based on the user's query and the AI's answer."""

import json
import logging

from kb_ai.llm import completion, CostTracker, get_request_tracker, set_request_tracker
from kb_ai.prompts import default_registry

logger = logging.getLogger(__name__)


def suggest_questions(query: str, answer: str, model: str = "claude-haiku-4-5") -> dict:
    """Generate follow-up question suggestions.

    Args:
        query: The user's original question.
        answer: The assistant's answer (may be truncated).
        model: LLM model to use.

    Returns:
        Dict with suggestions (list of strings), tokens_prompt, tokens_completion.
    """
    answer_truncated = answer[:2000] if len(answer) > 2000 else answer

    user_content = (
        f"User question: {query}\n\n"
        f"Assistant answer: {answer_truncated}\n\n"
        f"Suggest 3 follow-up questions (JSON array):"
    )

    system_prompt = default_registry().get("suggest").render()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    req_tracker = CostTracker()
    prev_tracker = get_request_tracker()
    set_request_tracker(req_tracker)
    try:
        raw = completion(model=model, messages=messages, temperature=0.7, max_tokens=256)
    finally:
        set_request_tracker(prev_tracker)

    summary = req_tracker.summary()

    suggestions = []
    text = raw.strip()
    logger.info("[suggest] raw LLM response: %s", text[:500])
    # Strip markdown code block wrapper if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            suggestions = [s for s in parsed if isinstance(s, str)][:3]
    except (json.JSONDecodeError, TypeError):
        logger.warning("[suggest] failed to parse JSON from: %s", text[:200])

    return {
        "suggestions": suggestions,
        "tokens_prompt": summary["total_prompt_tokens"],
        "tokens_completion": summary["total_completion_tokens"],
    }
