# Method

Three ideas combine here. The implementation is a fairly direct expression of them.

## 1. Membership queries are cheap, equivalence queries are not

Active automata learning frames black-box inference around two kinds of question.
A **membership query** asks whether the system accepts a given input. Here that is
just an HTTP request: the API answers it for free, instantly, and truthfully.

An **equivalence query** asks whether your current model *is* the true model. In a
real black-box setting nothing can answer that. There is no oracle to ask. It has
to be approximated by conformance testing — deliberately generating the inputs
where your own model is most likely to be wrong.

That asymmetry is the interesting part. The cheap half is free. The hard half is
guessing where your beliefs will break, and this is exactly what a language model
is unusually good at: a classical learner has to enumerate the input space, while
a model that has read a great many APIs has priors about how they usually behave
and can jump straight to the suspicious cases.

So the LLM is used as an approximate equivalence oracle — it proposes candidate
probes — and nothing else decides which one to send.

## 2. Expected information gain

For a latent variable θ (the true contract) and a candidate experiment ξ (a probe):

```
IG_θ(ξ, y) = H[p(θ)] − H[p(θ | y, ξ)]
EIG_θ(ξ)   = E_{p(y|ξ)}[ IG_θ(ξ, y) ]
```

Choose the probe maximising EIG. The same idea drives BED-LLM (arXiv:2508.21184),
which applies it to question-asking; the target here is a system contract rather
than a conversation.

## 3. The simplification that makes it affordable

Represent the posterior as a weighted particle set of candidate contracts. If every
hypothesis predicts a probe's outcome **deterministically**, the expectation over
outcomes collapses:

> A probe partitions the hypothesis set by predicted outcome. EIG is the entropy of
> that partition. The best probe splits the survivors most evenly — a binary search
> through contract space.

This is the classical version-space splitting criterion. It means no nested Monte
Carlo, and no LLM call per hypothesis per probe. With 30 hypotheses and 20
candidate probes, naive EIG would need 600 LLM calls per step; deterministic
prediction makes it 600 *function* calls and one LLM call for proposing candidates.

Getting deterministic predictions cheaply is why hypotheses are **executable** —
and why they are emitted as data in a closed rule grammar and then interpreted,
rather than as code that gets run. `tests/test_predicate_safety.py` walks the AST
of the whole agent package to show that no path executes model-authored Python.

## Factoring, and why it was necessary

A particle set over *whole contracts* is a hopelessly thin cover. With around ten
rule kinds across three endpoints the contract space is combinatorially large; a
few dozen whole-contract particles will essentially never contain the truth, and
hard elimination then empties the set constantly. The agent thrashes on
re-proposal instead of learning.

So the posterior is factored, and each factor keeps its own dense set over a small
subspace:

- **ParameterFactor** — one per parameter: requiredness, type, bounds, enum domain,
  format, default.
- **RelationalFactor** — one per cross-parameter slot: conditional dependencies and
  mutual exclusions. These span two parameters and are simply unrepresentable under
  per-parameter factoring, which is why both kinds are required.

EIG is scored against a **target factor** — the one with the highest entropy — with
every other factor pinned to its current best guess. Probes chosen this way vary one
thing at a time. That is both the controlled experiment and the practical answer to
credit assignment: an isolating probe's outcome has an unambiguous cause.

Re-proposal is local. When a factor empties, only that factor is re-proposed.

### What the first implementation got wrong

Three things, each found by inspecting a run's internals rather than reading its score:

1. **Elimination was applied to every factor.** This sounds stronger and is not. The
   pinned values of the other factors are themselves guesses, so a wrong pin convicts
   particles in a factor the probe was never about. It emptied factor after factor.
   Elimination is now confined to the probe's target factor; re-proposals per run
   dropped from 22 to 7.

2. **Factors were named once, off a single request per endpoint.** That invented
   parameters which do not exist, missed most that do, and froze the mistake for the
   whole run. Discovery now runs on a richer bootstrap and repeats as evidence
   accumulates.

3. **The reported contract took each factor's first surviving particle.** Right after
   a refill that is an untested guess. It now elects whichever survivor explains the
   most evidence.

## Measuring it honestly

**Counter-prior rules.** Roughly half of every variant's rules are chosen to defeat
memorised convention: a cap at 37 rather than 50, a 0-indexed page, an enum with an
unguessable extra member, an arbitrary house identifier format, a range violation
returning 422 where convention says 400. Recall is always reported for the
conventional and counter-prior subsets separately, because the blended number
cannot distinguish recovering a contract from recalling how store APIs usually work.

**Identifiability ceiling.** Some rules may be unrecoverable under a variant that
says little in its errors: if no probe's observable outcome differs between the
contract and its negation, no agent can ever find it, and counting it against recall
measures the problem rather than the agent. This is computed analytically, per rule,
before any agent runs. Negation is per rule kind — deleting a *default* is not its
negation, because the fallback may coincide with the declared default and hide a
plainly discoverable rule.

All three variants currently compute to a ceiling of 1.000, `hard` included. Bare
responses still distinguish 400 from 422 from 409, and isolating probes exist for
every rule, so `hard` is harder in practice rather than in principle: what it removes
is the hint about which parameter was at fault when a request varies several things
at once.

**Scoring is behavioural, not syntactic.** Two rules are the same rule if they
classify the same values identically, so `1 <= quantity <= 99` matches
`quantity in range(1, 100)` while an off-by-one bound does not — the two differ on
the boundary, and the boundary is always in the comparison corpus. Status codes are
not part of rule identity; a rule found with the wrong error code counts as found and
the code is reported separately, since scoring it as identity would penalise one
mistake twice.

**Scope of the efficiency claim.** Probe efficiency only matters where probes are the
scarce resource — rate limits, audit logs, side effects, detection risk. If probes are
free, ReAct with a large budget is a perfectly good answer. The EIG agent spends more
LLM tokens per probe than ReAct does, and that cost belongs next to any claim about
probe counts, not three paragraphs later.
