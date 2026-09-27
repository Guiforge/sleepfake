import asyncio
import datetime
import importlib.metadata
import re
import sys
import time
import types

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
        assert t1 - t0 >= 2
        assert t2 - t0 >= 5


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
            assert float(m.group(1)) < 60.0, f"Epoch-scale duration detected: {line!r}"


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
    assert t1 - t0 >= 2
    assert t2 - t0 >= 5


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


# ---------------------------------------------------------------------------
# pytest-timeout compatibility
# ---------------------------------------------------------------------------


def test_pytest_timeout_in_default_ignore() -> None:
    """``pytest_timeout`` must be in DEFAULT_IGNORE so session-expiry uses real clocks."""
    from sleepfake import DEFAULT_IGNORE  # noqa: PLC0415

    assert "pytest_timeout" in DEFAULT_IGNORE


def test_session_timeout_not_triggered_by_fake_sleep(pytester: pytest.Pytester) -> None:
    """Advancing frozen time must not cause pytest-timeout's session timeout to fire.

    pytest-timeout stores ``expire_time = time.time() + session_timeout`` at
    configure time, then checks ``time.time() > expire_time`` after each test.
    Without ``pytest_timeout`` in the freezegun ignore list the frozen clock
    (advanced by SleepFake) would feed both sides of that comparison, causing a
    spurious session-timeout failure whenever a test fakes a sleep longer than
    the configured session-timeout value.
    """
    pytester.makeini("""
        [pytest]
        session_timeout = 5
    """)
    pytester.makepyfile("""
        import time

        def test_fake_sleep_100s(sleepfake):
            # advances frozen time by 100 s; real wall-clock time stays < 1 ms
            time.sleep(100)
            assert time.time() - time.time() == 0   # just exercise frozen clock
    """)
    result = pytester.runpytest_subprocess("-v")
    # The test must pass without a session-timeout failure.
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# Error-path coverage for core.py
# ---------------------------------------------------------------------------


def test_mock_sleep_negative_raises() -> None:
    """mock_sleep raises ValueError for negative sleep duration."""
    with SleepFake() as sf, pytest.raises(ValueError, match="non-negative"):
        sf.mock_sleep(-1)


def test_mock_sleep_outside_context_raises() -> None:
    """mock_sleep raises RuntimeError when frozen_factory is not initialised."""
    sf = SleepFake()
    with pytest.raises(RuntimeError, match="outside SleepFake context"):
        sf.mock_sleep(1)


# ---------------------------------------------------------------------------
# Broad patching — module-level aliases (``from time import sleep``)
# ---------------------------------------------------------------------------


def test_broad_patch_time_sleep_module_alias() -> None:
    """SleepFake patches module-level ``from time import sleep`` aliases in sys.modules."""
    original_sleep = time.sleep  # capture before any context is active
    fake_mod = types.ModuleType("_sleepfake_test_broad_sync")
    fake_mod.__dict__["sleep"] = original_sleep  # simulates ``from time import sleep``
    sys.modules["_sleepfake_test_broad_sync"] = fake_mod
    try:
        with SleepFake():
            # The alias must have been replaced with a mock (not the original builtin).
            assert fake_mod.sleep is not original_sleep  # type: ignore[attr-defined]
            t0 = time.time()
            fake_mod.sleep(10)  # type: ignore[attr-defined]
            assert time.time() - t0 >= 10
        # After exit the alias is restored.
        assert fake_mod.sleep is original_sleep  # type: ignore[attr-defined]
    finally:
        sys.modules.pop("_sleepfake_test_broad_sync", None)


def test_broad_patch_restores_alias_on_exception() -> None:
    """Module-level aliases are restored even when the context body raises."""
    fake_mod = types.ModuleType("_sleepfake_test_broad_exc")
    fake_mod.__dict__["sleep"] = time.sleep
    sys.modules["_sleepfake_test_broad_exc"] = fake_mod
    try:
        with pytest.raises(RuntimeError), SleepFake():
            raise RuntimeError("boom")
        assert fake_mod.sleep is time.sleep  # type: ignore[attr-defined]
    finally:
        sys.modules.pop("_sleepfake_test_broad_exc", None)


