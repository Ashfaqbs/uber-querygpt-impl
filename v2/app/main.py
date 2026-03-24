"""
QueryGPT V2 — FastAPI application.

Full pipeline mirrors Uber V2:
  POST /query/intent        → Step 1: intent agent classifies question to workspace(s)
  POST /query/tables        → Step 2: table agent finds candidate tables
  POST /query/confirm       → Step 3: user confirms/edits table selection (human-in-loop)
  POST /query/generate      → Step 4: column prune + SQL generation

The split into separate endpoints mirrors the human-in-the-loop design:
user sees intent + tables before SQL is generated, and can correct either.
"""

import logging

import weaviate
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.agents import intent_agent, table_agent, column_prune_agent, sql_generator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="QueryGPT V2", version="2.0.0")

_client: weaviate.WeaviateClient | None = None


def get_client() -> weaviate.WeaviateClient:
    global _client
    if _client is None:
        _client = weaviate.connect_to_local(host="localhost", port=8081, grpc_port=50052)
    return _client


@app.on_event("shutdown")
def shutdown() -> None:
    if _client:
        _client.close()


# --- Request/Response models ---

class QuestionRequest(BaseModel):
    question: str

class IntentResponse(BaseModel):
    question: str
    workspaces: list[str]

class TablesRequest(BaseModel):
    question: str
    workspaces: list[str]

class TableCandidate(BaseModel):
    table_name: str
    workspace: str
    content: str

class TablesResponse(BaseModel):
    question: str
    workspaces: list[str]
    suggested_tables: list[TableCandidate]

class ConfirmRequest(BaseModel):
    question: str
    workspaces: list[str]
    confirmed_tables: list[str]   # user confirms or edits this list

class GenerateResponse(BaseModel):
    question: str
    sql: str
    explanation: str
    tables_used: list[str]


# --- Endpoints ---

@app.post("/query/intent", response_model=IntentResponse)
def detect_intent(req: QuestionRequest):
    """
    Step 1 — Intent Agent.
    Classifies the question into relevant workspace(s).
    Returns workspaces for user to review before table selection.
    """
    client = get_client()
    workspaces = intent_agent.run(client, req.question)

    if not workspaces:
        raise HTTPException(status_code=422, detail="Could not map question to any workspace.")

    return IntentResponse(question=req.question, workspaces=workspaces)


@app.post("/query/tables", response_model=TablesResponse)
def suggest_tables(req: TablesRequest):
    """
    Step 2 — Table Agent.
    Finds candidate tables within the detected workspace(s).
    Returns suggestions for user to confirm or edit (human-in-the-loop).
    """
    client = get_client()
    tables = table_agent.run(client, req.question, req.workspaces)

    if not tables:
        raise HTTPException(status_code=422, detail="No tables found for the given workspaces.")

    return TablesResponse(
        question=req.question,
        workspaces=req.workspaces,
        suggested_tables=[TableCandidate(**t) for t in tables],
    )


@app.post("/query/generate", response_model=GenerateResponse)
def generate_sql(req: ConfirmRequest):
    """
    Step 3+4 — Column Prune Agent + SQL Generator.
    User has confirmed (or edited) the table list.
    Prunes columns, retrieves SQL examples, generates SQL.
    """
    client = get_client()

    # Fetch confirmed tables by name
    tables = table_agent.run(
        client, req.question, req.workspaces, confirmed_tables=req.confirmed_tables
    )

    if not tables:
        raise HTTPException(status_code=422, detail="None of the confirmed tables were found.")

    # Column prune agent — strips irrelevant columns before prompt construction
    pruned_tables = column_prune_agent.run(req.question, tables)

    # SQL generator — retrieves examples + calls LLM
    result = sql_generator.run(client, req.question, req.workspaces, pruned_tables)

    return GenerateResponse(
        question=req.question,
        sql=result["sql"],
        explanation=result["explanation"],
        tables_used=req.confirmed_tables,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
