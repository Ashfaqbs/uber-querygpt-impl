"""
Intent Agent — maps the user's question to one or more workspaces.

Mirrors Uber V2: the intent agent narrows the search radius by classifying
the question into a business domain before any table/SQL retrieval happens.

Two strategies:
  1. Vector search against WorkspaceRegistry descriptions (fast, no LLM call)
  2. LLM call to classify when vector confidence is low (fallback)
"""

import logging

import ollama
import weaviate

from app.core.embeddings import embed

log = logging.getLogger(__name__)

LLM_MODEL = "qwen3:8b"


def detect_intent_by_vector(
    client: weaviate.WeaviateClient, question: str, top_k: int = 2
) -> list[str]:
    """
    Embed the question and find the closest workspace descriptions.
    Returns workspace names ranked by similarity.
    """
    query_vector = embed(question)
    collection = client.collections.get("WorkspaceRegistry")

    results = collection.query.near_vector(
        near_vector=query_vector,
        limit=top_k,
        return_properties=["workspace", "description"],
    )

    workspaces = [obj.properties["workspace"] for obj in results.objects]
    log.info("Intent (vector): question mapped to workspaces: %s", workspaces)
    return workspaces


def detect_intent_by_llm(
    client: weaviate.WeaviateClient, question: str
) -> list[str]:
    """
    Fallback: ask the LLM to classify the question into workspace(s).
    Used when vector similarity scores are low or ambiguous.
    """
    collection = client.collections.get("WorkspaceRegistry")
    all_workspaces = collection.query.fetch_objects(
        return_properties=["workspace", "description"]
    )

    workspace_list = "\n".join(
        f"- {obj.properties['workspace']}: {obj.properties['description']}"
        for obj in all_workspaces.objects
    )

    prompt = f"""You are a data domain classifier. Given a user question, identify which workspace(s) are relevant.

Available workspaces:
{workspace_list}

User question: "{question}"

Reply with ONLY a comma-separated list of workspace names that are relevant. Example: mobility,payments
Do not explain. Do not add anything else."""

    response = ollama.generate(model=LLM_MODEL, prompt=prompt, options={"temperature": 0, "think": False})
    raw = response["response"].strip().lower()
    workspaces = [w.strip() for w in raw.split(",") if w.strip()]
    log.info("Intent (LLM): question mapped to workspaces: %s", workspaces)
    return workspaces


def run(
    client: weaviate.WeaviateClient,
    question: str,
    use_llm_fallback: bool = False,
) -> list[str]:
    """
    Entry point for the intent agent.
    Returns a list of workspace names relevant to the question.
    """
    if use_llm_fallback:
        return detect_intent_by_llm(client, question)
    return detect_intent_by_vector(client, question)
