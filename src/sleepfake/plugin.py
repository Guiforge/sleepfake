from typing import Generator

import pytest

from sleepfake import SleepFake


@pytest.fixture
def sleepfake() -> Generator[SleepFake, None, None]:
    with SleepFake() as sleepfake_:
        yield sleepfake_


def pytest_configure(config: pytest.Config) -> None:
    """Inject documentation."""
    config.addinivalue_line("markers", "sleepfake: mark test to run with SleepFake context manager")
