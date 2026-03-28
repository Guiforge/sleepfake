import asyncio
import re
import sys
import time

import pytest

from sleepfake import SleepFake

SLEEP_DURATION = 4


def test_sync_sleepfake():
    real_start_time = time.time()
    with SleepFake():
        start_time = time.time()
        time.sleep(SLEEP_DURATION)
        end_time = time.time()
        assert end_time - start_time >= SLEEP_DURATION
    real_end_time = time.time()
    assert real_end_time - real_start_time < 1


@pytest.mark.asyncio
async def test_async_sleepfake():
    real_start_time = asyncio.get_running_loop().time()
    with SleepFake():
        start_time = asyncio.get_running_loop().time()
        await asyncio.sleep(SLEEP_DURATION)
        end_time = asyncio.get_running_loop().time()
        assert SLEEP_DURATION <= end_time - start_time <= SLEEP_DURATION + 0.2
    real_end_time = asyncio.get_running_loop().time()
    assert real_end_time - real_start_time < 1


def test_sync_multiple_sleeps_accumulate():
    """Multiple sequential time.sleep calls should each advance frozen time."""
    with SleepFake():
        t0 = time.time()
        time.sleep(2)
        t1 = time.time()
        time.sleep(3)
        t2 = time.time()
        assert t1 - t0 >= 2  # noqa: PLR2004
        assert t2 - t0 >= 5  # noqa: PLR2004


def test_sync_freeze_not_started_before_enter():
    """Bug 5: freeze_time must NOT start before __enter__ is called."""
    sf = SleepFake()
    # Before entering the context, frozen_factory should not be active.
    assert not sf._freeze_started  # noqa: SLF001
    with sf:
        assert sf._freeze_started  # noqa: SLF001
    assert not sf._freeze_started  # noqa: SLF001


def test_sync_context_restores_time_sleep():
    """time.sleep should be restored to the real function after exiting."""
    original = time.sleep
    with SleepFake():
        assert time.sleep is not original
    assert time.sleep is original


def test_sync_zero_sleep():
    """time.sleep(0) should be a no-op and not raise."""
    with SleepFake():
        start = time.time()
        time.sleep(0)
        end = time.time()
    assert end - start < 1


def test_sync_reentrant_context():
    """SleepFake can be used multiple times sequentially without state leakage."""
    for _ in range(3):
        real_start = time.time()
        with SleepFake():
            time.sleep(SLEEP_DURATION)
        assert time.time() - real_start < 1


def test_durations_not_epoch_scale(pytester: pytest.Pytester) -> None:
    """Pytest --durations must not show epoch-scale values when sleepfake is active.

    Freezegun's to_patch mechanism replaces _pytest.timing.perf_counter with a
    frozen stub, producing multi-billion-second durations. SleepFake must pass
    ``ignore=["_pytest.timing"]`` to ``freeze_time()`` so pytest internals keep
    using real timers.
    """
    pytester.makepyfile("""
        import pytest

        @pytest.fixture(autouse=True)
        def _use_sleepfake(sleepfake):
            pass

        def test_with_fake_sleep():
            pass
    """)
    result = pytester.runpytest_subprocess("--durations", "1")
    result.assert_outcomes(passed=1)
    # All reported durations must be well under one second (not epoch-scale).
    for line in result.outlines:
        m = re.match(r"^\s*([\d.]+)s\b", line)
        if m:
            assert float(m.group(1)) < 60.0, f"Epoch-scale duration detected: {line!r}"  # noqa: PLR2004


def test_default_ignore_includes_pytest() -> None:
    """SleepFake should always ignore ``_pytest.timing`` by default."""
    sf = SleepFake()
    configured_ignore = tuple(sf.freeze_time.ignore)
    assert "_pytest.timing" in configured_ignore


def test_custom_ignore_extends_default_ignore() -> None:
    """Custom ignore entries should be merged with the default ignore list."""
    sf = SleepFake(ignore=["my_custom_module"])
    configured_ignore = tuple(sf.freeze_time.ignore)
    assert "_pytest.timing" in configured_ignore
    assert "my_custom_module" in configured_ignore


