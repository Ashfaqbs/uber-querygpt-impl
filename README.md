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

## What This Repo Contains

Two implementations, matching Uber's two versions described in their engineering blog:

| Folder | What it is |
|---|---|
| `v1/` | Uber's hackathon prototype — simple RAG, flat vector search, no agents |
| `v2/` | Uber's production system — multi-agent pipeline, workspace scoping, human-in-the-loop |

Both are fully working implementations using local models (no OpenAI API needed).

## Reference

Uber Engineering Blog: [QueryGPT — Natural Language to SQL Using Generative AI](https://www.uber.com/en-IN/blog/query-gpt/)