def test_broad_patch_does_not_patch_local_variable() -> None:
    """A local variable binding is NOT patched (not visible in sys.modules)."""
    original_sleep = time.sleep
    local_sleep = time.sleep  # bound before context entry — not patchable
    with SleepFake():
        # local_sleep still references the original real function
        assert local_sleep is original_sleep
        # But the global time.sleep has been patched inside the context
        assert time.sleep is not original_sleep


def test_reused_instance_starts_from_current_time() -> None:
    """Re-entering the same SleepFake freezes at the current time, not construction time."""
    sf = SleepFake()
    with sf:
        pass
    time.sleep(0.05)  # real sleep: SleepFake is not active here
    before_second_entry = datetime.datetime.now(tz=datetime.timezone.utc)
    with sf:
        assert datetime.datetime.now(tz=datetime.timezone.utc) >= before_second_entry


def test_entry_point_is_named_sleepfake() -> None:
    """The pytest11 entry point is named ``sleepfake`` so ``-p no:sleepfake`` works."""
    names = {ep.name for ep in importlib.metadata.entry_points(group="pytest11")}
    assert "sleepfake" in names


def test_broad_patch_skips_non_module_entries_in_sys_modules() -> None:
    """Non-module objects in ``sys.modules`` are left alone instead of crashing the scan."""
    sentinel = object()
    sys.modules["_sleepfake_test_not_a_module"] = sentinel  # ty: ignore[invalid-assignment]
    try:
        with SleepFake():
            time.sleep(1)
        assert sys.modules["_sleepfake_test_not_a_module"] is sentinel
    finally:
        sys.modules.pop("_sleepfake_test_not_a_module", None)


