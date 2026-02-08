"""Shared fixtures for labyrinth tests."""

import pytest
from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog
from spec_manager.labyrinth.core.worker_pool import WorkerPool
from spec_manager.labyrinth.engine.registry import RuleRegistry
from spec_manager.labyrinth.integration.pipeline import Pipeline


@pytest.fixture
def bus():
    return AsyncMessageBus()


@pytest.fixture
def event_log():
    return EventLog()


@pytest.fixture
def worker_pool():
    wp = WorkerPool(max_workers=2)
    yield wp
    wp.shutdown()


@pytest.fixture
def registry():
    return RuleRegistry()


@pytest.fixture
def pipeline():
    p = Pipeline()
    yield p
    p.shutdown()
