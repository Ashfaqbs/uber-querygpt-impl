# QueryGPT V2

Implementation of Uber's V2 (production system) of QueryGPT.

---

## Background — Why V2 Exists

V1 worked but broke down at scale. Uber ran V1 in production and observed four problems:

1. Flat vector search returned wrong tables when all domains were mixed together
2. Large schemas consumed the entire LLM context window
3. No human review before SQL was generated — hallucinated columns went straight to users
4. Short or vague user questions ("show me trips data") gave poor retrieval results

V2 is the architectural response to all four problems. Read the V1 README first if you
have not already — V2 only makes sense in contrast to V1.

---

## The Problem Being Solved

Same as V1 — non-engineers typing questions in English and getting SQL back.
The difference is how accurately and reliably that happens at scale.

In Uber's case: 1.2 million queries per month, across multiple business domains
(Mobility, Payments, Ads, Support, etc.), with tables having 200+ columns each.
V1's simple approach could not handle that reliably. V2 was built to.

---

## What V2 Is

V2 is a multi-agent pipeline with workspace-scoped retrieval and human-in-the-loop
table confirmation before any SQL is generated.

Instead of one flow doing everything, V2 breaks the problem into specialized agents,
each doing one focused job. This is the key architectural insight Uber identified:

"Specialized agents outperform a single generalist prompt."

---

## How the Article Describes V2

From Uber's blog:

- Intent Agent: maps user question to a business domain (workspace)
- Table Agent: finds relevant tables within that workspace, shows them to user for confirmation
- Column Prune Agent: removes irrelevant columns from large schemas to manage token budget
- Workspaces: curated collections of tables + SQL examples organized by business domain
- Human-in-the-loop: user confirms or edits table selection before SQL is generated
- LLM used in production: GPT-4 Turbo (128K context). We use qwen3:8b locally.

---

## How V2 Differs from V1

| Aspect | V1 | V2 |
| --- | --- | --- |
| Vector space | One flat bucket for all tables | Separate workspaces per business domain |
| Retrieval | Search everything | Classify domain first, then search within it |
| Table selection | Auto, no review | Suggested to user, user confirms or edits |
| Schema size | Full schema goes to LLM | Column prune agent strips irrelevant columns first |
| API | Single Python script | REST API with 3 endpoints matching the agent steps |
| Human review | None | At intent step and table selection step |

---

## The Core Concept: Workspaces

This is the most important V2 addition. A workspace is a domain-specific bucket that
groups related tables and SQL examples together.

```text
workspace: mobility
  tables:  trips, drivers
  queries: trip counts, fare averages, driver performance...

workspace: payments
  tables:  payments, promotions
  queries: revenue, refunds, payment methods...

workspace: users
  tables:  users
  queries: signups, inactive users, top users...

workspace: support
  tables:  support_tickets
  queries: open tickets, critical issues, resolution times...

workspace: quality
  tables:  ratings
  queries: driver ratings by city, average scores...
```

Why this matters: when a user asks "how many trips were cancelled?", the intent agent
classifies it as a mobility question. The search then only runs against mobility tables
and examples — not payments, not support. This dramatically improves retrieval accuracy
because the search space is narrowed before KNN runs.

V1 searched everything. V2 searches the right bucket.

---

## The Agent Pipeline

V2 has four agents that run in sequence. Each agent has one job.

### Agent 1 — Intent Agent

**Job:** Figure out which workspace the question belongs to.

**How:** Embeds the question, runs KNN against the WorkspaceRegistry collection
(which holds workspace descriptions as vectors). Returns the top matching workspaces.

**Why it exists:** Without this, you are back to V1 — searching everything.
Knowing the domain first narrows the search radius for the next two agents.

```text
Input:  "how many trips were cancelled last week?"
Output: ["mobility"]
```

### Agent 2 — Table Agent

**Job:** Find the most relevant tables within the detected workspace(s).

**How:** KNN search within WorkspaceTable collection filtered to the detected workspace.
Returns top 3 candidate tables. Presents them to the user.

