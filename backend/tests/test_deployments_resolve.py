"""Guard: every Prefect deployment in the catalogue must resolve to a real flow.

This catches the bug class where a ``DeploymentSpec.flow_path`` points at a
module/callable that does not exist, so ``apply`` silently skips it and the
scheduled task never runs.

Any entry that is intentionally not-yet-implemented is listed in
``KNOWN_UNIMPLEMENTED`` below with a documented reason and xfailed, so the rest
of the catalogue is still strictly enforced.
"""

from __future__ import annotations

import pytest

from schedules.prefect_deployments import DEPLOYMENTS, _resolve_flow

# Deployment name -> reason. These resolve-failures are expected/accepted until
# the corresponding flow is built. Everything NOT in this map MUST resolve.
# Currently empty: every catalogued flow resolves. Add an entry here (name ->
# reason) only if a flow is intentionally catalogued before being implemented.
KNOWN_UNIMPLEMENTED: dict[str, str] = {}


def test_catalogue_is_non_empty() -> None:
    assert DEPLOYMENTS, "deployment catalogue is empty"


@pytest.mark.parametrize("dep", DEPLOYMENTS, ids=[d.name for d in DEPLOYMENTS])
def test_flow_path_resolves(dep) -> None:
    if dep.name in KNOWN_UNIMPLEMENTED:
        pytest.xfail(KNOWN_UNIMPLEMENTED[dep.name])
    # Must not raise (ImportError / ModuleNotFoundError / AttributeError).
    fn = _resolve_flow(dep.flow_path)
    assert callable(fn), f"{dep.name} -> {dep.flow_path} did not resolve to a callable"
