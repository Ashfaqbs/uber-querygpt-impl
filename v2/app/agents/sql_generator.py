"""
SQL Generator — final step in the V2 pipeline.

Takes the pruned table schemas + retrieved SQL examples from the workspace
and generates SQL with an explanation. Mirrors Uber V2's final LLM call.
"""

import logging

import ollama
import weaviate

from app.core.embeddings import embed

log = logging.getLogger(__name__)

LLM_MODEL = "qwen3:4b"
SQL_EXAMPLES_K = 7

SYSTEM_INSTRUCTIONS = """You are a SQL query assistant. Follow these rules strictly:
- Only use the tables and columns provided in the schema context below.
- Do not invent or guess table names or column names.
- Use TIMESTAMPTZ-aware date functions (e.g. DATE_TRUNC, CURRENT_DATE, INTERVAL).
- Always alias aggregated columns clearly.
- Return a valid SQL query followed by a plain-English explanation of what the query does.

Format your response exactly as:
SQL:
<the sql query>

EXPLANATION:
<plain english explanation>"""


def retrieve_sql_examples(
    client: weaviate.WeaviateClient, question: str, workspaces: list[str]
) -> list[dict]:
    query_vector = embed(question)
    collection = client.collections.get("WorkspaceSqlExample")

    results = collection.query.near_vector(
        near_vector=query_vector,
        limit=SQL_EXAMPLES_K,
        filters=weaviate.classes.query.Filter.by_property("workspace").contains_any(workspaces),
        return_properties=["question", "sql", "workspace"],
    )

    examples = [
        {"question": obj.properties["question"], "sql": obj.properties["sql"]}
        for obj in results.objects
    ]
    log.info("Retrieved %d SQL examples from workspaces %s", len(examples), workspaces)
    return examples


def build_prompt(
    question: str,
    pruned_tables: list[dict],
    sql_examples: list[dict],
) -> str:
    schema_block = "\n\n".join(t["content"] for t in pruned_tables)

    examples_block = "\n\n".join(
        f"Question: {ex['question']}\nSQL:\n{ex['sql']}"
        for ex in sql_examples
    )

    return f"""{SYSTEM_INSTRUCTIONS}

--- TABLE SCHEMAS ---
{schema_block}

--- SQL EXAMPLES ---
{examples_block}

--- USER QUESTION ---
{question}"""


def run(
    client: weaviate.WeaviateClient,
    question: str,
    workspaces: list[str],
    pruned_tables: list[dict],
) -> dict:
    """
    Entry point for the SQL generator.
    Returns a dict with 'sql' and 'explanation' keys.
    """
    sql_examples = retrieve_sql_examples(client, question, workspaces)
    prompt = build_prompt(question, pruned_tables, sql_examples)

    log.info("Calling LLM to generate SQL...")
    response = ollama.generate(model=LLM_MODEL, prompt=prompt, options={"temperature": 0, "think": False})
    raw_output = response["response"].strip()

    return parse_output(raw_output)


def parse_output(raw: str) -> dict:
    sql = ""
    explanation = ""

    if "SQL:" in raw and "EXPLANATION:" in raw:
        parts = raw.split("EXPLANATION:")
        sql_part = parts[0].replace("SQL:", "").strip()
        explanation = parts[1].strip()
        sql = sql_part
    else:
        # fallback: return raw as sql
        sql = raw
        explanation = "Could not parse explanation separately."

    return {"sql": sql, "explanation": explanation}
