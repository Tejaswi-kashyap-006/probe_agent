# CLAUDE.md
CLAUDE.md — Probe: an EIG-driven API discovery agent


Build spec for Claude Code. Read fully before writing code.
Work milestone by milestone. Commit after each. Rename this file to CLAUDE.md at the repo root.




0. Project

Build an agent that reverse-engineers an undocumented HTTP API by experimentation. It gets no docs — only the ability to send requests and observe responses. It must recover the contract: required vs optional parameters, types, value constraints, enum domains, inter-parameter dependencies, pagination, and error semantics.

The agent selects each probe by maximizing expected information gain over an explicit hypothesis space, rather than poking around and hoping.

Thesis under test: does explicit hypothesis tracking plus information-theoretic probe selection recover an API contract in materially fewer calls than an LLM simply told to "explore this API"?

Runs entirely on API calls — no GPU, no local model, no training. It can run alongside a long GPU job on the same machine.


1. Theoretical foundation — read this before designing anything

Three ideas combine here. Claude Code should understand all three, because the implementation is a direct expression of them.

1.1 The Minimally Adequate Teacher (Angluin, 1987)

Classical active automata learning frames black-box inference around two query types:


Membership query — "does the system accept this input?" Cheap. Here: send an HTTP request, observe the response.
Equivalence query — "is my hypothesised model the true model?" In a real black-box setting no such oracle exists. It must be approximated by conformance testing — generating inputs where the hypothesis is most likely to be wrong.


This asymmetry is the project's central insight. Membership queries are free (the API answers them). The hard part — and the part an LLM is uniquely good at — is approximating the equivalence oracle: guessing where your own model of the world is most likely to break. Classical learners must enumerate; an LLM has priors about how APIs usually behave and can jump straight to the suspicious cases.

1.2 Expected Information Gain (Lindley, 1956)

For a latent variable θ (the true contract) and a candidate experiment ξ (a probe):

IG_θ(ξ, y) = H[p(θ)] − H[p(θ | y, ξ)]
EIG_θ(ξ)   = E_{p(y|ξ)}[ IG_θ(ξ, y) ]

Pick the probe maximizing EIG. Apple's BED-LLM (arXiv:2508.21184) applies exactly this to LLM question-asking and more than doubles success rate over prompt-only baselines on 20 Questions. We apply it to a system contract instead of a conversation.

1.3 The simplification that makes it cheap

Represent the posterior as a weighted particle set: K candidate contracts proposed by the LLM. If each hypothesis makes a deterministic prediction about a probe's outcome, then EIG collapses into something trivial to compute:


A probe partitions the hypothesis set by predicted outcome. EIG is the entropy of that partition. The best probe splits the surviving hypotheses most evenly — a binary search through contract space.



This is the classical version space splitting criterion, and it means no nested Monte Carlo and no LLM call per hypothesis per probe. That's the difference between a project that runs in minutes and one that costs $200.

To get deterministic predictions cheaply, hypotheses must be executable. The LLM emits each candidate contract as code, not prose (see §4).


2. Repository structure