def test_ini_ignore_applies_to_autouse_sleepfake(pytester: pytest.Pytester) -> None:
    """Configured ignore entries from pytest ini should be used in autouse mode."""
    pytester.makeini("""
        [pytest]
        sleepfake_autouse = true
        sleepfake_ignore =
            helper
    """)
    pytester.makepyfile(
        helper="""
            import time

            def now():
                return time.time()
        """,
        test_ini_ignore="""
            import time
            import helper

            def test_ignored_module_keeps_real_time():
                before = helper.now()
                time.sleep(100)
                after = helper.now()
                assert after - before < 1
        """,
    )
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


def test_conftest_sleepfake_ignore_fixture_applies_to_marker(pytester: pytest.Pytester) -> None:
    """A ``pytest_sleepfake_ignore`` value in conftest.py should affect marker setup."""
    pytester.makeconftest("""
        pytest_sleepfake_ignore = ["helper"]
    """)
    pytester.makepyfile(
        helper="""
            import time

            def now():
                return time.time()
        """,
        test_conftest_ignore="""
            import time
            import pytest
            import helper

            @pytest.mark.sleepfake
            def test_ignored_module_keeps_real_time():
                before = helper.now()
                time.sleep(100)
                after = helper.now()
                assert after - before < 1
        """,
    )
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


def test_cli_ignore_flag_extends_ignore(pytester: pytest.Pytester) -> None:
    """``--sleepfake-ignore MODULE`` CLI flag should extend module ignores in autouse mode."""
    pytester.makeini("""
        [pytest]
        sleepfake_autouse = true
    """)
    pytester.makepyfile(
        helper="""
            import time

            def now():
                return time.time()
        """,
        test_cli_ignore="""
            import time
            import helper

            def test_ignored_module_keeps_real_time():
                before = helper.now()
                time.sleep(100)
                after = helper.now()
                assert after - before < 1
        """,
    )
    result = pytester.runpytest_subprocess("-vvv", "--sleepfake-ignore", "helper")
    result.assert_outcomes(passed=1)


def test_ini_ignore_applies_to_fixture(pytester: pytest.Pytester) -> None:
    """``sleepfake_ignore`` ini option should be respected by the ``sleepfake`` fixture."""
    pytester.makeini("""
        [pytest]
        sleepfake_ignore =
            helper
    """)
    pytester.makepyfile(
        helper="""
            import time

            def now():
                return time.time()
        """,
        test_ini_ignore_fixture="""
            import time
            import helper

            def test_fixture_respects_ignore(sleepfake):
                before = helper.now()
                time.sleep(100)
                after = helper.now()
                assert after - before < 1
        """,
    )
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


def test_conftest_ignore_applies_to_fixture(pytester: pytest.Pytester) -> None:
    """A ``pytest_sleepfake_ignore`` value in conftest.py should be respected by the ``sleepfake`` fixture."""
    pytester.makeconftest("""
        pytest_sleepfake_ignore = ["helper"]
    """)
    pytester.makepyfile(
        helper="""
            import time

            def now():
                return time.time()
        """,
        test_conftest_ignore_fixture="""
            import time
            import helper

            def test_fixture_respects_ignore(sleepfake):
                before = helper.now()
                time.sleep(100)
                after = helper.now()
                assert after - before < 1
        """,
    )
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


def test_no_sleepfake_marker_opts_out_of_autouse(pytester: pytest.Pytester) -> None:
    """``@pytest.mark.no_sleepfake`` should prevent autouse from patching that test."""
    pytester.makeini("""
        [pytest]
        sleepfake_autouse = true
    """)
    pytester.makepyfile("""
        import time
        import pytest

        def test_patched():
            start = time.time()
            time.sleep(100)
            assert time.time() - start >= 100

        @pytest.mark.no_sleepfake
        def test_real_sleep_not_patched():
            start = time.time()
            time.sleep(0.01)          # real sleep — must finish fast
            assert time.time() - start < 5   # would be >=100 if patched
    """)
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=2)


