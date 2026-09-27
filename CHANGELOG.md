# Changelog

## 2.0.0

### Breaking changes

- **Loop timers now run on the fake clock (autojump).** Inside SleepFake, `asyncio.wait_for`, `asyncio.timeout` and `loop.call_later` fire once the event loop has been idle for 20 ms of real time, instead of waiting in real time (or hanging). Real I/O slower than that under a timeout now times out.
  *Migration:* raise the threshold (`sleepfake_autojump_threshold = "0.5"` in your pytest config, or `SleepFake(autojump_threshold=0.5)`), or restore the 1.x behaviour with `"inf"` / `math.inf`.
- **`time.sleep` / `asyncio.sleep` are no longer `MagicMock`s** while patched. `time.sleep.assert_called_once_with(5)`, `.call_count`, `.mock_calls`... now raise `AttributeError`.
  *Migration:* assert on the clock instead (`time.time()` / `datetime.now()` advanced by the expected amount), or spy inside the context: `with patch("time.sleep", wraps=time.sleep) as spy: ...` then `spy.assert_called_once_with(5)`.
- **Removed attributes:** `SleepFake.sleep_queue`, `SleepFake.sleep_processor`, `SleepFake.process_sleeps`. There is no background task any more.
  *Migration:* none needed for normal use; `aclose()` and `async with` still clean up.
- **Plugin entry point renamed** from `pytest11` to `sleepfake`.
  *Migration:* `-p no:pytest11` becomes `-p no:sleepfake`.
- **Negative `asyncio.sleep` returns immediately** (like the real function) instead of raising `ValueError`. `time.sleep(-1)` still raises.
- **Marker / autouse no longer freeze broader-scope fixtures.** Session-, module- and class-scoped fixtures are set up and torn down on real time; only function-scoped fixtures and the test run on the fake clock.

### Added

- **Autojump for loop timers.** `asyncio.wait_for`, `asyncio.timeout` and `loop.call_later` now fire on the fake clock once the event loop has been idle for `autojump_threshold` real seconds (default `0.02`). Configure it with `SleepFake(autojump_threshold=...)` or the `sleepfake_autojump_threshold` ini option; `0` jumps at once, `math.inf` never jumps. `DEFAULT_AUTOJUMP_THRESHOLD` is exported.
- Free-threaded Python support (3.13t, 3.14t, 3.15t), tested in CI.
- `asyncio.sleep(delay, result)` returns `result`, like the real function.

### Fixed

- A timeout with no `asyncio.sleep` inside (`wait_for(event.wait(), 3)`) hung forever; it now fires.
- `wait_for(asyncio.sleep(10), timeout=5)` left the clock at 10 s; it now stops at 5 s.
- A task woken from `asyncio.sleep` could not sleep again before the clock jumped to the next deadline: periodic tasks were starved, and `asyncio.sleep(0)` could jump to a pending deadline.
- `asyncio.run` called twice inside one sync `with SleepFake()` hung.
- `asyncio.sleep(math.inf)` raised `OverflowError`; it now sleeps until cancelled.
- A sleep being woken when the context exited was never resolved nor cancelled.
- Exiting after the event loop was closed raised `RuntimeError`.
- `from time import sleep` run inside the context kept the fake after exit; nested contexts drove the outer clock; exit overwrote aliases the user had reassigned.
- Reusing a `SleepFake` instance froze time at its construction, not at entry.
- Concurrent `time.sleep` calls from several threads lost time on free-threaded builds.
- With `@pytest.mark.sleepfake` or autouse: combining with an explicit `sleepfake` fixture left `time.sleep` patched for the rest of the session; function-fixture teardown ran with real sleeps; session/module fixtures saw the frozen clock.
- `pytest_sleepfake_ignore` set to a `set` (or any non-list iterable) was ignored; other invalid types are now a `pytest.UsageError`.

For earlier versions, see the [GitHub releases](https://github.com/Guiforge/sleepfake/releases).