probe/
├── README.md
├── CLAUDE.md
├── pyproject.toml
├── .env.example                  # OPENAI_API_KEY=
├── .gitignore
├── docs/
│   ├── METHOD.md                 # the three ideas above, in your own words
│   └── RESULTS.md                # written at M7
├── artifacts/                    # computed ground-truth facts (committed)
│   ├── identifiability_*.json    # per-variant achievable_rules + ceiling (§3.2)
│   └── referee_*.json            # frozen referee hypothesis sets (§6.1)
├── target_api/
│   ├── server.py                 # FastAPI app — the system under learning
│   ├── contract.py               # GROUND TRUTH rule set. Agent NEVER sees this.
│   ├── identifiability.py        # GROUND TRUTH. Analytic ceiling (§3.2).
│   └── variants/                 # easy.py, medium.py, hard.py
├── src/probe/
│   ├── config.py
│   ├── client.py                 # HTTP client + probe budget counter + call log
│   ├── llm.py                    # LLM calls: token ceiling, counting, cache (§5.1)
│   ├── hypothesis/
│   │   ├── space.py              # HypothesisSet: particles + weights
│   │   ├── propose.py            # LLM -> K executable candidate contracts
│   │   └── predicate.py          # safe execution of hypothesis code
│   ├── eig/
│   │   ├── scoring.py            # partition entropy == EIG
│   │   └── candidates.py         # LLM proposes candidate PROBES to score
│   ├── agents/
│   │   ├── base.py               # shared interface: .run(budget) -> Trace
│   │   ├── random_agent.py       # baseline 1
│   │   ├── react_agent.py        # baseline 2: "explore this API"
│   │   ├── hypothesis_agent.py   # ablation: hypotheses, no EIG selection
│   │   └── eig_agent.py          # THE METHOD
│   ├── eval/
│   │   ├── scoring.py            # recovered rules vs ground truth -> P/R/F1
│   │   └── runner.py             # runs all agents x variants x seeds
│   └── viz/
│       ├── trace_export.py       # JSONL trace -> viz-ready JSON
│       ├── declassify.py         # HERO: redaction race (HTML/JS)
│       ├── swarm.py              # hypothesis swarm collapse (HTML/JS)
│       ├── partition.py          # single-probe EIG split (SVG)
│       ├── tape.py               # probe filmstrip (SVG)
│       └── recovery_curve.py     # supporting chart
├── scripts/
│   ├── serve.py                  # start target API
│   ├── run_experiment.py         # --agent --variant --budget --seed
│   └── make_figures.py
└── tests/
    ├── test_contract_scoring.py  # MOST IMPORTANT — see §6
    ├── test_eig.py
    └── test_predicate_safety.py


3. The target API (system under learning)

A FastAPI server the agent probes over HTTP. You write it, so you own the ground truth — no contaminated public benchmark, no leaderboard to game.

Theme: a small store API. GET /products, POST /orders, GET /orders/{id}.

The hidden contract is a set of atomic rules, each independently checkable. This is what makes recovery measurable. Rule types to include:

Rule typeExampleRequired paramPOST /orders requires customer_idOptional parampage is optional, defaults to 1Type constraintquantity must be an integerRange constraint1 <= quantity <= 99Enum domainstatus in {pending, shipped, cancelled}Format constraintemail must match an email patternConditional dependencyif expedited=true, phone becomes requiredPagination behaviourlimit caps at 50 even if you ask for moreError semanticsmissing required -> 422; bad enum -> 400Mutual exclusionsku and product_id cannot both be sent

Three difficulty variants (easy / medium / hard) that add rules and make error messages progressively less informative. hard returns bare status codes with no field hints — this is where LLM priors should matter most, and where the interesting result lives.

Rules for the server:


Fully deterministic. Same request -> same response, always.
Stateless between probes (reset endpoint available to the harness, not the agent).
Never leak the spec. No OpenAPI route, no /docs, no schema in error bodies beyond what the variant allows.
Every response the agent sees goes through client.py so probes are counted.



3.1 Counter-prior rules — required

Roughly half the rules in every variant must be counter-prior: deliberately chosen to defeat the conventions an LLM has memorised. A store API whose limit caps at 50 and whose status enum is {pending, shipped, cancelled} can be largely guessed from the endpoint names alone, which would let a ReAct baseline score well without probing effectively and leave no headroom for any result.

Every rule carries a prior_class tag: conventional or counter_prior. Examples of the counter-prior treatment: a cap at 37 rather than 50; an enum carrying an unguessable extra member; a 0-indexed page where convention is 1-indexed; an arbitrary house format like CUS-######; an error status that violates convention (range violation returning 422 rather than 400).

Scoring rule: recall, precision and F1 are always reported for the two subsets separately. Never report the blend alone. The expected shape of the result is that baselines match the EIG agent on conventional rules and fall away on counter-prior ones — that separation is the finding, and it survives even if the headline blended number ties.

3.2 Identifiability ceiling — computed analytically

Under a terse or bare variant some rules are simply unrecoverable: no observable outcome distinguishes a contract containing the rule from one where it is false. Counting those against recall measures the problem's difficulty, not the agent's skill, and makes the hard column uninterpretable.

Compute the ceiling statically, not with an oracle agent. For each rule, ask whether any probe's observable outcome differs between the contract with the rule and the contract with it negated, given that variant's error verbosity. Deterministic, no LLM, milliseconds. Produces achievable_rules at M1, before any agent runs.