**Why it exists:** Even within a workspace, not every table is needed. A question about
trip counts does not need the drivers table. Surfacing candidates for user review rather
than blindly feeding everything to the LLM reduces noise.

```text
Input:  question + ["mobility"]
Output: suggested tables → [trips, drivers]   ← shown to user
```

### Agent 3 — Human in the Loop

**Job:** User reviews the suggested tables and confirms or edits them.

**How:** The `/query/tables` endpoint returns the suggestions. The user calls
`/query/generate` with their confirmed list. They can remove tables or change the selection.

**Why it exists:** Uber built this intentionally — not as a workaround. Letting the user
verify table selection before SQL is generated catches wrong retrievals early, before
an incorrect SQL is produced and confuses the user.

```text
Suggested: [trips, drivers, ratings]
User edits: [trips]           ← user removes drivers and ratings, not needed
Confirmed: [trips]
```

### Agent 4 — Column Prune Agent

**Job:** Strip irrelevant columns from the confirmed table schemas before building the prompt.

**How:** Calls the LLM with the question + full schema. Asks which columns are relevant.
Rebuilds the schema text with only those columns.

**Why it exists:** At Uber's scale, one table could have 200+ columns consuming 40-60K tokens.
A question about trip counts does not need `driver_id`, `distance_km`, `ended_at` etc.
Pruning keeps the prompt lean, reduces LLM cost, and avoids context window overflow.

```text
Full trips schema: 10 columns
Question: "how many trips per city?"
After pruning: pickup_city, status    ← only what is needed
```

### Final Step — SQL Generator

**Job:** Retrieve SQL examples from the workspace, build the prompt, call the LLM.

**How:** KNN search against WorkspaceSqlExample filtered to the confirmed workspace(s),
get top 7 examples, combine with pruned schemas and custom instructions, call qwen3:8b.

```text
Input:  pruned schemas + 7 SQL examples + question
Output: SQL query + explanation
```

---

## The Full Flow End to End

```text
User: "how many trips were cancelled last week?"
         |
         v
POST /query/intent
  Intent Agent: embed question → KNN on WorkspaceRegistry
  Result: ["mobility"]
  ← user sees this, can override if wrong
         |
         v
POST /query/tables
  Table Agent: KNN on WorkspaceTable filtered to mobility
  Result: suggested [trips, drivers]
  ← user reviews, edits if needed
         |
         v
POST /query/generate  (user sends confirmed_tables: ["trips"])
  Column Prune Agent: ask LLM which columns from trips are needed
    → keeps: status, started_at
  SQL Generator: KNN on WorkspaceSqlExample filtered to mobility
    → retrieves 7 similar SQL examples
  Builds prompt: instructions + pruned schema + 7 examples + question
  Calls qwen3:8b
  Result:
    SQL:
    SELECT COUNT(*) AS cancelled_trips FROM trips
    WHERE status = 'cancelled'
    AND started_at >= CURRENT_DATE - INTERVAL '7 days';

    EXPLANATION:
    Counts trips with cancelled status in the last 7 days.
```

---

## Weaviate Collections (Three, not Two)

V2 adds a third collection compared to V1:

| Collection | What it stores | Used by |
| --- | --- | --- |
| WorkspaceRegistry | Workspace name + description | Intent Agent (classify domain) |
| WorkspaceTable | Table schemas tagged with workspace | Table Agent (find tables) |
| WorkspaceSqlExample | SQL examples tagged with workspace | SQL Generator (find examples) |

Every record in WorkspaceTable and WorkspaceSqlExample has a `workspace` field.
At search time, the filter `workspace IN ["mobility"]` ensures only relevant domain
records are searched — this is the workspace scoping.

Collections are created via `init/init_collections.sh` running as a Docker init
container hitting Weaviate's REST API with curl. Same pattern as V1.

---

## REST API Design

V2 exposes 3 endpoints, one per agent hand-off point. The split is intentional —
each endpoint is a place where the user can review and correct before proceeding.

