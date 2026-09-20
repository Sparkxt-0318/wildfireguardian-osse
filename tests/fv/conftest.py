"""Shared fixtures for the forecast-value experiment tests.

Worlds are expensive (about two seconds each), so the session-scoped fixtures
build a small fixed set and every test reuses it.  Tests that need a *fresh*
world to prove reproducibility build their own.
"""

from __future__ import annotations

import pytest

from wildfireguardian_fv.worlds import WorldGenConfig, build_experiment_world

SMALL = WorldGenConfig(nx=96, ny=96, horizon_min=180.0, master_seed=424242)


@pytest.fixture(scope="session")
def gen_config() -> WorldGenConfig:
    return SMALL


@pytest.fixture(scope="session")
def dev_world(gen_config):
    return build_experiment_world(gen_config, "open_plain", 0)


@pytest.fixture(scope="session")
def dev_world_b(gen_config):
    return build_experiment_world(gen_config, "rolling_noise", 1)


def executable_source(module) -> str:
    """The module's *code*, with every docstring removed.

    Tests that assert "this module never touches X" must look at what the
    module does, not at what its prose says about X. Matching on the docstring
    makes a test fail when the documentation improves, which is exactly
    backwards.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


@pytest.fixture(scope="session")
def conftest_executable_source():
    return executable_source