Negation is per rule kind, and this matters. For most kinds, deleting the rule is its negation. For a default it is not: the fallback may coincide with the declared default, making the two contracts observationally identical even though the default is plainly discoverable. Negating a default means declaring a different one.

Report hard-variant recovery as a fraction of achievable, never absolute.

4. Hypothesis representation

The single most important design decision. Hypotheses are executable, not prose.

The LLM proposes each candidate contract as a JSON object of atomic rules, which compiles to a predicate:

python# A hypothesis predicts the outcome CLASS of any probe, deterministically.
class Hypothesis:
    rules: list[Rule]
    weight: float

    def predict(self, probe: Probe) -> OutcomeClass:
        """Return the predicted response class: OK | 400 | 422 | TRUNCATED | ...
        Deterministic. NO LLM call. This is what makes EIG cheap."""

Why this matters: with K=30 hypotheses and 20 candidate probes, naive EIG would need 600 LLM calls per step. Executable hypotheses make it 600 function calls and one LLM call per step for proposing candidates.

Proposal loop. The LLM sees the observation history and emits K diverse candidate contracts consistent with everything seen so far. Diversity is essential — a hypothesis set that agrees on everything has zero EIG for every probe and the agent stalls. Enforce it: reject duplicates, and if the surviving set collapses below a floor (say 3), re-propose with an explicit instruction to disagree with the current majority.

Safety. Hypothesis code is LLM-generated. Do not exec arbitrary strings. Constrain hypotheses to a fixed rule grammar (a closed set of rule types with typed fields) and interpret them. test_predicate_safety.py must prove no code path executes model-authored Python.


4.2 Factored hypothesis space

A single particle set over whole contracts is a vanishingly thin cover: with ~10 rule types across 3 endpoints the contract space is combinatorially huge, K=30 whole-contract particles will essentially never contain the truth, and the hard elimination rule of §5 empties the set constantly. The agent thrashes on re-proposal instead of learning.

Factor the posterior instead. Maintain independent particle sets per factor, each densely covering its own small subspace. Two kinds of factor are required, because pure per-slot factoring cannot represent relational rules — expedited -> phone required and sku XOR product_id span two parameters and would be unrepresentable:


ParameterFactor — one per parameter. Covers that parameter's requiredness, type, range, enum domain, format, default.
RelationalFactor — one per cross-parameter rule slot. Covers conditional dependencies and mutual exclusions.


Diversity floor is 8 per factor, not 3. A floor of 3 caps EIG at log2(3) ≈ 1.58 bits and causes re-proposal churn.

Target-factor EIG. Score EIG with respect to a target factor — take the highest-entropy factor as the target and pin every other factor to its MAP value — rather than against the joint. Probes chosen this way are naturally isolating: they vary one variable at a time. That is both the controlled experiment and the practical mitigation for the credit-assignment problem, since an isolating probe's outcome has an unambiguous cause.

Re-proposal stays local: when a factor's particle set empties, only that factor is re-proposed, not the whole contract.

5. Probe selection

pythondef eig(probe: Probe, hyps: list[Hypothesis]) -> float:
    """EIG == entropy of the partition the probe induces over hypotheses."""
    buckets: dict[OutcomeClass, float] = defaultdict(float)
    for h in hyps:
        buckets[h.predict(probe)] += h.weight
    total = sum(buckets.values())
    return -sum((w/total) * log2(w/total) for w in buckets.values() if w > 0)

A probe every hypothesis agrees on scores 0 — it teaches nothing, and the naive agents waste most of their budget on exactly these.

