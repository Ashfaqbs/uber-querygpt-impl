"""
Column Prune Agent — removes irrelevant columns from table schemas.

Mirrors Uber V2: tables with 200+ columns consumed 40-60K tokens each,
blowing the LLM context window. This agent strips columns unrelated to
the user's question before building the final prompt.

This is an LLM call — it asks the model which columns are relevant,
then reconstructs a trimmed schema with only those columns.
"""

import logging
import re

import ollama

log = logging.getLogger(__name__)

# Use a smaller model here — column pruning is a simple "list relevant columns"
# task that does not need the full 8b model. This halves the latency of the
# generate endpoint since it runs before the SQL generation LLM call.
LLM_MODEL = "qwen3:4b"


def prune(question: str, table: dict) -> dict:
    """
    Given a user question and a full table schema, return a trimmed version
    containing only columns relevant to answering the question.
    """
    prompt = f"""You are a database schema optimizer.

User question: "{question}"

Full table schema:
{table['content']}

Your task: identify which columns from this table are needed to answer the question.
Reply with ONLY a comma-separated list of column names. Nothing else.
Example: trip_id,status,fare_amount,started_at"""

    response = ollama.generate(model=LLM_MODEL, prompt=prompt, options={"temperature": 0, "think": False})
    raw = response["response"].strip()

    relevant_columns = {col.strip() for col in raw.split(",") if col.strip()}
    log.info(
        "Column prune for table '%s': keeping %s",
        table["table_name"],
        relevant_columns,
    )

    pruned_content = _rebuild_schema(table["content"], table["table_name"], relevant_columns)

    return {
        "table_name": table["table_name"],
        "content": pruned_content,
        "workspace": table["workspace"],
    }


def _rebuild_schema(original_content: str, table_name: str, keep_columns: set[str]) -> str:
    """
    Rebuilds the schema text keeping only the specified columns.
    Falls back to original if parsing fails.
    """
    lines = original_content.split("\n")
    result = []
    in_columns_section = False

    for line in lines:
        if line.strip().startswith("Columns:"):
            in_columns_section = True
            result.append(line)
            continue

        if in_columns_section and line.strip().startswith("-"):
            # Extract column name from "  - column_name (TYPE): description"
            match = re.match(r"\s+-\s+(\w+)", line)
            if match:
                col_name = match.group(1)
                if col_name in keep_columns:
                    result.append(line)
            continue

        result.append(line)

    pruned = "\n".join(result)

    # Safety: if pruning removed everything, return original
    if "- " not in pruned:
        log.warning("Column pruning removed all columns for %s, using original.", table_name)
        return original_content

    return pruned


def run(question: str, tables: list[dict]) -> list[dict]:
    """
    Entry point for the column prune agent.
    Prunes each table schema and returns the trimmed list.
    """
    return [prune(question, table) for table in tables]
