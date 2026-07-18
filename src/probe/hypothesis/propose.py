"""LLM proposal of factors and their particles.

The model's job here is to generate a dense, diverse cover of each small
subspace. Diversity is the whole game: a factor whose particles agree has zero
information gain for every probe and stalls the agent, so duplicates are
rejected and disagreement is asked for explicitly.
"""

from __future__ import annotations

from probe.hypothesis.rules import GRAMMAR_PROMPT, parse_rules
from probe.hypothesis.space import Factor, FactorSet, Particle
from probe.llm import LLMClient

SURFACE_SYSTEM = """You are reverse-engineering an undocumented HTTP API.

From the evidence, list the parameters each endpoint plausibly accepts, and the
pairs of parameters that might be related (one requiring another, or two that
cannot be sent together).

Be generous with parameters: list at least eight per endpoint, including ones
you have not confirmed but which an API of this kind plausibly has — filtering,
sorting, pagination, contact details, status, currency, flags. A parameter you
fail to name can never be investigated, so missing one is far more costly than
naming one that turns out not to exist.

Be sparing with relations. Only propose a pair when the evidence actually hints
at a link between them.

Reply with JSON:
{"parameters":[{"endpoint":"POST /orders","param":"quantity"}, ...],
 "relations":[{"endpoint":"POST /orders","param_a":"sku","param_b":"product_id"}, ...]}"""

PARTICLE_SYSTEM = """You are enumerating competing hypotheses about ONE aspect of an
undocumented HTTP API.

Propose {k} DIFFERENT hypotheses. They must disagree with each other: if they
all predict the same responses, they are worthless. Vary the specific values,
not just the wording. Cover both the conventional answer and unconventional
ones, because this API may cap, index, or number things differently from the
APIs you have seen.

Every hypothesis must be consistent with all the evidence given.

""" + GRAMMAR_PROMPT + """

Each hypothesis is a list of rules, possibly empty (meaning no constraint).

Reply with JSON: {"hypotheses":[[rule, ...], [rule, ...], ...]}"""


def propose_surface(
    llm: LLMClient, endpoints: tuple[str, ...], evidence: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Ask which parameters and relations plausibly exist."""
    user = f"ENDPOINTS: {', '.join(endpoints)}\n\n{evidence}"
    payload = llm.complete_json(SURFACE_SYSTEM, user, purpose="surface")

    params = [
        {"endpoint": str(item.get("endpoint", "")), "param": str(item.get("param", ""))}
        for item in payload.get("parameters", [])
        if isinstance(item, dict) and item.get("param") and item.get("endpoint")
    ]
    relations = [
        {
            "endpoint": str(item.get("endpoint", "")),
            "param_a": str(item.get("param_a", "")),
            "param_b": str(item.get("param_b", "")),
        }
        for item in payload.get("relations", [])
        if isinstance(item, dict) and item.get("param_a") and item.get("param_b")
    ]
    return params, relations


def build_factors(
    params: list[dict[str, str]],
    relations: list[dict[str, str]],
    endpoints: tuple[str, ...],
    max_relations: int = 4,
) -> FactorSet:
    """Parameter factors first, then a few relational ones.

    Ordering matters because the caller caps how many factors it will carry.
    Relational factors are cheap to propose and expensive to resolve, so
    letting them crowd out parameter factors leaves real parameters with no
    representation at all and caps recall before probing starts.
    """
    factors: list[Factor] = []
    relational: list[Factor] = []
    seen: set[str] = set()

    for item in params:
        if item["endpoint"] not in endpoints:
            continue
        name = f"{item['endpoint']}::{item['param']}"
        if name not in seen:
            seen.add(name)
            factors.append(
                Factor(name=name, endpoint=item["endpoint"], kind="parameter")
            )

    for item in relations:
        if item["endpoint"] not in endpoints:
            continue
        pair = "+".join(sorted((item["param_a"], item["param_b"])))
        name = f"{item['endpoint']}::rel::{pair}"
        if name not in seen:
            seen.add(name)
            relational.append(
                Factor(name=name, endpoint=item["endpoint"], kind="relational")
            )

    return FactorSet(factors=factors + relational[:max_relations], endpoints=endpoints)


def _describe(factor: Factor) -> str:
    if factor.kind == "relational":
        pair = factor.name.split("::rel::")[1].replace("+", " and ")
        return (
            f"the relationship between {pair} on {factor.endpoint}: "
            "whether one becomes required given the other, or whether they are "
            "mutually exclusive, or whether there is no relationship at all"
        )
    param = factor.name.split("::")[-1]
    return (
        f"the parameter {param!r} on {factor.endpoint}: whether it is required "
        "or optional and with what default, its type, its bounds, its allowed "
        "values, its format, and which status code a violation returns"
    )


def propose_particles(
    llm: LLMClient,
    factor: Factor,
    evidence: str,
    k: int,
    disagree_with: str = "",
) -> list[Particle]:
    """Propose k competing hypotheses for one factor."""
    system = PARTICLE_SYSTEM.replace("{k}", str(k))
    user = (
        f"ASPECT: {_describe(factor)}\n"
        f"Use exactly this endpoint string: {factor.endpoint}\n\n"
        f"{evidence}\n{disagree_with}"
    )
    payload = llm.complete_json(system, user, purpose="particles")

    particles: list[Particle] = []
    for raw in payload.get("hypotheses", []) or []:
        if not isinstance(raw, list):
            continue
        rules = parse_rules(raw)
        kept = tuple(r for r in rules if r.endpoint == factor.endpoint)
        particles.append(Particle(rules=kept))
    return particles


def refill(
    llm: LLMClient,
    factor: Factor,
    evidence: str,
    floor: int,
) -> tuple[list[Particle], bool]:
    """Top a factor back up to the diversity floor.

    Returns the new particles and whether this was a re-proposal from empty,
    which is the agent discovering every hypothesis it held was wrong.
    """
    was_empty = factor.is_empty
    nudge = ""
    if was_empty:
        nudge = (
            "\nEvery hypothesis you previously held for this aspect has been "
            "refuted by the evidence. Propose genuinely different ones."
        )
    elif factor.particles:
        nudge = (
            "\nThese survive and must NOT be repeated:\n"
            + "\n".join(f"  {p.rules}" for p in factor.particles[:4])
        )

    proposed = propose_particles(llm, factor, evidence, k=floor + 4, disagree_with=nudge)
    return proposed, was_empty
