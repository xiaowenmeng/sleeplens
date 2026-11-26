"""Current-runtime tests are offline; fixed fixtures remain explicit."""

from importlib.resources import files

import pytest

from sleeplens.data import load_dataset


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket

    original_connect = socket.socket.connect

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not contact a network or paid model")

    def local_only(connection, address):
        # Windows asyncio and Streamlit use loopback sockets internally.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}:
            return original_connect(connection, address)
        return forbidden()

    monkeypatch.setattr("socket.socket.connect", local_only)
    monkeypatch.setattr("sleeplens.llm.DeepSeekClient.complete", forbidden)


@pytest.fixture
def regression_dataset(monkeypatch):
    path = files("sleeplens").joinpath("fixtures/synthetic_sleep.json")
    monkeypatch.setattr("sleeplens.analysis.load_dataset", lambda: load_dataset(path))
