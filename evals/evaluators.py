"""Reference-free evaluators for the YouTube Chat RAG pipeline.

Both evaluators take the standard LangSmith (run, example) signature and
return a dict with ``key``, ``score`` (0.0–1.0 or None to skip), and
``comment``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langchain_groq import ChatGroq

from backend.core.config import get_settings

_REFUSAL_PATTERNS = [
    "couldn't find",
    "cannot",
    "don't have",
    "not in the transcript",
    "not available",
    "does not contain",
    "i cannot",
    "i don't",
    "no information",
    "not mentioned",
    "not covered",
    "doesn't mention",
]

# Small, fast model for LLM-as-judge — much higher throughput than the 70B
# used by the actual RAG chain, and a YES/NO classification task doesn't
# need a large model.
_JUDGE_MODEL = "llama-3.1-8b-instant"
_MAX_RETRIES = 5
_INITIAL_BACKOFF_S = 2.0


def _invoke_with_retry(llm: ChatGroq, prompt: str) -> str:
    """Call llm.invoke with exponential backoff on rate-limit (429) errors."""
    backoff = _INITIAL_BACKOFF_S
    for attempt in range(_MAX_RETRIES):
        try:
            response = llm.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            err_str = str(e).lower()
            if "429" in str(e) or "rate limit" in err_str or "too many" in err_str:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
            raise
    return ""


def faithfulness_evaluator(run, example):
    """LLM-as-judge: is the answer fully supported by the retrieved sources?

    For regular examples: asks Groq to judge YES/NO.
    For negative examples (expected_timestamp_range is None): checks whether
    the answer correctly refuses to answer (anti-hallucination check).
    """
    answer = (run.outputs or {}).get("output", "")
    sources = (run.outputs or {}).get("sources", [])
    expected_range = (example.outputs or {}).get("expected_timestamp_range")

    # ---- Negative example: check refusal ----
    if expected_range is None:
        refused = any(p in answer.lower() for p in _REFUSAL_PATTERNS)
        score = 1.0 if refused else 0.0
        return {
            "key": "faithfulness",
            "score": score,
            "comment": "negative: refusal={}".format(refused),
        }

    # ---- Positive example: LLM judge ----
    if not sources:
        return {"key": "faithfulness", "score": 0.0, "comment": "no sources retrieved"}

    source_texts = "\n\n".join(s.get("text", "") for s in sources if s.get("text"))
    judge_prompt = (
        f"Given these source excerpts:\n\n{source_texts}\n\n"
        f"And this answer:\n\n{answer}\n\n"
        "Is the answer fully and only supported by the excerpts? "
        "Reply YES or NO and a one-sentence reason."
    )

    settings = get_settings()
    judge_llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=_JUDGE_MODEL,
        temperature=0.0,
    )
    try:
        judge_text = _invoke_with_retry(judge_llm, judge_prompt)
    except Exception as e:
        return {"key": "faithfulness", "score": 0.0, "comment": f"judge error: {e}"}

    if not judge_text:
        return {"key": "faithfulness", "score": 0.0, "comment": "empty judge response"}

    score = 1.0 if judge_text.upper().startswith("YES") else 0.0
    return {"key": "faithfulness", "score": score, "comment": judge_text}


def retrieval_recall_evaluator(run, example):
    """Does at least one retrieved chunk overlap the expected timestamp range?

    Skips scoring (returns None) for negative examples where no range exists.
    """
    expected_range = (example.outputs or {}).get("expected_timestamp_range")
    if expected_range is None:
        return {"key": "retrieval_recall", "score": None, "comment": "skipped: negative"}

    expected_start, expected_end = expected_range
    sources = (run.outputs or {}).get("sources", [])

    if not sources:
        return {"key": "retrieval_recall", "score": 0.0, "comment": "no sources retrieved"}

    overlap = False
    for s in sources:
        s_start = s.get("start", 0.0)
        s_end = s.get("end", float("inf"))
        if s_start <= expected_end and s_end >= expected_start:
            overlap = True
            break

    return {
        "key": "retrieval_recall",
        "score": 1.0 if overlap else 0.0,
        "comment": "overlap" if overlap else "no overlap with [{:.0f}, {:.0f}]".format(
            expected_start, expected_end
        ),
    }
