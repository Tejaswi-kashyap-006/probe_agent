# Results

**Status: preliminary. One seed, one variant. This is not yet a result, and the
headline finding so far is negative.**

The run matrix the design calls for is 4 agents x 3 variants x 3 seeds. What has
been run is 4 agents x 1 variant x 1 seed. A single run proves nothing, LLM
sampling is noisy, and every number below should be read as "what happened once"
rather than "what is true".

## Head to head: easy variant, seed 0, budget 100 probes

| agent | F1 | conventional recall | counter-prior recall | probes | LLM calls | cost |
|---|---|---|---|---|---|---|
| random | **0.296** | 0.400 | 0.000 | 100 | 8 | $0.003 |
| hypothesis | 0.240 | 0.200 | **0.143** | 100 | 110 | $0.068 |
| react | 0.214 | 0.300 | 0.000 | 100 | 0 (fully cached) | $0.000 |
| eig | 0.138 | 0.200 | 0.000 | 100 | 70 | $0.048 |

Identifiability ceiling on `easy` is 1.000, so these are fractions of what is
actually recoverable, not of an unreachable total.

## The EIG agent does not win

At one seed on the easiest variant it comes last, below a baseline that sends
random requests, while costing roughly sixteen times as much as that baseline in
LLM spend. The thesis is not supported by the evidence gathered so far.

Two things are worth separating out before anyone reads that as settled.

**Random's F1 is partly an artefact of reporting little.** It names few rules, so
its precision is high and F1 rewards that. It recovers 0.400 of the conventional
rules — mostly the required-parameter rules, which random requests trip over by
accident — and 0.000 of the counter-prior ones. It is not recovering a contract;
it is recalling that missing parameters produce errors.

**The counter-prior column is the one that matters, and only one agent scores on
it.** The `hypothesis` agent is the sole arm with non-zero counter-prior recall
(0.143). That subset is exactly the part of the contract that cannot be guessed
from convention, so it is the part that measures recovery rather than recall of
API folklore. That hypothesis tracking scores there while random, ReAct and EIG
score zero is the most suggestive signal in the data — at n=1, which is to say,
barely a signal at all.

The awkward pairing is that `hypothesis` and `eig` share all their machinery and
differ only in the selection rule: `hypothesis` picks a candidate probe at random,
`eig` picks the one that splits the surviving hypotheses most evenly. The ablation
beating the method suggests the problem is in probe selection specifically rather
than in hypothesis tracking. Possible explanations, untested:

- EIG is scored against the target factor with all others pinned. If the pins are
  wrong, the probe that best splits the target factor may be uninformative about
  the real contract.
- Choosing the maximally-splitting probe concentrates effort on whichever factor
  is currently most uncertain, which may starve the remaining factors. Random
  selection spreads across them.
- The candidate pool is small (roughly 9 usable probes per step). Argmax over a
  weak pool is close to a random draw from it, plus whatever bias the scoring adds.

## Cost

Probe efficiency only matters where probes are the scarce resource. Here they are
not: all four agents spent exactly their 100-probe budget, and the differences are
in tokens. The EIG agent spends far more per probe than ReAct or random, and at
present buys nothing with it.

The `react` row shows $0.000 because that trajectory was already in the LLM disk
cache; its true first-run cost was $0.033 for 161 calls.

## What is not yet measured

- **Medium and hard variants.** The interesting claim was always that priors matter
  most where error messages say least. Untested.
- **Seeds 1 and 2.** Everything above is a single sample.
- **Wasted-probe rate.** Requires the frozen referee, which is specified but not yet
  built, so the metric is deliberately absent from the table above rather than
  computed against incomparable per-agent beliefs.
- **Probes to 80% recall.** No arm reached 80% recall, so the column is empty.

## Honest reading

If these numbers survive the full matrix, the finding is that explicit hypothesis
tracking shows a small advantage on exactly the rules that defeat memorised
convention, and that information-theoretic probe selection on top of it does not
help and may hurt. That is a publishable result and it is not the one the design
expected. It should not be reported as a win, and the design does not permit
tuning until it becomes one.