```text
POST /query/intent
  Body:    { "question": "..." }
  Returns: { "question": "...", "workspaces": ["mobility"] }

POST /query/tables
  Body:    { "question": "...", "workspaces": ["mobility"] }
  Returns: { "suggested_tables": [{ "table_name": "trips", ... }] }

POST /query/generate
  Body:    { "question": "...", "workspaces": ["mobility"], "confirmed_tables": ["trips"] }
  Returns: { "sql": "SELECT ...", "explanation": "...", "tables_used": ["trips"] }
```

---

## What We Are Achieving with V2

V2 demonstrates that the accuracy problems of V1 are solvable by:

1. Narrowing the search space (workspaces) before retrieval
2. Letting users correct wrong retrievals before SQL is generated
3. Keeping the LLM prompt lean by pruning irrelevant columns

The result is a system that gives better SQL, is less likely to hallucinate wrong column
names (since it only sees relevant columns), and builds user trust through transparency
(user sees which tables will be used before generation).

---

## Tech Stack

| Component | Tool | Why |
| --- | --- | --- |
| Vector DB | Weaviate (Docker) | Same as V1, now on port 8081 |
| Embedding model | nomic-embed-text via Ollama | Same as V1 |
| LLM | qwen3:8b via Ollama | Uber used GPT-4 Turbo; qwen3:8b is the local equivalent |
| API | FastAPI | Async, clean endpoint-per-agent design |

---

## Project Structure

```text
v2/
  docker-compose.yml         # Weaviate on port 8081 + init container
  requirements.txt           # Python dependencies
  init/
    init_collections.sh      # Creates 3 collections: WorkspaceRegistry, WorkspaceTable, WorkspaceSqlExample
  data/
    workspaces.json          # 5 workspace definitions with descriptions
    tables.json              # 7 tables, each tagged with a workspace
    queries.json             # 20 SQL examples, each tagged with a workspace
  app/
    main.py                  # FastAPI app — 3 endpoints
    ingest.py                # Embed and store workspaces + tables + queries
    core/
      embeddings.py          # nomic-embed-text wrapper
    agents/
      intent_agent.py        # Classifies question into workspace(s)
      table_agent.py         # Finds tables, handles user confirmation
      column_prune_agent.py  # Strips irrelevant columns from schemas
      sql_generator.py       # Retrieves SQL examples + calls LLM
```

---

## How to Run

### Prerequisites

- Docker Desktop running
- Ollama running with models pulled:

```bash
ollama pull nomic-embed-text
ollama pull qwen3:8b
```

### Step 1 — Start Weaviate and create collections

```bash
cd v2
docker compose up -d
```

Creates `WorkspaceRegistry`, `WorkspaceTable`, and `WorkspaceSqlExample` collections.

### Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Ingest the knowledge base (run once)

```bash
python -m app.ingest
```

Embeds and stores 5 workspaces, 7 tables, and 20 SQL examples — all with workspace tags.

### Step 4 — Start the API

```bash
python -m uvicorn app.main:app --port 8001
```

### Step 5 — Use the pipeline

```bash
# Step 1: detect intent
curl -X POST http://localhost:8001/query/intent \
  -H "Content-Type: application/json" \
  -d '{"question": "how many trips were cancelled last week?"}'

# Step 2: get table suggestions
curl -X POST http://localhost:8001/query/tables \
  -H "Content-Type: application/json" \
  -d '{"question": "how many trips were cancelled last week?", "workspaces": ["mobility"]}'

# Step 3: confirm tables and generate SQL
curl -X POST http://localhost:8001/query/generate \
  -H "Content-Type: application/json" \
  -d '{"question": "how many trips were cancelled last week?", "workspaces": ["mobility"], "confirmed_tables": ["trips"]}'
```

---

## Reference

Uber Engineering Blog: [QueryGPT — Natural Language to SQL Using Generative AI](https://www.uber.com/en-IN/blog/query-gpt/)
