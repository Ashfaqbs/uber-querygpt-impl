# QueryGPT V1

Implementation of Uber's V1 (hackathon prototype) of QueryGPT.

---

## Background — Why This Exists

This comes from Uber's engineering blog post on QueryGPT. Instead of just reading the article,
this is a working implementation of exactly what Uber described in V1 so you can run it,
break it, and understand it hands-on.

The article describes V1 as their hackathon prototype — the simplest possible approach that
proved the concept worked before they invested in a production system (V2).

---

## The Problem Being Solved

People at Uber who are not engineers need data every day. Questions like:

- "How many trips got cancelled in Mumbai last week?"
- "Which drivers have low ratings in Delhi?"
- "How much revenue came in from UPI payments this month?"

To answer any of these you need SQL. Most people don't know SQL. Before QueryGPT,
they would go ask a data engineer — slow, blocks both parties, does not scale at
1.2 million queries a month.

QueryGPT's answer: type the question in English, get SQL back.

---

## What V1 Is

V1 is a RAG (Retrieval-Augmented Generation) pipeline. No agents, no multi-step logic.
One flow, start to finish.

RAG means: instead of asking the LLM to know everything, you give it the relevant
information at the time it needs to answer. The LLM never touches your actual database —
it only sees the schema descriptions and example queries you feed it.

---

## How the Article Describes V1

From Uber's blog:

"We vectorize the user's natural language prompt and perform a similarity search
to retrieve relevant SQL samples and table schemas, which are then used in a
few-shot prompt to generate the SQL."

"7 tier-1 tables and 20 SQL queries as our sample dataset"

"k=3 for tables, k=7 for SQL samples"

"Custom instructions for date handling and internal conventions"

"LLM returns SQL query + explanation"

Everything in this implementation maps directly to those five points.

---

## How We Implemented It

### The Two Phases

#### Phase 1 — Offline Ingestion (done once)

You take your knowledge base — table schemas and example SQL queries — convert each one
into a vector using an embedding model, and store them in a vector database.

Think of it as building a searchable index of your data knowledge.

```text
tables.json (7 tables)    → embed each schema text → store in Weaviate [TableSchema]
queries.json (20 queries) → embed each Q+SQL text  → store in Weaviate [SqlExample]
```

#### Phase 2 — Online Query (runs every time a user asks a question)

When a user asks a question, you embed that question too, then search for the most
similar items in your index. Those items become the context you feed to the LLM.

```text
User question → embed → search Weaviate → get top 3 schemas + top 7 SQL examples
             → build prompt → LLM → SQL + explanation
```

---

### Mapping Article to Code

| What Uber's article says | Where it lives in our code |
| --- | --- |
| "Vectorize the user's prompt" | `query.py` → `embed(question)` |
| "Similarity search, k=3 for tables" | `query.py` → `near_vector(limit=3)` on TableSchema |
| "Similarity search, k=7 for SQL samples" | `query.py` → `near_vector(limit=7)` on SqlExample |
| "7 tier-1 tables" | `data/tables.json` — 7 table schemas |
| "20 SQL queries as sample dataset" | `data/queries.json` — 20 question+SQL pairs |
| "Custom instructions for date handling" | `query.py` → `CUSTOM_INSTRUCTIONS` constant |
| "LLM returns SQL + explanation" | `query.py` → `parse_output()` splits both |
| Vectorize + store schemas | `ingest.py` → `ingest_tables()` |
| Vectorize + store SQL examples | `ingest.py` → `ingest_queries()` |

---

### The Full Flow, Step by Step

```text
STEP 1 — User asks a question
  "how many trips were completed in each city?"

STEP 2 — Embed the question (query.py: embed())
  nomic-embed-text converts the question into 768 numbers
  [0.23, -0.87, 0.41, 0.12, ...]   ← this represents the meaning of the question

STEP 3 — KNN search in Weaviate (query.py: retrieve())
  Find the 3 stored table schema vectors closest to the question vector
    → trips schema, payments schema, drivers schema

  Find the 7 stored SQL example vectors closest to the question vector
    → "how many trips per city?", "what is avg fare per city?", etc.

STEP 4 — Build the prompt (query.py: build_prompt())
  Assemble everything the LLM needs to see:
    [custom instructions]         ← date handling rules, output format
    [3 retrieved table schemas]   ← so LLM knows what columns exist
    [7 retrieved SQL examples]    ← so LLM learns the correct query patterns
    [user's question]             ← what to actually answer

STEP 5 — LLM generates SQL (query.py: query())
  qwen3:8b reads the full prompt and writes:

    SQL:
    SELECT pickup_city, COUNT(*) AS total_trips
    FROM trips WHERE status = 'completed'
    GROUP BY pickup_city ORDER BY total_trips DESC;

    EXPLANATION:
    This query counts completed trips grouped by city...
```

