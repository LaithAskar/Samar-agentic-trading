from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest) -> object:
    if request.node.get_closest_marker("enable_socket") is not None:
        yield None
        return
    request.getfixturevalue("socket_disabled")
    yield None