def _module_with_sleep_alias(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__["sleep"] = time.sleep  # simulates ``from time import sleep``
    sys.modules[name] = mod
    return mod


def test_alias_imported_inside_context_is_restored() -> None:
    """``from time import sleep`` run inside the context does not keep the fake after exit."""
    real_sleep = time.sleep
    try:
        with SleepFake():
            late = _module_with_sleep_alias("_sleepfake_test_late_import")
            assert late.sleep is not real_sleep
        assert late.sleep is real_sleep
    finally:
        sys.modules.pop("_sleepfake_test_late_import", None)


def test_user_reassignment_inside_context_is_kept() -> None:
    """Exit only restores attributes that still hold the fake."""
    mod = _module_with_sleep_alias("_sleepfake_test_reassign")

    def custom_sleep(_: float) -> None:
        pass

    try:
        with SleepFake():
            mod.__dict__["sleep"] = custom_sleep
        assert mod.sleep is custom_sleep
    finally:
        sys.modules.pop("_sleepfake_test_reassign", None)


def test_nested_contexts_drive_the_inner_clock() -> None:
    """In nested contexts, module aliases advance the innermost clock and are restored LIFO."""
    real_sleep = time.sleep
    mod = _module_with_sleep_alias("_sleepfake_test_nested")
    try:
        with SleepFake():
            outer_t0 = datetime.datetime.now(tz=datetime.timezone.utc)
            outer_sleep = mod.sleep
            with SleepFake():
                t0 = datetime.datetime.now(tz=datetime.timezone.utc)
                mod.sleep(10)
                time.sleep(5)
                assert (datetime.datetime.now(tz=datetime.timezone.utc) - t0).total_seconds() == 15
            assert mod.sleep is outer_sleep
            assert time.sleep is outer_sleep
            assert datetime.datetime.now(tz=datetime.timezone.utc) == outer_t0
        assert mod.sleep is real_sleep
        assert time.sleep is real_sleep
    finally:
        sys.modules.pop("_sleepfake_test_nested", None)


@pytest.mark.parametrize("mode", [["--sleepfake"], []])
def test_marker_or_autouse_with_nested_fixture_restores_sleep(
    pytester: pytest.Pytester, mode: list[str]
) -> None:
    """Marker/autouse plus an explicit ``sleepfake`` request exits cleanly and restores sleep."""
    pytester.makepyfile("""
        import time
        import pytest

        @pytest.mark.sleepfake
        def test_1(request):
            request.getfixturevalue("sleepfake")
            time.sleep(1)

        @pytest.mark.no_sleepfake
        def test_2():
            assert "built-in" in repr(time.sleep)
    """)
    result = pytester.runpytest_subprocess("-p", "no:randomly", *mode)
    result.assert_outcomes(passed=2)


@pytest.mark.parametrize("mode", [["--sleepfake"], []])
def test_function_fixture_teardown_is_faked(pytester: pytest.Pytester, mode: list[str]) -> None:
    """Sleeps in a function fixture's teardown are faked under the marker and autouse."""
    pytester.makepyfile("""
        import time
        import pytest

        @pytest.fixture
        def slow_teardown():
            yield
            assert "built-in" not in repr(time.sleep)
            time.sleep(30)

        @pytest.mark.sleepfake
        def test_uses_fixture(slow_teardown):
            pass
    """)
    result = pytester.runpytest_subprocess(*mode)
    result.assert_outcomes(passed=1)


def test_session_fixture_stays_on_real_clock_in_autouse(pytester: pytest.Pytester) -> None:
    """Broader-scope fixtures are set up and torn down outside the frozen clock."""
    pytester.makepyfile("""
        import time
        import pytest

        @pytest.fixture(scope="session")
        def budget():
            start = time.monotonic()
            yield
            elapsed = time.monotonic() - start
            assert 0 <= elapsed < 60, elapsed

        def test_uses_budget(budget):
            time.sleep(1000)
    """)
    result = pytester.runpytest_subprocess("--sleepfake")
    result.assert_outcomes(passed=1)


@pytest.mark.parametrize(
    "value", ['"helper"', '{"helper"}', '("helper",)'], ids=["str", "set", "tuple"]
)
def test_conftest_ignore_accepts_str_and_iterables(pytester: pytest.Pytester, value: str) -> None:
    """``pytest_sleepfake_ignore`` accepts a string or any iterable of strings."""
    pytester.makeconftest(f"pytest_sleepfake_ignore = {value}")
    pytester.makepyfile(
        helper="""
            import time

            def now():
                return time.time()
        """,
        test_it="""
            import time
            import helper

            def test_ignored(sleepfake):
                before = helper.now()
                time.sleep(100)
                assert helper.now() - before < 1
        """,
    )
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)


def test_conftest_ignore_rejects_other_types(pytester: pytest.Pytester) -> None:
    """A non-string, non-iterable ``pytest_sleepfake_ignore`` is a usage error."""
    pytester.makeconftest("pytest_sleepfake_ignore = 42")
    pytester.makepyfile("""
        def test_it(sleepfake):
            pass
    """)
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*pytest_sleepfake_ignore must be a str or an iterable*"])


def test_conftest_ignore_only_applies_to_its_subtree(pytester: pytest.Pytester) -> None:
    """A sibling directory's conftest ignore list does not leak into other directories."""
    pytester.makepyfile(
        helper="""
            import time

            def now():
                return time.time()
        """
    )
    sub_a = pytester.mkpydir("sub_a")
    sub_a.joinpath("conftest.py").write_text('pytest_sleepfake_ignore = ["helper"]\n')
    sub_a.joinpath("test_a.py").write_text(
        "import time\n"
        "import helper\n\n"
        "def test_ignored(sleepfake):\n"
        "    before = helper.now()\n"
        "    time.sleep(100)\n"
        "    assert helper.now() - before < 1\n"
    )
    pytester.mkpydir("sub_b").joinpath("test_b.py").write_text(
        "import time\n"
        "import helper\n\n"
        "def test_not_ignored(sleepfake):\n"
        "    before = helper.now()\n"
        "    time.sleep(100)\n"
        "    assert helper.now() - before >= 100\n"
    )
    result = pytester.runpytest_subprocess("-p", "no:randomly")
    result.assert_outcomes(passed=2)
