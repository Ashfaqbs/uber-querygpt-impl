import json
import logging
from pathlib import Path

import weaviate

from app.core.embeddings import embed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


def ingest_workspaces(client: weaviate.WeaviateClient) -> None:
    workspaces = json.loads((DATA_DIR / "workspaces.json").read_text())
    collection = client.collections.get("WorkspaceRegistry")

    for ws in workspaces:
        # Embed the description — intent agent uses this for vector classification
        vector = embed(ws["description"])
        collection.data.insert(
            properties={
                "workspace": ws["workspace"],
                "description": ws["description"],
                "tables": ws["tables"],
            },
            vector=vector,
        )
        log.info("Inserted workspace: %s", ws["workspace"])

    log.info("Done — inserted %d workspaces.", len(workspaces))


def ingest_tables(client: weaviate.WeaviateClient) -> None:
    tables = json.loads((DATA_DIR / "tables.json").read_text())
    collection = client.collections.get("WorkspaceTable")

    for table in tables:
        vector = embed(table["content"])
        collection.data.insert(
            properties={
                "table_name": table["table_name"],
                "content": table["content"],
                "workspace": table["workspace"],
            },
            vector=vector,
        )
        log.info("Inserted table: %s (workspace: %s)", table["table_name"], table["workspace"])

    log.info("Done — inserted %d tables.", len(tables))


def ingest_queries(client: weaviate.WeaviateClient) -> None:
    queries = json.loads((DATA_DIR / "queries.json").read_text())
    collection = client.collections.get("WorkspaceSqlExample")

    for item in queries:
        text = f"Question: {item['question']}\nSQL: {item['sql']}"
        vector = embed(text)
        collection.data.insert(
            properties={
                "question": item["question"],
                "sql": item["sql"],
                "workspace": item["workspace"],
            },
            vector=vector,
        )
        log.info("Inserted SQL example (workspace: %s): %s", item["workspace"], item["question"][:55])

    log.info("Done — inserted %d SQL examples.", len(queries))


def main() -> None:
    log.info("Connecting to Weaviate...")
    client = weaviate.connect_to_local(host="localhost", port=8081, grpc_port=50052)

    try:
        log.info("Ingesting workspaces...")
        ingest_workspaces(client)

        log.info("Ingesting table schemas...")
        ingest_tables(client)

        log.info("Ingesting SQL examples...")
        ingest_queries(client)

        log.info("All data ingested successfully.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