# ---------------------------------------------------------------------------
# asyncio.timeout integration inside a sync context manager (Python 3.11+)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_timeout_raises_when_sleep_exceeds_deadline():
    """asyncio.timeout should fire when SleepFake is entered via sync __enter__."""
    if sys.version_info < (3, 11):
        pytest.skip("asyncio.timeout requires Python 3.11+")

    timed_out = False
    with SleepFake():
        try:
            async with asyncio.timeout(2):  # type: ignore[attr-defined]
                await asyncio.sleep(10)
        except TimeoutError:
            timed_out = True
    assert timed_out


@pytest.mark.asyncio
async def test_sync_timeout_not_raised_when_sleep_within_deadline():
    """No TimeoutError when asyncio.sleep finishes before the asyncio.timeout deadline."""
    if sys.version_info < (3, 11):
        pytest.skip("asyncio.timeout requires Python 3.11+")

    with SleepFake():
        async with asyncio.timeout(10):  # type: ignore[attr-defined]
            await asyncio.sleep(2)  # completes well within the 10 s deadline


# ---------------------------------------------------------------------------
# Fixture-based sync tests
# ---------------------------------------------------------------------------


def test_fixture_sync_sleep(sleepfake: SleepFake) -> None:
    """The ``sleepfake`` fixture patches time.sleep correctly."""
    assert sleepfake.frozen_factory is not None
    start = time.time()
    time.sleep(SLEEP_DURATION)
    end = time.time()
    assert end - start >= SLEEP_DURATION


def test_fixture_sync_multiple_sleeps(sleepfake: SleepFake) -> None:  # noqa: ARG001
    """Sequential sleeps accumulate through the fixture."""
    t0 = time.time()
    time.sleep(2)
    t1 = time.time()
    time.sleep(3)
    t2 = time.time()
    assert t1 - t0 >= 2  # noqa: PLR2004
    assert t2 - t0 >= 5  # noqa: PLR2004


# ---------------------------------------------------------------------------
# @pytest.mark.sleepfake — marker auto-applies SleepFake (pytester)
# ---------------------------------------------------------------------------


def test_marker_applies_sleepfake(pytester: pytest.Pytester) -> None:
    """@pytest.mark.sleepfake should auto-patch time.sleep without a fixture."""
    pytester.makepyfile("""
        import time
        import pytest

        @pytest.mark.sleepfake
        def test_marked():
            start = time.time()
            time.sleep(100)
            end = time.time()
            assert end - start >= 100
    """)
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


def test_marker_async_applies_sleepfake(pytester: pytest.Pytester) -> None:
    """@pytest.mark.sleepfake should auto-patch asyncio.sleep for async tests."""
    pytester.makepyfile("""
        import asyncio
        import pytest

        @pytest.mark.sleepfake
        @pytest.mark.asyncio
        async def test_marked_async():
            start = asyncio.get_running_loop().time()
            await asyncio.sleep(100)
            end = asyncio.get_running_loop().time()
            assert end - start >= 100
    """)
    pytester.makeconftest("""
        import pytest
        pytest_plugins = ["pytest_asyncio"]
    """)
    result = pytester.runpytest_subprocess("-vvv", "-p", "pytest_asyncio")
    result.assert_outcomes(passed=1)


def test_marker_skipped_when_fixture_requested(pytester: pytest.Pytester) -> None:
    """Marker should not double-patch when the sleepfake fixture is also used."""
    pytester.makepyfile("""
        import time
        import pytest

        @pytest.mark.sleepfake
        def test_marker_plus_fixture(sleepfake):
            start = time.time()
            time.sleep(50)
            end = time.time()
            assert end - start >= 50
    """)
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# pytest-timeout integration — real-time watchdog must not be affected
# ---------------------------------------------------------------------------