Candidate probes come from the LLM (§1.1: this is the equivalence-oracle approximation, and it's where priors earn their keep) — ask for probes that would discriminate between the current top hypotheses. Then score them with eig() and send the winner. LLM proposes; information theory decides.

Update. After observing the real outcome, eliminate every hypothesis that predicted otherwise. If the set empties, all hypotheses were wrong — re-propose from the evidence log (§5.1). Log every such event. It is the agent being genuinely surprised, and it will be one of the best findings in the article.

5.1 Context discipline — the main cost risk

Never send raw observation history to the LLM. If every call appends the full transcript of past requests and responses, token usage grows quadratically with probe count and a $5 experiment becomes a $50 one. This is the single easiest way to blow the budget, and it degrades quality too — long raw logs bury the signal.

Instead maintain a compact evidence log: a structured, deduplicated set of confirmed facts derived from observations, not the observations themselves.

python@dataclass
class Evidence:
    confirmed: list[str]      # facts established beyond doubt
    refuted: list[str]        # hypotheses ruled out, with the probe that killed them
    open_questions: list[str] # what remains ambiguous
    recent: list[ProbeResult] # last N raw results only (N ~ 5)

Rules:


The prompt carries Evidence, never the full log. Raw responses live in the trace on disk for the figures.
Keep only the last ~5 raw results for local context; everything older must have been distilled into confirmed / refuted.
Deduplicate aggressively — the same confirmed fact must never appear twice.
Assert a hard token ceiling on every prompt (e.g. 6,000 input tokens). Exceeding it is a bug, not a cost of doing business — fail loudly rather than silently paying.
Log per-call token counts to the trace so cost is measurable after the fact, not guessed.



6. Evaluation

eval/scoring.py compares the agent's final reported contract against ground truth, rule by rule:

MetricWhyRule recallfraction of true rules discoveredRule precisionof the rules it reports, how many are real — catches hallucinated constraints, which LLMs will absolutely inventF1headline numberProbes to 80% recallthe efficiency claimWasted-probe ratefraction of probes with EIG ≈ 0 (measurable post-hoc for every agent)Cost / latencypractical column: LLM tokens + wall clock

Rule matching must be semantic, not string equality — 1 <= quantity <= 99 and quantity in range(1,100) are the same rule. Normalise both sides into a canonical form before comparing. test_contract_scoring.py is the most important test file in the repo: if scoring is wrong, every number in the article is wrong. Include cases for paraphrased-but-equivalent rules, subtly-wrong rules (off-by-one bounds must NOT match), and hallucinated rules.

6.1 The frozen referee

Wasted-probe rate is defined relative to a hypothesis set, but the random and ReAct agents do not maintain one, and the EIG agent's own sets cannot be reused — a different trajectory means different beliefs at step k. Without a fixed yardstick the metric is not comparable across arms and must not appear in the results table.

So: generate one reference hypothesis set per variant, independently and seeded, factored to match §4.2, roughly 100 particles per factor. Freeze it to disk before any experiment runs. Replay every agent's probe sequence against that same frozen set to score wasted probes. Same yardstick for all four agents.

6.2 Scope of the efficiency claim

Probe efficiency only matters when probes are the scarce resource — rate limits, audit logs, side effects, detection risk. If probes are free, ReAct with a large budget is a perfectly good answer, and the write-up says so plainly. The headline sentence claims fewer probes; the token and wall-clock cost sits immediately next to it, not three paragraphs later, because the EIG agent spends more LLM tokens per probe than ReAct does.

Run matrix: 4 agents x 3 variants x 3 seeds, at a fixed probe budget (default 100). Report mean and spread. Three seeds minimum because LLM sampling is noisy and a single run proves nothing — never report a single-run number as a result.

Model: gpt-4o-mini throughout. Do not silently switch to a larger model; if you believe a run needs one, say so and ask.

Budget expectation: roughly 130 LLM calls per full run, so the 36-run matrix lands around 4,000–5,000 calls. Print a running cost estimate and a cumulative call counter to stdout during run_experiment.py. Abort with a clear message if a single run exceeds 300 LLM calls — that means something is looping.


7. Visualizations

Design principle: visualize the epistemics, not the numbers. An API is invisible — JSON in, JSON out — so a line chart is the weakest possible artefact. The interesting thing to show is uncertainty dying. Charts are supporting evidence; the hero visuals are animated and driven by real trace data.

All visuals read from the JSONL traces via trace_export.py. Never hardcode data into a visual — if a figure can't be regenerated from a trace, it doesn't ship.

7.1 Hero — the declassification race (declassify.py)

The ground-truth contract rendered as a redacted document: every rule blacked out. Two agents side by side (random vs EIG) racing to un-redact it. Each rule reveals at the exact probe index where that agent first confirmed it. A probe counter ticks; a live readout shows surviving hypotheses.

This is the shareable artefact. It makes the result legible in three seconds with no axis labels to read. Requirements:


Self-contained HTML + inline JS, no build step, no external deps.
Auto-plays once on load, with a replay control. Respect prefers-reduced-motion.
Reveal schedules come from first_confirmed_at per rule in the trace.
Works in light and dark; flat styling; no gradients.
Also export a static PNG of the final frame for the article body.


7.2 Hypothesis swarm (swarm.py)

K dots, one per candidate contract. After each probe, the hypotheses that predicted wrongly fade out. The viewer watches a cloud collapse to a point. Mark re-proposal events (where the space emptied — the agent was genuinely surprised) with a visible burst of new dots. Those moments are the most interesting thing in the whole run and must be legible.

7.3 The partition split (partition.py)

Static SVG for one chosen probe: the hypothesis set fanning into outcome buckets. An even split is highlighted (high EIG); a unanimous one is grayed (zero EIG — a wasted probe). This is the figure that makes the math visible — it shows in one image why the EIG agent picks what it picks. Generate one high-EIG example and one zero-EIG example, side by side.

7.4 Probe tape (tape.py)

A horizontal filmstrip of every probe in a run, each cell shaded by information actually gained. The random agent's tape is mostly gray; the EIG agent's is dense early and fades as it exhausts what's left to learn. One tape per agent, stacked, same length — the visual contrast carries the whole efficiency argument without a single number.

7.5 Supporting chart (recovery_curve.py)

Contract F1 vs probe budget, one line per agent, shaded band across seeds. Keep it — it's the rigorous version of the claim — but it goes below the hero visuals in the article, not above.


8. Build order

Each milestone runs and passes tests before the next.


M1 — Target API. Server plus the easy variant, ground-truth rule set, serve.py. Manual curl confirms rules fire.
M2 — Client + budget. Every probe counted and logged. Agent literally cannot see the contract module.
M3 — Scoring. test_contract_scoring.py green, including paraphrase, off-by-one, and hallucination cases. Do not proceed until this is trustworthy.
M4 — Baselines. Random and ReAct agents run end-to-end and produce scored contracts. You now have a working result with no EIG anywhere — commit it. Then sanity-check the ceiling risk: if ReAct already scores high on the counter_prior subset, the variant is not counter-prior enough and M1 gets fixed before continuing. Catching that here costs one run; catching it after the full matrix costs 36.
M5 — Hypothesis machinery. Proposal, rule grammar, interpreter, safety tests.
M6 — EIG agent. test_eig.py proves: unanimous probe scores 0, evenly-splitting probe scores maximum.
M7 — Experiments. Full matrix (36 runs), traces on disk, RESULTS.md written with mean and spread. Confirm the cost counter matches the estimate before committing.
M8 — Visuals. Build §7 in order: declassification race first (it's the hero), then swarm, partition, tape, curve. Every one regenerated from traces — if a visual can't be rebuilt by rerunning make_figures.py against the JSONL, it is not done.



9. Rules for you (Claude Code)


Cost discipline. gpt-4o-mini only. Print a running token/cost estimate and cumulative call count. Never launch the full 36-run matrix unprompted — ask first, and run a smoke config by default.
Enforce §5.1 context discipline from the very first LLM call. Retrofitting compression after the prompts are written is painful and usually gets skipped. Assert the token ceiling in client.py, not in a comment.
Cache aggressively. Identical probe -> cached response. Re-running an experiment should be nearly free.
No hardcoded data in visuals. Every figure regenerates from a trace file. A visual with numbers typed into the JS is a fabrication risk and will not ship.
The ground truth must be unreachable from agent code. Enforce it with an import-boundary test, not a comment.
Log everything. Every probe, EIG score, partition, and hypothesis death goes to a structured JSONL trace. The figures are built from traces, not from re-running.
If the EIG agent doesn't win, say so plainly. That is a publishable finding, and a spec that only permits one outcome is not an experiment. The most likely honest result is that it wins clearly on hard and barely at all on easy — which is itself the interesting story.
Type hints everywhere. ruff clean. Docstrings citing which idea from §1 each module implements.

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
