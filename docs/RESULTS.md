# Results

**Status: one variant (`easy`), three seeds, 100-probe budget. The result is
negative and is reported as it came out.**

The design calls for 4 agents x 3 variants x 3 seeds. What has been run is
4 agents x 1 variant x 3 seeds. `medium` and `hard` are untested.

## easy variant, 3 seeds, 100 probes

Mean across seeds, with the range in brackets.

| agent | F1 | conventional recall | counter-prior recall | LLM calls | cost |
|---|---|---|---|---|---|
| random | **0.252** [0.174-0.296] | 0.300 [0.200-0.400] | 0.048 [0.000-0.143] | 7 | $0.006 |
| react | **0.223** [0.214-0.240] | 0.300 [0.300-0.300] | 0.000 | 126 | $0.072 |
| eig | 0.140 [0.091-0.174] | 0.167 [0.100-0.200] | 0.000 | 133 | $0.224 |
| hypothesis | 0.129 [0.095-0.191] | 0.100 [0.000-0.200] | 0.048 [0.000-0.143] | 115 | $0.172 |

The identifiability ceiling on `easy` is 1.000, so these are fractions of what is
genuinely recoverable.

## The method loses

The EIG agent is beaten by both baselines, and by a baseline that sends random
requests, while costing roughly thirty-seven times as much as that baseline in
LLM spend. The thesis — that explicit hypothesis tracking plus information-
theoretic probe selection recovers a contract in fewer probes than an LLM told
to explore — is not supported.

Ranges overlap, so the *size* of the gap is not established. The *ordering* is
more robust than the means suggest: react beats eig on all three seeds
individually, and random beats eig on all three. Nothing here rescues the method.

## Two earlier claims from this project, retracted

Both came from single-seed runs and did not survive three.

**"EIG selection is broken relative to its own ablation."** An earlier run showed
eig 0.138 against hypothesis 0.240, and a detailed mechanism was diagnosed from
the traces: tie-breaking bias, a starvation trap, thin factor coverage. On three
seeds the two agents are indistinguishable — 0.140 [0.091-0.174] against
0.129 [0.095-0.191]. The gap that motivated the diagnosis was seed noise. The
subsequent "regression" to 0.065/0.065, which prompted a further round of
changes, is also inside that variance.

**"Only hypothesis tracking scores on counter-prior rules."** This was called the
most suggestive signal in the data. On three seeds `random` scores identically
(0.048 mean, 0.143 on one seed). There is no such effect.

The code changes made in response to those two claims are not thereby shown to be
wrong, but neither are they shown to be right: they were justified by differences
that turned out not to be real, and none of them has been measured against a
proper baseline. Depth-over-coverage, random tie-breaking, and seeding factors
from error fields are all currently unvalidated.

## Why counter-prior recall is near zero everywhere

No agent recovers the rules that defeat convention: the cap at 37, the 0-indexed
page, the `sundries` category, the `held` status, the `CUS-######` format. Every
arm is near zero on that subset while scoring 0.1-0.3 on conventional rules.

This is the design working as intended as a *measurement* — it cleanly separates
recalling API folklore from recovering a contract — and every agent failing the
part that matters. A store API's required parameters are guessable; its arbitrary
constants are not, and none of these agents systematically go looking for them.

## Where the ceiling actually binds

Trace diagnostics show both hypothesis-based agents build factors covering only
4-5 of the 9 real parameter slots, capping recall near 0.5 before a probe is
chosen. Whatever is wrong is upstream of probe selection: the agents do not
work out what the parameters *are*. Selection cannot help with a parameter that
has no representation.

That is a hypothesis about the failure, not a measured cause, and it is stated
here as such.

## Cost

Probes were never the scarce resource in these runs: all four agents spent their
full 100-probe budget, so no arm can claim probe efficiency. The differences are
entirely in tokens, and the two arms that spend the most tokens produce the worst
contracts. Under the stated scope of the efficiency claim, where probes are free
this design has nothing to offer over ReAct.

## Not yet measured

- **`medium` and `hard` variants.** The claim that priors matter most where error
  messages say least is completely untested, and it is the most interesting one.
- **Wasted-probe rate.** Requires the frozen referee, which is specified but not
  built. Deliberately absent rather than computed against incomparable beliefs.
- **Probes to 80% recall.** No arm came close to 80%, so the column is empty.

## Honest reading

On the easiest variant, with the most informative error messages, a factored
hypothesis space with EIG-driven probe selection performs worse than random
probing and worse than a plain ReAct loop, at many times the cost. Three seeds is
thin, and one variant is thinner, but nothing in the data points the other way.

The remaining open question worth spending money on is `hard`: if the ordering
inverts where errors stop naming fields, the method has a defensible niche. If it
does not, the honest conclusion is that this approach does not work at this scale
and budget, and the write-up should say so.
