"""Run a LangSmith evaluation experiment against the real RAG pipeline.

Usage:
    python -m evals.run_eval --workspace-id <uuid>
    python -m evals.run_eval --workspace-id <uuid> --experiment-name "baseline-chunk800"

Expects a dataset named ``{langsmith_project}-{workspace_id}`` to already exist
(create it first with ``generate_dataset.py``).
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langsmith.evaluation import evaluate

from backend.core.config import get_settings
from backend.services.rag import build_chain
from backend.services.vectorstore import VectorStoreService
from backend.services.embeddings import get_embedding_service

from evals.evaluators import faithfulness_evaluator, retrieval_recall_evaluator


# ---- Thread-safe score accumulator ----

_lock = threading.Lock()
_scores: list[dict] = []


def _collecting_faithfulness(run, example):
    result = faithfulness_evaluator(run, example)
    with _lock:
        _scores.append(result)
    return result


def _collecting_retrieval_recall(run, example):
    result = retrieval_recall_evaluator(run, example)
    with _lock:
        _scores.append(result)
    return result


# ---- Context formatting (mirrors rag.py) ----


def _format_timestamp(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_context(chunks, max_chars: int = 12000) -> str:
    if not chunks:
        return "(no relevant context found)"
    pieces: list[str] = []
    used = 0
    for c in chunks:
        ts = _format_timestamp(c.start)
        line = f"[{ts}] {c.text}"
        if used + len(line) > max_chars:
            break
        pieces.append(line)
        used += len(line) + 1
    return "\n".join(pieces)


# ---- Retry helper for Groq calls ----


def _chain_invoke_with_retry(chain, inputs: dict, max_retries: int = 5, initial_backoff: float = 2.0) -> str:
    """Invoke the LCEL chain with exponential backoff on rate-limit errors."""
    backoff = initial_backoff
    for attempt in range(max_retries):
        try:
            response = chain.invoke(inputs)
            return response.content if isinstance(response.content, str) else str(response.content)
        except Exception as e:
            err_str = str(e).lower()
            if "429" in str(e) or "rate limit" in err_str or "too many" in err_str:
                if attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
            raise
    return ""


# ---- Target function ----


def make_rag_target(workspace_id: str):
    """Build a callable target function for a specific workspace.

    Uses the real production services (vectorstore, chain) — no
    reimplementation of the core logic.
    """
    settings = get_settings()
    embedding_service = get_embedding_service(settings.embedding_model)
    vectorstore = VectorStoreService(embedding_service)
    chain = build_chain()

    def target(inputs: dict) -> dict:
        question = inputs["question"]

        chunks = vectorstore.query(
            workspace_id, question, top_k=settings.retrieval_top_k
        )
        context = _format_context(chunks, max_chars=settings.max_context_chars)

        content = _chain_invoke_with_retry(
            chain, {"context": context, "history": [], "question": question}
        )

        return {
            "output": content,
            "sources": [
                {"start": c.start, "end": c.end, "text": c.text, "score": c.score}
                for c in chunks
            ],
        }

    return target


# ---- Summary printing ----


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def print_summary(experiment_name: str, project: str) -> None:
    faithfulness_scores = []
    retrieval_recall_scores = []
    negative_correct = 0
    total_examples = set()

    for s in _scores:
        total_examples.add(id(s))
        key = s.get("key")
        score = s.get("score")
        comment = s.get("comment", "")

        if key == "faithfulness" and score is not None:
            faithfulness_scores.append(score)
            if "refusal" in comment and score == 1.0:
                negative_correct += 1
        elif key == "retrieval_recall" and score is not None:
            retrieval_recall_scores.append(score)

    print()
    print("=" * 60)
    print(f"Experiment:               {experiment_name}")
    print(f"Total examples:           {len(total_examples)}")
    print(f"Mean faithfulness:        {_mean(faithfulness_scores):.3f}  "
          f"(over {len(faithfulness_scores)} scored)")
    print(f"Mean retrieval_recall:    {_mean(retrieval_recall_scores):.3f}  "
          f"(over {len(retrieval_recall_scores)} scored)")
    print(f"Negatives correctly refused: {negative_correct}")
    print(f"View in LangSmith: https://smith.langchain.com/o/-/projects/p/"
          f"{project}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Run a LangSmith evaluation experiment."
    )
    parser.add_argument(
        "--workspace-id", required=True, help="UUID of the ingested workspace."
    )
    parser.add_argument(
        "--experiment-name",
        default=None,
        help="Label for this experiment (default: auto-timestamp).",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.langsmith_api_key:
        sys.exit("LANGSMITH_API_KEY is not set. Cannot run evaluation.")

    dataset_name = f"{settings.langsmith_project.strip()}-{args.workspace_id}"
    experiment_name = (
        args.experiment_name
        or f"eval-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    print(f"Dataset:      {dataset_name}")
    print(f"Experiment:   {experiment_name}")
    print(f"Workspace:    {args.workspace_id}")
    print(f"Top-K:        {settings.retrieval_top_k}")
    print(f"Chunk size:   {settings.chunk_size}")
    print(f"Model:        {settings.groq_model}")
    print()

    target = make_rag_target(args.workspace_id)

    evaluate(
        target,
        data=dataset_name,
        evaluators=[_collecting_faithfulness, _collecting_retrieval_recall],
        experiment_prefix=experiment_name,
        max_concurrency=1,
    )

    print_summary(experiment_name, settings.langsmith_project)


if __name__ == "__main__":
    main()
