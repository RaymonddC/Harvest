import dataclasses
import datetime as dt

import pytest

from app import seed_data
from app.config import get_settings
from app.store import MemoryStore

PLAN_START = dt.date(2026, 10, 12)


@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(get_settings(), plan_start=PLAN_START, store_backend="memory",
                               seed_on_start=False, static_dir=None, auth_required=False,
                               target_kg_per_week=100_000, gap_tolerance=0.2, weeks=5,
                               max_call_attempts=2)


@pytest.fixture
def store(settings):
    s = MemoryStore()
    seed_data.load_seed(s, settings)
    return s
