# QueryGPT — Uber Article Implementation

This repo is a hands-on implementation of Uber's QueryGPT system, built to understand
how it works by actually building it rather than just reading about it.

## What is QueryGPT?

Uber's internal tool that lets non-engineers query their data warehouse using plain English.
Instead of writing SQL, an analyst types a question and the system writes the SQL for them.

The problem it solves: Uber's data platform handles 1.2 million queries per month.
Writing each query requires finding the right table, understanding the schema, then writing SQL.
That takes ~10 minutes per query on average. QueryGPT reduces it to ~3 minutes.

## How It Works

Three separate systems work together. The vector DB never touches your actual data rows.

```
Vector DB  →  finds the right schema (what tables/columns exist)
LLM        →  writes the SQL using that schema
Your DB    →  runs the SQL and returns the real answer
```

End to end:

```
User asks: "How many people went to Mumbai?"
              |
         embed question → [0.23, -0.87, ...]   (a list of floats = the meaning)
              |
         match against stored schema vectors in vector DB
              |
         finds: trips table schema (most similar meaning)
              |
         feeds schema to LLM
              |
         LLM writes: SELECT COUNT(*) FROM trips WHERE pickup_city = 'Mumbai';
              |
         YOU run that SQL against your real PostgreSQL
              |
         get the actual answer: 52
```

The LLM already knows SQL. What it does not know is your database. The vector DB
gives it that knowledge — not your data, just your structure (table names, columns,
what each table holds, how they relate).

## V1 vs V2

V1 is a single RAG pipeline. V2 is a multi-agent pipeline where each agent does one job,
and the human gets to intervene between steps.

**V1 flow — one shot, no review:**

```text
Question → embed → search ALL tables → top 3 schemas + 7 SQL examples → LLM → SQL
```

**V2 flow — 3 steps, human in the middle:**

```text
STEP 1 — Intent Agent
  Question → embed → search WorkspaceRegistry
  "how many trips were cancelled?" → classified as: mobility
  User can override if wrong.

STEP 2 — Table Agent
  Search ONLY mobility tables (not payments, not support, not users)
  Suggests: [trips, drivers]
  User reviews and edits → confirms: [trips]   ← human in the loop

STEP 3 — Generate
  Column Prune Agent: strips irrelevant columns from trips schema → smaller prompt
  SQL Generator: KNN on mobility SQL examples only → top 7 examples
  Builds prompt → LLM → SQL + explanation
```

**The 4 problems V1 had and how V2 fixes them:**

| Problem in V1 | V2 fix |
|---|---|
| All tables in one flat bucket — wrong tables returned | Workspaces — search only the right domain |
| Full schema floods LLM context window | Column Prune Agent strips irrelevant columns first |
| Hallucinated columns go straight to user | Human confirms tables before SQL is generated |
| Vague questions give bad retrieval | Intent step narrows search space before KNN runs |

## What This Repo Contains

Two implementations, matching Uber's two versions described in their engineering blog:

| Folder | What it is |
|---|---|
| `v1/` | Uber's hackathon prototype — simple RAG, flat vector search, no agents |
| `v2/` | Uber's production system — multi-agent pipeline, workspace scoping, human-in-the-loop |

Both are fully working implementations using local models (no OpenAI API needed).

## Reference

Uber Engineering Blog: [QueryGPT — Natural Language to SQL Using Generative AI](https://www.uber.com/en-IN/blog/query-gpt/)
