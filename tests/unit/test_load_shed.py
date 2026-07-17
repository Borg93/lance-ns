"""Load-shed middleware — caps concurrent Arrow-IPC writes, shedding the overflow with 429 (P5).

Driven at the ASGI layer (not via TestClient, which is synchronous) so overlap is deterministic: one write is
held in flight while a second is issued, proving the cap sheds the second BEFORE its body is buffered.
"""

from __future__ import annotations

import asyncio

from catalog.api.load_shed import WriteConcurrencyLimitMiddleware
from starlette.types import Message, Receive, Scope, Send


def _scope(method: str, path: str) -> Scope:
    return {"type": "http", "method": method, "path": path, "headers": []}


async def _drive(mw: WriteConcurrencyLimitMiddleware, scope: Scope) -> int:
    """Run one request through the middleware; return the HTTP status the middleware/app emitted."""
    status = 0

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: Message) -> None:
        nonlocal status
        if msg["type"] == "http.response.start":
            status = int(msg["status"])

    await mw(scope, receive, send)
    return status


def test_write_over_cap_is_shed_with_429_before_the_body() -> None:
    async def scenario() -> tuple[int, int, int]:
        release = asyncio.Event()
        entered = asyncio.Event()
        calls = 0

        async def app(_scope_: Scope, _receive: Receive, send: Send) -> None:
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()  # hold the one slot in flight
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = WriteConcurrencyLimitMiddleware(app, max_concurrent=1)
        # request 1 acquires the only slot and blocks inside app
        t1 = asyncio.create_task(_drive(mw, _scope("POST", "/v1/table/t/insert")))
        await entered.wait()  # inflight is now 1
        # request 2 finds the cap full → 429, and the app is NOT entered a second time (shed before body)
        code2 = await _drive(mw, _scope("POST", "/v1/table/t/merge_insert"))
        release.set()
        code1 = await t1
        return code1, code2, calls

    code1, code2, calls = asyncio.run(scenario())
    assert code2 == 429, "the write over the concurrency cap must be shed"
    assert code1 == 200, "the in-flight write completes normally"
    assert calls == 1, "the shed request must NOT reach the app (shed before the body is buffered)"


def test_reads_and_non_bulk_writes_are_not_gated() -> None:
    # A read (GET) and /commit (a small metadata op) must pass through even while a write slot is held.
    async def scenario() -> tuple[int, int]:
        release = asyncio.Event()
        entered = asyncio.Event()

        async def app(scope: Scope, _receive: Receive, send: Send) -> None:
            if str(scope["path"]).endswith("/insert"):
                entered.set()
                await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = WriteConcurrencyLimitMiddleware(app, max_concurrent=1)
        t1 = asyncio.create_task(_drive(mw, _scope("POST", "/v1/table/t/insert")))
        await entered.wait()  # the one write slot is held in flight
        get_code = await _drive(mw, _scope("GET", "/v1/table/t"))
        commit_code = await _drive(mw, _scope("POST", "/v1/table/t/commit"))
        release.set()
        await t1
        return get_code, commit_code

    get_code, commit_code = asyncio.run(scenario())
    assert get_code == 200 and commit_code == 200, "reads + non-bulk writes must never be shed"


def test_zero_disables_the_limit() -> None:
    async def scenario() -> int:
        async def app(_scope_: Scope, _receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = WriteConcurrencyLimitMiddleware(app, max_concurrent=0)  # 0 => disabled (pre-P5 behavior)
        return await _drive(mw, _scope("POST", "/v1/table/t/insert"))

    assert asyncio.run(scenario()) == 200
