# Probe — an EIG-driven API discovery agent

An agent that reverse-engineers an undocumented HTTP API by experimentation. It
gets no docs, only the ability to send requests and read responses, and must
recover the contract: required and optional parameters, types, ranges, enum
domains, formats, cross-parameter dependencies, pagination, and error semantics.

Each probe is chosen by maximising expected information gain over an explicit
hypothesis space, rather than by poking around and hoping.

**Thesis under test:** does explicit hypothesis tracking plus information-theoretic
probe selection recover an API contract in materially fewer calls than an LLM
simply told to "explore this API"?

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
cp .env.example .env                              # then set OPENAI_API_KEY
```

## Run the target API

```bash
python scripts/serve.py --variant easy --port 8000
```

```bash
curl "127.0.0.1:8000/products?limit=100"
curl -X POST 127.0.0.1:8000/orders -H 'content-type: application/json' \
     -d '{"customer_id":"CUS-000123","quantity":2}'
```

## Identifiability ceiling

Some rules are unrecoverable under a variant that returns bare status codes: no
probe distinguishes a contract containing the rule from one where it is false.
Recovery is reported as a fraction of what is achievable, so the numbers measure
the agent rather than the problem.

```bash
python -m target_api.identifiability
```

Writes `artifacts/identifiability_<variant>.json`.

## Status

| Milestone | State |
|---|---|
| M1 target API, easy variant, identifiability | done |
| M2 client + probe budget | not started |
| M3 contract scoring | not started |
| M4 random + ReAct baselines | not started |
| M5 hypothesis machinery | not started |
| M6 EIG agent | not started |
| M7 experiment matrix | not started |
| M8 visualisations | not started |

`CLAUDE.md` is the build spec.
