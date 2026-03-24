"""
Table Agent — identifies relevant tables within the detected workspace(s).

Mirrors Uber V2: after the intent agent narrows to a workspace, the table agent
retrieves candidate tables and presents them to the user for confirmation or editing.
This human-in-the-loop step is intentional — it increases accuracy and builds trust.
"""

import logging

import weaviate

from app.core.embeddings import embed

log = logging.getLogger(__name__)


def find_tables(
    client: weaviate.WeaviateClient,
    question: str,
    workspaces: list[str],
    top_k: int = 3,
) -> list[dict]:
    """
    KNN search within the given workspace(s) to find relevant tables.
    Returns a list of table candidates with name and schema content.
    """
    query_vector = embed(question)
    collection = client.collections.get("WorkspaceTable")

    results = collection.query.near_vector(
        near_vector=query_vector,
        limit=top_k,
        filters=weaviate.classes.query.Filter.by_property("workspace").contains_any(workspaces),
        return_properties=["table_name", "content", "workspace"],
    )

    tables = [
        {
            "table_name": obj.properties["table_name"],
            "content": obj.properties["content"],
            "workspace": obj.properties["workspace"],
        }
        for obj in results.objects
    ]

    log.info(
        "Table agent found %d tables for workspaces %s: %s",
        len(tables),
        workspaces,
        [t["table_name"] for t in tables],
    )
    return tables


def run(
    client: weaviate.WeaviateClient,
    question: str,
    workspaces: list[str],
    confirmed_tables: list[str] | None = None,
) -> list[dict]:
    """
    Entry point for the table agent.

    If confirmed_tables is provided (user has already ACK'd or edited the selection),
    return only those tables from Weaviate by name.

    Otherwise, return the auto-selected candidates for the user to confirm.
    """
    if confirmed_tables:
        collection = client.collections.get("WorkspaceTable")
        result = collection.query.fetch_objects(
            filters=weaviate.classes.query.Filter.by_property("table_name").contains_any(
                confirmed_tables
            ),
            return_properties=["table_name", "content", "workspace"],
        )
        tables = [
            {
                "table_name": obj.properties["table_name"],
                "content": obj.properties["content"],
                "workspace": obj.properties["workspace"],
            }
            for obj in result.objects
        ]
        log.info("Table agent using user-confirmed tables: %s", confirmed_tables)
        return tables

    return find_tables(client, question, workspaces)