def test_pytest_timeout_not_affected_by_frozen_time(pytester: pytest.Pytester) -> None:
    """pytest-timeout uses real time; a 100 s fake sleep must not trigger a 5 s timeout."""
    pytester.makepyfile("""
        import time
        import pytest

        @pytest.mark.timeout(5)
        def test_long_fake_sleep(sleepfake):
            time.sleep(100)
    """)
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# sleepfake_autouse ini option
# ---------------------------------------------------------------------------


def test_autouse_ini_applies_sleepfake_globally(pytester: pytest.Pytester) -> None:
    """sleepfake_autouse = true must patch every test without any fixture or marker."""
    pytester.makeini("""
        [pytest]
        sleepfake_autouse = true
    """)
    pytester.makepyfile("""
        import time

        def test_no_fixture():
            start = time.time()
            time.sleep(100)
            assert time.time() - start >= 100

        def test_also_no_fixture():
            start = time.time()
            time.sleep(50)
            assert time.time() - start >= 50
    """)
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=2)


def test_autouse_ini_no_double_patch_with_fixture(pytester: pytest.Pytester) -> None:
    """When autouse is on and the fixture is also requested, only one SleepFake is active."""
    pytester.makeini("""
        [pytest]
        sleepfake_autouse = true
    """)
    pytester.makepyfile("""
        import time

        def test_with_fixture(sleepfake):
            start = time.time()
            time.sleep(10)
            assert time.time() - start >= 10
    """)
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


def test_autouse_ini_no_double_patch_with_marker(pytester: pytest.Pytester) -> None:
    """When autouse is on and a test also has the marker, only one SleepFake is active."""
    pytester.makeini("""
        [pytest]
        sleepfake_autouse = true
    """)
    pytester.makepyfile("""
        import time
        import pytest

        @pytest.mark.sleepfake
        def test_marker_plus_autouse():
            start = time.time()
            time.sleep(10)
            assert time.time() - start >= 10
    """)
    result = pytester.runpytest_subprocess("-vvv")
    result.assert_outcomes(passed=1)


def test_cli_flag_applies_sleepfake_globally(pytester: pytest.Pytester) -> None:
    """``--sleepfake`` CLI flag must patch every test, same as sleepfake_autouse = true."""
    pytester.makepyfile("""
        import time

        def test_no_fixture():
            start = time.time()
            time.sleep(100)
            assert time.time() - start >= 100
    """)
    result = pytester.runpytest_subprocess("-vvv", "--sleepfake")
    result.assert_outcomes(passed=1)


def test_cli_flag_async_test(pytester: pytest.Pytester) -> None:
    """``--sleepfake`` CLI flag must also patch async tests."""
    pytester.makepyfile("""
        import asyncio
        import pytest

        @pytest.mark.asyncio
        async def test_async_no_fixture():
            start = asyncio.get_running_loop().time()
            await asyncio.sleep(100)
            assert asyncio.get_running_loop().time() - start >= 100
    """)
    pytester.makeconftest("""
        import pytest
        pytest_plugins = ["pytest_asyncio"]
    """)
    result = pytester.runpytest_subprocess("-vvv", "--sleepfake", "-p", "pytest_asyncio")
    result.assert_outcomes(passed=1)


def test_autouse_ini_async_test(pytester: pytest.Pytester) -> None:
    """sleepfake_autouse = true must also patch async tests."""
    pytester.makeini("""
        [pytest]
        sleepfake_autouse = true
    """)
    pytester.makepyfile("""
        import asyncio
        import pytest

        @pytest.mark.asyncio
        async def test_async_no_fixture():
            start = asyncio.get_running_loop().time()
            await asyncio.sleep(100)
            assert asyncio.get_running_loop().time() - start >= 100
    """)
    pytester.makeconftest("""
        import pytest
        pytest_plugins = ["pytest_asyncio"]
    """)
    result = pytester.runpytest_subprocess("-vvv", "-p", "pytest_asyncio")
    result.assert_outcomes(passed=1)
