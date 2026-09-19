"""Self-check for /mc link code resolution.

Run: python3 tools/test_mc_link_resolve_token.py

Verifies that resolve_token tells the three failure modes apart. They used to
collapse into one "invalid or expired code", which made a wrong api_url or a
mismatched shared secret look like the player mistyped their code.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assets.mc_link import resolve_token  # noqa: E402
from assets import mc_link as mc_link_mod  # noqa: E402


class _Resp:
    def __init__(self, status):
        self.status = status

    async def json(self):
        return {"uuid": "0000-uuid", "name": "Alice"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self, status):
        self.status = status

    def get(self, url, **kwargs):
        if self.status == "boom":
            raise OSError("connection refused")
        return _Resp(self.status)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


async def main():
    cases = [
        (200, None),            # server knows the code
        (404, "not_found"),     # code wrong or expired — the player's problem
        (401, "unauthorized"),  # shared secret mismatch — the admin's problem
        (403, "unauthorized"),
        (500, "unreachable"),
        ("boom", "unreachable"),  # connection refused / timeout
    ]
    for status, want in cases:
        mc_link_mod.aiohttp.ClientSession = lambda *a, s=status, **k: _Session(s)
        data, err = await resolve_token("http://mc.example:4321", "secret", "noodle1")
        assert err == want, f"status {status}: got {err!r}, want {want!r}"
        assert (data is not None) == (want is None), f"status {status}: unexpected data {data!r}"

    print(f"mc_link resolve_token OK — {len(cases)} cases passed")


if __name__ == "__main__":
    asyncio.run(main())
