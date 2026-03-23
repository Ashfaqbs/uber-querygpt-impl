"""
query.py — Runtime query pipeline.

Uber V1 equivalent: the online RAG pipeline that runs on every user question.

Full flow (matches Uber V1 exactly):
  1. Embed the user's question                        (vectorize input)
  2. KNN search → top 3 table schemas                (k=3, as Uber specified)
  3. KNN search → top 7 SQL examples                 (k=7, as Uber specified)
  4. Build prompt: custom instructions + schemas + examples + question
  5. LLM generates SQL + plain-English explanation

Run ingest.py first to populate Weaviate before using this.
"""

import logging

import ollama
import weaviate

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "qwen3:8b"
WEAVIATE_URL = "http://localhost:8080"

# Uber V1: "custom business instructions" baked into the prompt.
# This is where domain-specific rules go — how to handle dates, which
# columns to use for time filtering, output format expectations.
# Uber used this to encode internal Uber data conventions.
CUSTOM_INSTRUCTIONS = """You are a SQL query assistant for an internal data platform.
Rules:
- Only use the tables and columns listed in the schema context below. Do not invent columns.
- Use TIMESTAMPTZ-aware date functions: DATE_TRUNC, CURRENT_DATE, INTERVAL.
- For date ranges use: started_at, ended_at, created_at, paid_at, joined_at columns.
- Always alias aggregated columns (e.g. COUNT(*) AS total_trips).
- Return a valid SQL query followed by a plain-English explanation.

Format your response exactly as:
SQL:
<the sql query>

EXPLANATION:
<plain english explanation>"""


def embed(text: str) -> list[float]:
    """
    Convert text to a 768-float vector using nomic-embed-text.
    Must be the same model used in ingest.py — both sides of the
    vector space must match for KNN similarity to be meaningful.
    """
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response["embedding"]


def retrieve(client: weaviate.WeaviateClient, question: str) -> tuple[list[dict], list[dict]]:
    """
    Uber V1: "similarity search — retrieve 3 tables + 7 SQL samples"

    Embed the question, then run KNN search against both Weaviate collections.
    near_vector = find the stored vectors closest to the query vector.
    limit=3 and limit=7 are the exact K values Uber used in V1.

    Limitation Uber identified: searching a flat space with no domain scoping
    means loosely related tables can surface (e.g. payments table appearing
    for a trips question). V2 fixes this with workspace/domain classification.
    """
    query_vector = embed(question)

    # KNN search: top 3 most semantically similar table schemas
    tables_result = client.collections.get("TableSchema").query.near_vector(
        near_vector=query_vector,
        limit=3,
        return_properties=["table_name", "content"],
    )

    # KNN search: top 7 most semantically similar SQL examples
    examples_result = client.collections.get("SqlExample").query.near_vector(
        near_vector=query_vector,
        limit=7,
        return_properties=["question", "sql"],
    )

    tables = [{"table_name": o.properties["table_name"], "content": o.properties["content"]}
              for o in tables_result.objects]
    examples = [{"question": o.properties["question"], "sql": o.properties["sql"]}
                for o in examples_result.objects]

    log.info("Retrieved tables: %s", [t["table_name"] for t in tables])
    log.info("Retrieved %d SQL examples", len(examples))
    return tables, examples


def build_prompt(question: str, tables: list[dict], examples: list[dict]) -> str:
    """
    Uber V1: "construct prompt with schemas, samples, and custom instructions"

    Assembles the full context the LLM will see:
      - CUSTOM_INSTRUCTIONS: business rules and output format
      - TABLE SCHEMAS: the 3 retrieved schemas so LLM knows what columns exist
      - SQL EXAMPLES: the 7 retrieved examples as few-shot demonstrations
      - USER QUESTION: the actual question to answer

    The LLM never touches the real database. It only sees this text and
    uses it to write a SQL query that would work against the real schema.
    """
    schema_block = "\n\n".join(t["content"] for t in tables)
    examples_block = "\n\n".join(
        f"Question: {ex['question']}\nSQL:\n{ex['sql']}" for ex in examples
    )
    return f"""{CUSTOM_INSTRUCTIONS}

--- TABLE SCHEMAS ---
{schema_block}

--- SQL EXAMPLES ---
{examples_block}

--- USER QUESTION ---
{question}"""


def parse_output(raw: str) -> dict:
    """
    Extract SQL and explanation from the LLM response.
    Uber V1: "LLM returns SQL query + explanation" — two distinct outputs.
    """
    if "SQL:" in raw and "EXPLANATION:" in raw:
        parts = raw.split("EXPLANATION:")
        sql = parts[0].replace("SQL:", "").strip()
        explanation = parts[1].strip()
    else:
        sql = raw
        explanation = "Could not parse explanation separately."
    return {"sql": sql, "explanation": explanation}


def query(question: str) -> dict:
    """
    Main entry point. Runs the full V1 pipeline for a given question.
    Returns question, tables used, generated SQL, and explanation.
    """
    client = weaviate.connect_to_local(host="localhost", port=8080)
    try:
        # Steps 1-3: embed + KNN retrieval
        tables, examples = retrieve(client, question)

        # Step 4: build the prompt with all context
        prompt = build_prompt(question, tables, examples)

        # Step 5: LLM generates SQL + explanation
        log.info("Calling LLM...")
        response = ollama.generate(model=LLM_MODEL, prompt=prompt, options={"temperature": 0})
        result = parse_output(response["response"].strip())

        return {
            "question": question,
            "tables_used": [t["table_name"] for t in tables],
            "sql": result["sql"],
            "explanation": result["explanation"],
        }
    finally:
        client.close()


if __name__ == "__main__":
    import sys
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "How many trips were completed in each city?"
    result = query(question)
    print("\n=== QUESTION ===")
    print(result["question"])
    print("\n=== TABLES USED ===")
    print(", ".join(result["tables_used"]))
    print("\n=== GENERATED SQL ===")
    print(result["sql"])
    print("\n=== EXPLANATION ===")
    print(result["explanation"])
