"""
ingest.py — One-time data ingestion script.

Uber V1 equivalent: "7 tier-1 tables and 20 SQL queries as our sample dataset"

This script does the OFFLINE part of the RAG pipeline:
  1. Read table schemas from tables.json       (our 7 tier-1 tables)
  2. Read SQL examples from queries.json       (our 20 reference queries)
  3. Embed each one using nomic-embed-text     (convert text → vector of 768 numbers)
  4. Store the vector + original text in Weaviate

Run this once before running query.py. After this, Weaviate holds the
knowledge base that the query pipeline searches at runtime.
"""

import json
import logging
from pathlib import Path

import ollama
import weaviate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

WEAVIATE_URL = "http://localhost:8080"

# nomic-embed-text: local embedding model running via Ollama.
# Converts any text into a list of 768 floats that represent its meaning.
EMBED_MODEL = "nomic-embed-text"

DATA_DIR = Path(__file__).parent.parent / "data"


def embed(text: str) -> list[float]:
    """
    Convert text into a vector (list of 768 floats) using nomic-embed-text.

    Uber V1: "vectorize user natural language prompt" — same model is used
    here at ingest time AND in query.py at search time. Both must use the
    same model so the vector space is consistent.
    """
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response["embedding"]


def ingest_tables(client: weaviate.WeaviateClient) -> None:
    """
    Embed and store all 7 table schemas into the TableSchema collection.

    Uber V1: "7 tier-1 tables with full schemas"
    Each table schema is a readable text block:
      Table: trips
      Columns:
        - trip_id (UUID): ...
        - pickup_city (VARCHAR): ...

    We embed the entire text block. At query time, when a user asks something
    like "how many trips per city?", the KNN search finds these schemas by
    semantic similarity and returns the most relevant ones.
    """
    tables_path = DATA_DIR / "tables.json"
    tables = json.loads(tables_path.read_text())

    collection = client.collections.get("TableSchema")

    for table in tables:
        # embed() converts the schema text to a 768-float vector
        vector = embed(table["content"])

        # Store both the vector (for search) and the original text (to return to LLM)
        collection.data.insert(
            properties={
                "table_name": table["table_name"],
                "content": table["content"],
            },
            vector=vector,
        )
        log.info("Inserted table schema: %s", table["table_name"])

    log.info("Done — inserted %d table schemas.", len(tables))


def ingest_queries(client: weaviate.WeaviateClient) -> None:
    """
    Embed and store all 20 SQL examples into the SqlExample collection.

    Uber V1: "20 reference SQL queries as sample data"
    Each example is a question + SQL pair:
      Question: how many trips per city?
      SQL: SELECT pickup_city, COUNT(*) FROM trips GROUP BY pickup_city

    We embed question + SQL together as one text block. This means the vector
    captures both the intent (question) and the pattern (SQL). At query time,
    a user's question will find these examples by similarity and they will be
    used as few-shot examples to guide the LLM.
    """
    queries_path = DATA_DIR / "queries.json"
    queries = json.loads(queries_path.read_text())

    collection = client.collections.get("SqlExample")

    for item in queries:
        # Combine question + SQL into one text so the embedding captures both
        text = f"Question: {item['question']}\nSQL: {item['sql']}"
        vector = embed(text)

        collection.data.insert(
            properties={
                "question": item["question"],
                "sql": item["sql"],
            },
            vector=vector,
        )
        log.info("Inserted SQL example: %s", item["question"][:60])

    log.info("Done — inserted %d SQL examples.", len(queries))


def main() -> None:
    log.info("Connecting to Weaviate at %s ...", WEAVIATE_URL)
    client = weaviate.connect_to_local(host="localhost", port=8080)

    try:
        log.info("Starting table schema ingestion...")
        ingest_tables(client)

        log.info("Starting SQL example ingestion...")
        ingest_queries(client)

        log.info("All data ingested successfully.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
