"""The factored posterior.

A single particle set over whole contracts is a hopelessly thin cover: the
contract space is combinatorially large, a few dozen whole-contract particles
will essentially never contain the truth, and hard elimination then empties the
set constantly, so the agent thrashes on re-proposal instead of learning.

The posterior is factored instead. Each factor keeps its own dense particle set
over a small subspace:

  ParameterFactor  one per parameter: requiredness, type, range, enum, format,
                   default.
  RelationalFactor one per cross-parameter slot: conditional dependencies and
                   mutual exclusions, which span two parameters and cannot be
                   represented by per-parameter factoring at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import log2

from probe.client import Probe, ProbeResult
from probe.hypothesis.predicate import observed_class, predict
from probe.hypothesis.rules import Rule


@dataclass(frozen=True)
class Particle:
    """One candidate answer for a single factor."""

    rules: tuple[Rule, ...]

    def key(self) -> str:
        return "|".join(
            sorted(str(sorted(r.as_dict().items(), key=str)) for r in self.rules)
        )


@dataclass
class Factor:
    name: str
    endpoint: str
    kind: str  # "parameter" | "relational"
    particles: list[Particle] = field(default_factory=list)
    deaths: int = 0
    reproposals: int = 0
    _map_cache: tuple[Rule, ...] | None = None

    def add(self, particles: list[Particle]) -> None:
        """Add particles, rejecting duplicates.

        A factor whose particles all agree has zero information gain for every
        probe, so duplicates are not merely wasteful: they stall the agent.
        """
        seen = {p.key() for p in self.particles}
        for particle in particles:
            if particle.key() not in seen:
                seen.add(particle.key())
                self.particles.append(particle)

    @property
    def is_empty(self) -> bool:
        return not self.particles

    def map_rules(self) -> tuple[Rule, ...]:
        """The current best guess for this factor.

        Whichever surviving particle explains the most evidence. Taking the
        first survivor instead would be arbitrary: a factor that was just
        refilled is full of particles nothing has tested yet, and reporting one
        of those as the answer produces a contract built from untested guesses.
        """
        if not self.particles:
            return ()
        if self._map_cache is not None:
            return self._map_cache
        return self.particles[0].rules

    def entropy(self) -> float:
        """Uniform over survivors, so entropy is just log2 of how many remain."""
        return log2(len(self.particles)) if self.particles else 0.0


@dataclass
class FactorSet:
    factors: list[Factor] = field(default_factory=list)
    endpoints: tuple[str, ...] = ()
    history: list[tuple[Probe, str]] = field(default_factory=list)

    def get(self, name: str) -> Factor | None:
        return next((f for f in self.factors if f.name == name), None)

    def refresh_map(self) -> None:
        """Re-elect each factor's best guess against everything observed.

        Pins come from the previous election rather than the current one, so
        this stays a single pass and cannot recurse.
        """
        for factor in self.factors:
            if len(factor.particles) < 2 or not self.history:
                factor._map_cache = None
                continue
            pinned = self.pinned_rules(exclude=factor.name)
            best, best_hits = factor.particles[0], -1
            for particle in factor.particles:
                rules = list(particle.rules) + pinned
                hits = sum(
                    1
                    for probe, seen in self.history
                    if predict(rules, probe, self.endpoints) == seen
                )
                if hits > best_hits:
                    best, best_hits = particle, hits
            factor._map_cache = best.rules

    def pinned_rules(self, exclude: str | None = None) -> list[Rule]:
        """Every other factor at its MAP value.

        Pinning is what makes a probe isolating: with everything else held
        fixed, the outcome has an unambiguous cause.
        """
        rules: list[Rule] = []
        for factor in self.factors:
            if factor.name != exclude:
                rules.extend(factor.map_rules())
        return rules

    def assembled(self) -> list[Rule]:
        return self.pinned_rules(exclude=None)

    def target(self) -> Factor | None:
        """The factor we are least sure about."""
        live = [f for f in self.factors if len(f.particles) > 1]
        return max(live, key=lambda f: f.entropy()) if live else None

    def predict_with(self, factor: Factor, particle: Particle, probe: Probe) -> str:
        rules = list(particle.rules) + self.pinned_rules(exclude=factor.name)
        return predict(rules, probe, self.endpoints)

    def eliminate(
        self, probe: Probe, result: ProbeResult, only: str | None = None
    ) -> list[dict[str, object]]:
        """Drop every particle whose prediction the API just contradicted.

        Elimination is confined to the factor the probe was chosen to isolate.
        Applying it to every factor sounds stronger but is not: the pinned
        values of the other factors are themselves guesses, so a wrong pin
        convicts innocent particles in a factor the probe was never about. Done
        across the board it empties factor after factor and the agent spends
        its budget re-proposing instead of learning.
        """
        seen = observed_class(result)
        self.history.append((probe, seen))
        events: list[dict[str, object]] = []

        targets = [f for f in self.factors if only is None or f.name == only]
        for factor in targets:
            survivors = []
            killed = 0
            for particle in factor.particles:
                if self.predict_with(factor, particle, probe) == seen:
                    survivors.append(particle)
                else:
                    killed += 1
            if killed:
                factor.particles = survivors
                factor._map_cache = None
                factor.deaths += killed
                events.append(
                    {
                        "factor": factor.name,
                        "killed": killed,
                        "surviving": len(survivors),
                        "observed": seen,
                    }
                )
        return events

    def empty_factors(self) -> list[Factor]:
        return [f for f in self.factors if f.is_empty]

    def total_particles(self) -> int:
        return sum(len(f.particles) for f in self.factors)

    def reported_rules(self) -> list[dict[str, object]]:
        """The contract implied by every factor's current best guess."""
        return [rule.as_dict() for rule in self.assembled()]
