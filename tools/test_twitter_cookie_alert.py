"""Self-check for the X (Twitter) cookie health alert.

Run: python3 tools/test_twitter_cookie_alert.py

Verifies that TwitterPostTask._check_cookies alerts once on expiry, once on recovery,
and stays quiet while the state is unchanged, unknown (no cookies) or inconclusive.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assets import tasks as tasks_mod  # noqa: E402


async def main():
    task = tasks_mod.TwitterPostTask.__new__(tasks_mod.TwitterPostTask)
    task.bot = None
    task._cookies_ok = True

    sent = []

    async def _capture(embed):
        sent.append(embed.title)

    task._send_operator_alert = _capture  # type: ignore

    statuses = []
    tasks_mod.twitter_api.verify_cookies = lambda: _returns(statuses.pop(0))  # type: ignore

    async def run(status):
        statuses.append(status)
        await task._check_cookies()

    await run(True)                     # already ok -> no alert
    assert sent == [], sent
    await run(False)                    # expired -> one alert
    assert sent == ["X cookies expired"], sent
    await run(False)                    # still expired -> no repeat
    assert sent == ["X cookies expired"], sent
    await run(None)                     # cookies removed / inconclusive -> no alert
    assert sent == ["X cookies expired"], sent
    await run(True)                     # recovered -> one alert
    assert sent == ["X cookies expired", "X cookies restored"], sent

    print("ok")


async def _returns(value):
    return value


if __name__ == "__main__":
    asyncio.run(main())
