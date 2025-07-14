<!-- Shield Badges -->
<p align="center">
  <img src="./logo.svg" alt="SleepFake Logo" width="120"/>
</p>
<p align="center">
  <a href="https://pypi.org/project/sleepfake/"><img src="https://img.shields.io/pypi/v/sleepfake.svg?color=blue" alt="PyPI version"></a>
  <a href="https://github.com/spulec/freezegun"><img src="https://img.shields.io/badge/dependency-freezegun-blue" alt="freezegun"></a>
  <img src="https://img.shields.io/badge/pytest%20fixture-alpha-orange" alt="pytest fixture alpha"/>
</p>

# 💤 SleepFake: Time Travel for Your Tests

Ever wish your tests could skip the wait? **SleepFake** lets you fake `time.sleep` and `asyncio.sleep` so your tests run at lightning speed—no more wasting time waiting for the clock!

## 🚀 Features

- Instantly skip over `sleep` calls in both sync and async code
- Works with `time.sleep` and `asyncio.sleep`
- Compatible with pytest and pytest-asyncio
- Supports context manager and async context manager usage
- No more slow tests—get results fast!

## ✨ Example Usage

```python
from sleepfake import SleepFake
import time
import asyncio

# Synchronous example
with SleepFake():
    start = time.time()
    time.sleep(10)  # Instantly skipped!
    end = time.time()
    print(f"Elapsed: {end - start:.2f}s")  # Elapsed: 10.00s

# Asynchronous example
async def main():
    async with SleepFake():
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(5)  # Instantly skipped!
        end = asyncio.get_event_loop().time()
        print(f"Elapsed: {end - start:.2f}s")  # Elapsed: 5.00s

asyncio.run(main())
```

## 🧪 Why Use SleepFake?

- **Speed up your test suite**: No more real waiting!
- **Test time-based logic**: Simulate long waits, retries, and timeouts instantly.
- **Fun to use**: Who doesn't love time travel?

## 📦 Installation

```bash
pip install sleepfake
```

## 🤝 Contributing

PRs and issues welcome! Help make testing even more fun.

---

Made with ❤️ and a dash of impatience.

---

> **Note:** SleepFake uses [freezegun](https://github.com/spulec/freezegun) under the hood for time manipulation magic.
