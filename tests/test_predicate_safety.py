"""Hypotheses are data, never code.

Model output reaches the interpreter as JSON, is validated against a closed
grammar, and is then read by fixed Python. No path executes model-authored
Python, and this file exists to prove it rather than assert it in a comment.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from probe.client import Probe
from probe.hypothesis.predicate import predict
from probe.hypothesis.rules import KINDS, parse_rule, parse_rules

SRC = Path(__file__).resolve().parents[1] / "src" / "probe"
ENDPOINTS = ("GET /products", "POST /orders")

# Any of these applied to model output would be a way to execute it.
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "globals", "locals"}
FORBIDDEN_MODULES = {"pickle", "marshal", "shelve", "subprocess"}


def test_no_agent_module_can_execute_a_string() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_CALLS:
                    offenders.append(f"{path.name}: calls {node.func.id}()")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                        offenders.append(f"{path.name}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_MODULES:
                    offenders.append(f"{path.name}: imports from {node.module}")
    assert not offenders, "; ".join(offenders)


@pytest.mark.parametrize(
    "hostile",
    [
        {"kind": "__import__('os').system('echo pwned')", "endpoint": "GET /products"},
        {"kind": "eval", "endpoint": "GET /products", "param": "x"},
        {"kind": "required", "endpoint": "GET /products", "param": {"$ref": "evil"}},
        {"kind": "range", "endpoint": "GET /products", "param": "x", "lo": "__import__"},
        {"kind": "type", "endpoint": "GET /products", "param": "x", "type_name": "os.system"},
        {"kind": "format", "endpoint": "GET /products", "param": "x", "pattern": "((((("},
        {"kind": "enum", "endpoint": "GET /products", "param": "x", "values": "not a list"},
        "a bare string, not an object",
        None,
        42,
    ],
)
def test_hostile_rules_are_rejected_or_defanged(hostile: object) -> None:
    parsed = parse_rule(hostile)
    if parsed is None:
        return
    # Anything that survives parsing must be a value from the closed grammar.
    assert parsed.kind in KINDS
    assert isinstance(parsed.endpoint, str)


def test_unparseable_regex_never_reaches_the_matcher() -> None:
    # An invalid pattern is refused at parse time rather than raising later.
    assert parse_rule(
        {"kind": "format", "endpoint": "GET /products", "param": "x", "pattern": "(((("}
    ) is None


def test_prediction_over_hostile_input_stays_a_pure_function() -> None:
    rules = parse_rules(
        [
            {"kind": "exec", "endpoint": "GET /products", "param": "limit"},
            {"kind": "pagination_cap", "endpoint": "GET /products", "param": "limit", "cap": 37},
        ]
    )
    # The hostile kind is dropped; the legitimate rule survives and interprets.
    assert len(rules) == 1
    outcome = predict(rules, Probe("GET", "/products", params={"limit": 100}), ENDPOINTS)
    assert outcome == "TRUNCATED"


def test_rule_fields_are_never_callable() -> None:
    rules = parse_rules(
        [{"kind": "required", "endpoint": "GET /products", "param": "limit", "status": 422}]
    )
    for rule in rules:
        for value in vars(rule).values():
            assert not callable(value)
