"""The laboratory must not know the experiment exists.

``docs/SCOPE.md`` says the OSSE has to be usable by *any* evaluation method.
That is only true if the evaluation method is not wired into it.  The
dependency is therefore one-way, and this test is what makes that structural
rather than aspirational.
"""

from __future__ import annotations

import ast
from pathlib import Path

LAB = Path(__file__).resolve().parents[2] / "src" / "wildfireguardian_osse"
FV = Path(__file__).resolve().parents[2] / "src" / "wildfireguardian_fv"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_laboratory_never_imports_the_experiment_layer():
    offenders = []
    for path in sorted(LAB.rglob("*.py")):
        for name in _imported_modules(path):
            if name.split(".")[0] == "wildfireguardian_fv":
                offenders.append(f"{path.relative_to(LAB.parent)} imports {name}")
    assert not offenders, (
        "the OSSE laboratory must not depend on the forecast-value experiment "
        "(docs/DECISIONS.md#d-017):\n  " + "\n  ".join(offenders)
    )


def test_experiment_layer_has_no_numpy_random_outside_its_rng_module():
    offenders = []
    for path in sorted(FV.rglob("*.py")):
        if path.name == "rng.py":
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("default_rng", "np.random.seed", "RandomState"):
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert not offenders, (
        "all randomness goes through a named stream in wildfireguardian_fv/"
        f"rng.py (AGENTS.md section 1): {offenders}"
    )


def test_every_fv_stream_is_declared():
    from wildfireguardian_fv.rng import FV_STREAM_NAMES, derive_fv_seed

    for name in FV_STREAM_NAMES:
        assert derive_fv_seed(1, 0, name) >= 0
    try:
        derive_fv_seed(1, 0, "undeclared_stream")
    except ValueError:
        return
    raise AssertionError("an undeclared stream must raise")
