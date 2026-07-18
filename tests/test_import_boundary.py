"""The agent must not be able to reach the ground truth.

Enforced statically over the AST rather than by grepping, and dynamically by
checking that importing the agent package never pulls target_api into
sys.modules.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "probe"
FORBIDDEN = "target_api"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_agent_code_never_imports_ground_truth() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        for module in _imported_modules(path):
            if module == FORBIDDEN or module.startswith(f"{FORBIDDEN}."):
                offenders.append(f"{path.relative_to(SRC.parent.parent)} imports {module}")
    assert not offenders, "agent code reaches ground truth: " + "; ".join(offenders)


def test_importing_agent_package_does_not_load_ground_truth() -> None:
    code = (
        "import importlib, sys, pkgutil;"
        "import probe;"
        "[importlib.import_module(m.name) for m in pkgutil.walk_packages("
        "probe.__path__, 'probe.')];"
        "print(any(m == 'target_api' or m.startswith('target_api.') for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False", result.stdout + result.stderr
