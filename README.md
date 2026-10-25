# WhyCode

WhyCode answers "why is the code like this?" for a real codebase, with evidence on every answer.
It ingests a repository's commits, pull request discussions and issues, builds a Neo4j graph that
links code entities to the decisions, people and incidents behind them, and answers questions with
a chain of evidence: the decision, the discussion that produced it, the person to ask, and the date.

The graph holds the answer; the LLM only words it. When the graph has no answer, WhyCode says so.

Team AXIOM, hackFront India 2026 ("AI and Developer Tools").

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker (for local Postgres and the Neo4j test container)
- A Neo4j AuraDB instance, a GitHub token, Gemini and Groq API keys

## Setup

```sh
uv sync                       # creates .venv with Python 3.12 and installs everything
cp .env.example .env          # then fill in every value; never commit .env
docker compose up -d          # Postgres 16 (raw cache) + Neo4j 5 (integration tests only)
```

Configuration is read by `whycode/config.py`. A missing or invalid variable stops the program with a
message that names the variable and never prints any value.

The free Aura instance pauses when idle. If Neo4j checks fail, resume it in the Aura console.

## Tests

```sh
uv run pytest                     # unit tests only (default): no network, no databases
uv run pytest -m integration      # needs `docker compose up -d`; uses repo "test/fixture" only
uv run pytest -m live             # real GitHub + LLM calls; costs API calls; never in CI
uv run pytest --cov=whycode       # with coverage
uv run ruff check .
```

## Layout

```
whycode/
  config.py        settings from .env
  ids.py           make_id(repo, kind, key) -> "psf/requests#pr:1565"
  ingest/          GitHub fetch -> Postgres raw cache
  graph/           Neo4j driver wrapper, schema runner, MERGE-only writers
    schema.cypher  the graph contract (source of truth)
  extract/         LLM decision extraction (prompt + pydantic models)
  llm/             llm_client: Gemini/Groq, cache, call budget, retries
  agent/ api/      later phases
tests/  unit/  integration/  e2e/  fixtures/
scripts/
```

Every node carries a `repo` property and every id is prefixed with the repo, so several repositories
can live in one graph without colliding.