---

### Why Embed Question + SQL Together in ingest.py?

In `ingest.py`, SQL examples are embedded as:

```text
"Question: how many trips per city?\nSQL: SELECT pickup_city, COUNT(*) ..."
```

Both together, not separately. Because the vector needs to capture the intent (question words)
AND the pattern (SQL structure). If you only embed the SQL, searching with a natural language
question would find a weak match. Combining them bridges the human-language to SQL-language gap.

---

### What is the Vector Database Doing?

Weaviate stores two things per record: the original text and its vector.

At search time, Weaviate computes the cosine similarity between the query vector and every
stored vector, then returns the top K closest ones.

Cosine similarity = how similar the direction of two vectors is in 768-dimensional space.
Texts with similar meaning will have vectors pointing in similar directions — so semantically
similar text surfaces even if the exact words do not match.

We created two collections before inserting anything:

- `TableSchema` — holds schema definitions
- `SqlExample` — holds question + SQL pairs

Collections are created via `init/init_collections.sh` which runs as a Docker init container
and hits Weaviate's REST API directly with curl. No Python needed for setup — Docker handles it.

---

## What We Are Achieving with V1

The goal is to prove the concept: given a small curated knowledge base (7 tables, 20 queries),
can we answer natural language questions with correct SQL using only local models, no external APIs?

The answer is yes. V1 works. The limitations show up when you scale it.

---

## Known Limitations (Same as Uber's V1)

### 1. No domain awareness

All 7 tables live in one flat vector space. If you ask "how many drivers have low ratings?",
the KNN search might return the `payments` table as one of the top 3 because it is loosely
related to drivers via trips. The LLM then gets misleading context.

### 2. Token budget risk

If your tables have 100+ columns, the schema text alone can consume most of the LLM's context
window before the question is even added. We kept columns lean here but it is a real problem
at Uber's scale (40-60K tokens per table).

### 3. No hallucination guard

The LLM can invent column names that do not exist. Nothing checks the output. Whatever is
generated goes straight to the user.

### 4. Weak matching for internal jargon

If real column names are `supply_uuid` or `shift_start_ts`, a user asking "how many drivers
went online?" will not match well — human words vs internal DB names have a large semantic gap.

These four limitations are exactly what drove Uber to build V2.

---

## Tech Stack

| Component | Tool | Why |
| --- | --- | --- |
| Vector DB | Weaviate (Docker) | Native KNN search, simple REST API, production-grade |
| Embedding model | nomic-embed-text via Ollama | Local, free, 768-dim vectors, good quality |
| LLM | qwen3:8b via Ollama | Local, strong at code/SQL generation |
| Collections setup | Shell script + curl in Docker | Weaviate collections created via REST before app starts |

---

## Project Structure

```text
v1/
  docker-compose.yml       # Weaviate on port 8080 + init container
  requirements.txt         # Python dependencies
  init/
    init_collections.sh    # Creates TableSchema + SqlExample collections via curl
  data/
    tables.json            # 7 table schema definitions (the knowledge base)
    queries.json           # 20 example question + SQL pairs (the knowledge base)
  app/
    ingest.py              # Phase 1: embed knowledge base + store in Weaviate
    query.py               # Phase 2: embed question + KNN search + LLM call
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
cd v1
docker compose up -d
```

The `weaviate-init` container runs `init/init_collections.sh` automatically,
which creates the `TableSchema` and `SqlExample` collections via Weaviate's REST API.

### Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Ingest the knowledge base (run once)

```bash
python app/ingest.py
```

Embeds all 7 table schemas and 20 SQL examples, stores them in Weaviate.

### Step 4 — Ask questions

```bash
python app/query.py "How many trips were completed in each city?"
python app/query.py "Which drivers have a rating below 4?"
python app/query.py "What is the total refund amount this year by payment method?"
python app/query.py "How many users have not logged in for 90 days?"
```

---

## Reference

Uber Engineering Blog: [QueryGPT — Natural Language to SQL Using Generative AI](https://www.uber.com/en-IN/blog/query-gpt/)
