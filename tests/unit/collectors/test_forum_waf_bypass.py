"""FlareSolverr WAF-bypass client: session reuse, URL resolution, cookie injection,
response adaptation. No network - the sidecar HTTP call is faked."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from eyenet.collectors.forum._flaresolverr import FlareSolverrClient


class _FakeResp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHTTP:
    """Stands in for the httpx client talking to the FlareSolverr sidecar."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def post(self, url: str, *, json: dict[str, Any]) -> _FakeResp:
        self.calls.append(json)
        cmd = json["cmd"]
        if cmd == "sessions.create":
            return _FakeResp({"status": "ok", "session": "sess-1"})
        if cmd == "sessions.destroy":
            return _FakeResp({"status": "ok"})
        # request.get / request.post
        return _FakeResp(
            {
                "status": "ok",
                "solution": {
                    "status": 200,
                    "response": "<html>PwnForums postbit</html>",
                    "headers": {"Content-Type": "text/html"},
                },
            }
        )

    async def aclose(self) -> None:
        self.closed = True


def _client() -> tuple[FlareSolverrClient, _FakeHTTP]:
    cookies = httpx.Cookies()
    cookies.set("mybbuser", "123_abc", domain="pwnforums.st")
    c = FlareSolverrClient(
        endpoint="http://flaresolverr:8191",
        base_url="https://pwnforums.st/",
        cookies=cookies,
    )
    fake = _FakeHTTP()
    c._http = fake  # type: ignore[assignment]
    return c, fake


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_creates_session_once_and_resolves_relative_url() -> None:
    c, fake = _client()
    r1 = await c.get("Forum-Databases?sortby=started")
    r2 = await c.get("Thread-Some-Leak")
    # response adapted to the collector's expected surface
    assert r1.status_code == 200
    assert "postbit" in r1.text
    assert r1.headers.get("content-type") == "text/html"  # case-insensitive
    # exactly one session created, reused for both gets
    assert [k["cmd"] for k in fake.calls] == ["sessions.create", "request.get", "request.get"]
    gets = [k for k in fake.calls if k["cmd"] == "request.get"]
    assert gets[0]["url"] == "https://pwnforums.st/Forum-Databases?sortby=started"
    assert gets[0]["session"] == "sess-1"
    # our warmed jar is injected so the browser is logged in
    assert {"name": "mybbuser", "value": "123_abc", "domain": "pwnforums.st"} in gets[0]["cookies"]
    assert r2.status_code == 200


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aclose_destroys_session_and_closes_http() -> None:
    c, fake = _client()
    await c.get("/")
    await c.aclose()
    assert {"cmd": "sessions.destroy", "session": "sess-1"} in [
        {k: v for k, v in call.items() if k in ("cmd", "session")} for call in fake.calls
    ]
    assert fake.closed is True


@pytest.mark.unit
def test_challenge_cookies_are_not_injected() -> None:
    """FlareSolverr mints cf_clearance/Anubis itself (right IP/UA/TLS); replaying our
    stale foreign tokens fights its session. Only board-login cookies get injected."""
    cookies = httpx.Cookies()
    cookies.set("mybbuser", "123_abc", domain="pwnforums.st")
    cookies.set("sid", "deadbeef", domain="pwnforums.st")
    cookies.set("cf_clearance", "STALE", domain="pwnforums.st")
    cookies.set("anubis.pwnforums-auth", "eyJ...", domain="pwnforums.st")
    c = FlareSolverrClient(
        endpoint="http://flaresolverr:8191", base_url="https://pwnforums.st/", cookies=cookies
    )
    names = {ck["name"] for ck in c._cookies}
    assert names == {"mybbuser", "sid"}
    assert "cf_clearance" not in names
    assert not any(n.startswith("anubis") for n in names)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_ok_status_raises() -> None:
    c, fake = _client()

    async def _boom(url: str, *, json: dict[str, Any]) -> _FakeResp:
        return _FakeResp({"status": "error", "message": "challenge not solved"})

    fake.post = _boom  # type: ignore[method-assign]
    with pytest.raises(httpx.HTTPError, match="challenge not solved"):
        await c.get("/")
