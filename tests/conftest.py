"""Pytest fixtures for Ontario Energy Board tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

# pycares spawns a daemon ``_run_safe_shutdown_loop`` thread on first Channel
# creation. pytest-homeassistant-custom-component's ``verify_cleanup`` snapshots
# threads at the start of each test and asserts no extras at the end, which
# fails when aiohttp triggers a DNS resolver during the test. Initialize the
# Channel once at conftest import time so the thread is already running before
# any per-test snapshot is taken.
try:
    import pycares

    pycares.Channel()
except ImportError:
    pass

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: object,
) -> Generator[None, None, None]:
    """Ensure HA discovers ``custom_components/ontario_energy`` in every test."""
    yield


@pytest.fixture
def bill_data_xml() -> bytes:
    """Trimmed real OEB feed, ~10 rows across several distributors."""
    return (FIXTURES_DIR / "bill_data.xml").read_bytes()


@pytest.fixture
def bill_data_minimal_xml() -> bytes:
    """Single-row OEB feed for happy-path tests."""
    return (FIXTURES_DIR / "bill_data_minimal.xml").read_bytes()


@pytest.fixture
def malformed_xml() -> bytes:
    """Intentionally broken XML to exercise parser error paths."""
    return (FIXTURES_DIR / "malformed.xml").read_bytes()


@pytest.fixture
def bill_data_gs_xml() -> bytes:
    """Trimmed General Service < 50 kW feed, ~10 rows."""
    return (FIXTURES_DIR / "bill_data_gs.xml").read_bytes()


@pytest.fixture
def bill_data_gs_minimal_xml() -> bytes:
    """Single-row GS<50 kW feed for happy-path tests."""
    return (FIXTURES_DIR / "bill_data_gs_minimal.xml").read_bytes()


@pytest.fixture
def gas_bill_data_xml() -> bytes:
    """Full OEB gas feed snapshot (3 distributors, 6 rows)."""
    return (FIXTURES_DIR / "gas_bill_data.xml").read_bytes()


@pytest.fixture
def gas_minimal_xml() -> bytes:
    """Single-row gas feed (Enbridge Gas / All / RC=1) for happy-path tests."""
    return (FIXTURES_DIR / "gas_minimal.xml").read_bytes()


@pytest.fixture
def gas_malformed_xml() -> bytes:
    """Intentionally broken gas XML to exercise parser error paths."""
    return (FIXTURES_DIR / "gas_malformed.xml").read_bytes()
