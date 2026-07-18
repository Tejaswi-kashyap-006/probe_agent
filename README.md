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
| M1 target API, all three variants, identifiability | done |
| M2 client + probe budget + LLM token ceiling | done |
| M3 contract scoring | done |
| M4 random + ReAct baselines, counter-prior check | done |
| M5 factored hypothesis machinery + safety tests | done |
| M6 EIG agent | done |
| M7 experiment matrix | **partial** — 1 variant, 1 seed; full matrix not run |
| M8 visualisations | done |

```bash
python -m pytest                                    # 56 tests
python scripts/run_experiment.py --agent eig --variant easy --budget 100
python scripts/make_figures.py --variant easy
```

Runs are cached by prompt, so re-running an experiment costs nothing and
reproduces the same numbers.

**Current finding is negative.** At one seed on the easy variant the EIG agent
comes last, below a random baseline. The ablation that keeps hypothesis tracking
but drops EIG selection is the only arm to score on counter-prior rules. See
[docs/RESULTS.md](docs/RESULTS.md) — it is one sample and settles nothing, but it
is not being tuned away.

`CLAUDE.md` is the build spec. [docs/METHOD.md](docs/METHOD.md) explains the three
ideas the implementation expresses.
