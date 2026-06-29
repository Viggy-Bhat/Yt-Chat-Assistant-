"""Auto-generate a LangSmith eval dataset from an already-ingested workspace.

Usage:
    python -m evals.generate_dataset --workspace-id <uuid>
    python -m evals.generate_dataset --workspace-id <uuid> --max-examples 50 --max-negative 3

Generates one question per transcript chunk (sampled evenly across the video)
plus a small set of negative/off-topic questions. Uploads to a LangSmith dataset
named ``{langsmith_project}-{workspace_id}``. Idempotent: if the dataset already
exists it appends new examples rather than raising.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

# Ensure the project root is on sys.path so ``backend`` is importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from langchain_groq import ChatGroq
from langsmith import Client as LangSmithClient

from backend.core.config import get_settings
from backend.services.ingestion import vectorstore_service


def _collect_chunks(workspace_id: str, min_words: int = 40):
    """Return all non-trivial chunks from a workspace's Chroma collection."""
    coll = vectorstore_service.get_or_create_collection(workspace_id)
    data = coll.get()
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []
    ids = data.get("ids") or []

    chunks = []
    for i, doc in enumerate(documents):
        if len(doc.split()) < min_words:
            continue
        meta = metadatas[i] if i < len(metadatas) else {}
        chunks.append(
            {
                "text": doc,
                "start": meta.get("start", 0.0),
                "end": meta.get("end", 0.0),
                "id": ids[i] if i < len(ids) else str(i),
            }
        )
    # chronological order for even sampling
    chunks.sort(key=lambda c: c["start"])
    return chunks


def _sample_evenly(chunks, n: int):
    """Pick *n* chunks spread evenly across the sorted list."""
    if len(chunks) <= n:
        return list(chunks)
    indices = [int(i * len(chunks) / n) for i in range(n)]
    return [chunks[i] for i in indices]


def _make_llm(settings):
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0.0,
    )


def _generate_video_summary(llm, chunks) -> str:
    """Ask the LLM for a one-line summary from the first few chunks."""
    sample = [c["text"][:300] for c in chunks[:3]]
    prompt = (
        "Based on the following video transcript excerpts, provide a one-line summary"
        " of what this video is about:\n\n" + "\n\n".join(sample)
    )
    return llm.invoke(prompt).content.strip()


def _generate_question(llm, chunk_text: str) -> str:
    prompt = (
        f"Here is an excerpt from a video transcript:\n\n{chunk_text}\n\n"
        "Write ONE specific question that this excerpt directly and fully answers.\n"
        "The question should be answerable from this excerpt alone, without needing "
        "other parts of the video.\n"
        "Respond with only the question text, nothing else."
    )
    return llm.invoke(prompt).content.strip()


def _generate_negative_question(llm, summary: str) -> str:
    prompt = (
        f"Here is a one-line summary of a YouTube video: '{summary}'\n\n"
        "Write a question that sounds like it COULD be about this video's general "
        "topic, but is NOT actually answered by the transcript. The question should "
        "be plausible and related to the general theme, but something the transcript "
        "does not cover.\n"
        "Respond with only the question text, nothing else."
    )
    return llm.invoke(prompt).content.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Generate a LangSmith evaluation dataset from an ingested workspace."
    )
    parser.add_argument(
        "--workspace-id", required=True, help="UUID of an already-ingested workspace."
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=20,
        help="Maximum number of positive examples to generate (sampled evenly).",
    )
    parser.add_argument(
        "--max-negative",
        type=int,
        default=5,
        help="Number of negative (off-topic) examples to add.",
    )
    args = parser.parse_args()

    settings = get_settings()
    llm = _make_llm(settings)

    if not settings.langsmith_api_key:
        sys.exit("LANGSMITH_API_KEY is not set. Cannot upload dataset.")

    # ---- Collect + sample chunks ----
    all_chunks = _collect_chunks(args.workspace_id)
    if not all_chunks:
        sys.exit(f"No non-trivial chunks found for workspace {args.workspace_id}.")
    print(f"Found {len(all_chunks)} eligible chunks, sampling {args.max_examples}...")
    selected = _sample_evenly(all_chunks, args.max_examples)

    # ---- Generate positive examples ----
    examples: list[dict] = []
    for chunk in selected:
        try:
            question = _generate_question(llm, chunk["text"])
        except Exception as e:
            print(f"  Skipping chunk at {chunk['start']}s: {e}")
            continue
        examples.append(
            {
                "question": question,
                "workspace_id": args.workspace_id,
                "expected_timestamp_range": [chunk["start"], chunk["end"]],
                "source_chunk_text": chunk["text"],
            }
        )
    print(f"Generated {len(examples)} positive examples.")

    # ---- Generate negative examples ----
    if args.max_negative > 0:
        try:
            summary = _generate_video_summary(llm, all_chunks)
            print(f"Video summary: {summary}")
        except Exception as e:
            print(f"  Could not generate summary: {e}. Skipping negative examples.")
            summary = None

        if summary:
            for _ in range(args.max_negative):
                try:
                    question = _generate_negative_question(llm, summary)
                except Exception as e:
                    print(f"  Failed to generate negative question: {e}")
                    continue
                examples.append(
                    {
                        "question": question,
                        "workspace_id": args.workspace_id,
                        "expected_timestamp_range": None,
                        "source_chunk_text": None,
                    }
                )
            print(f"Generated {args.max_negative} negative examples.")

    # ---- Upload to LangSmith ----
    dataset_name = f"{settings.langsmith_project.strip()}-{args.workspace_id}"
    client = LangSmithClient()

    try:
        dataset = client.create_dataset(dataset_name=dataset_name)
        print(f"Created new dataset '{dataset_name}'.")
    except Exception:
        dataset = client.read_dataset(dataset_name=dataset_name)
        print(f"Dataset '{dataset_name}' already exists; appending examples.")

    for ex in examples:
        client.create_example(
            inputs={"question": ex["question"]},
            outputs={
                "workspace_id": ex["workspace_id"],
                "expected_timestamp_range": ex["expected_timestamp_range"],
                "source_chunk_text": ex["source_chunk_text"],
            },
            dataset_id=dataset.id,
        )

    print(f"Done. Uploaded {len(examples)} examples to '{dataset_name}'.")


if __name__ == "__main__":
    main()
