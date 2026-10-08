"""FlareSolverr-backed HTTP client for the forum collector's WAF-bypass path.

Some clearnet boards stack a Cloudflare "managed challenge" (JS/Turnstile) AND an
Anubis proof-of-work in front of every page. Neither httpx nor curl-cffi can clear
the JS/behavioural layer - only a real browser can. FlareSolverr
(https://github.com/FlareSolverr/FlareSolverr, MIT) runs that browser as a sidecar:
we POST it a URL, it drives the browser, solves CF + Anubis, and returns the final
HTML + status + the cleared cookie jar.

This adapter makes FlareSolverr look like the httpx/curl-cffi client the collector
already speaks to: an awaitable ``.get()``/``.post()`` returning an object with
``.status_code`` / ``.text`` / ``.headers``, plus ``.aclose()``. The collector's
``_get``/``_post`` are unchanged. A single long-lived FlareSolverr *session* is
created lazily so the solved cf_clearance/Anubis cookies persist across requests
(re-solving every page is slow and gets you re-challenged); our own warmed jar
(e.g. the MyBB ``mybbuser`` login) is injected on each request so the browser is
authenticated too.

WAF bypass is deliberately a plain on/off per-identity knob (``forum_enable_waf_bypass``),
NOT tied to the evasion/timing preset: a board having a CF challenge says nothing
about whether it rate-limits, so the operator decides independently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

if TYPE_CHECKING:
    from collections.abc import Mapping

# FlareSolverr spins a browser per solve; CF/Anubis typically clears in a few
# seconds but allow headroom. Kept under the collector's _REQUEST_HARD_TIMEOUT so
# the hard deadline still backstops a wedged solve.
_FS_MAX_TIMEOUT_MS = 40_000
_FS_HTTP_TIMEOUT_S = 55.0


class _FSResponse:
    """The minimal response surface the collector's callers touch."""

    __slots__ = ("headers", "status_code", "text")

    def __init__(self, status_code: int, text: str, headers: Mapping[str, str] | None) -> None:
        self.status_code = status_code
        self.text = text
        # httpx.Headers is case-insensitive, matching what _note_rate_limit expects
        # when it reads a Retry-After off a real response.
        self.headers = httpx.Headers(dict(headers) if headers else {})


class FlareSolverrClient:
    """Routes forum requests through a FlareSolverr sidecar.

    ``base_url`` resolves the collector's relative URLs (it hands us
    ``"Forum-Databases?..."``); ``cookies`` is our warmed jar (injected so the
    browser is logged in); ``proxy_uri`` is forwarded to FlareSolverr if set.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        base_url: str,
        cookies: httpx.Cookies,
        proxy_uri: str | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._base = base_url if base_url.endswith("/") else base_url + "/"
        self._domain = urlsplit(base_url).hostname or ""
        self._cookies = [
            {"name": c.name, "value": c.value, "domain": self._domain}
            for c in cookies.jar
            if c.value is not None
        ]
        self._proxy = proxy_uri or None
        self._session_id: str | None = None
        # Talks to the LOCAL sidecar (no WAF between us and it), so plain httpx.
        self._http = httpx.AsyncClient(timeout=_FS_HTTP_TIMEOUT_S)

    async def _command(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._http.post(f"{self._endpoint}/v1", json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if data.get("status") != "ok":
            raise httpx.HTTPError(f"flaresolverr: {data.get('message', data.get('status'))}")
        return data

    async def _ensure_session(self) -> str:
        if self._session_id is not None:
            return self._session_id
        payload: dict[str, Any] = {"cmd": "sessions.create"}
        if self._proxy:
            payload["proxy"] = {"url": self._proxy}
        data = await self._command(payload)
        self._session_id = str(data["session"])
        return self._session_id

    async def _solve(self, cmd: str, url: str, post_data: str | None) -> _FSResponse:
        session = await self._ensure_session()
        payload: dict[str, Any] = {
            "cmd": cmd,
            "url": url,
            "session": session,
            "maxTimeout": _FS_MAX_TIMEOUT_MS,
            "cookies": self._cookies,
        }
        if post_data is not None:
            payload["postData"] = post_data
        data = await self._command(payload)
        sol = data.get("solution", {})
        return _FSResponse(
            int(sol.get("status", 0)),
            sol.get("response", "") or "",
            sol.get("headers"),
        )

    # The collector hands relative URLs (base_url set on the httpx client it thinks
    # it has); FlareSolverr needs absolute, so resolve against base_url.
    async def get(self, url: str, **_: Any) -> _FSResponse:
        return await self._solve("request.get", urljoin(self._base, url), None)

    async def post(self, url: str, *, data: Any = None, **_: Any) -> _FSResponse:
        body = data if isinstance(data, str) else _urlencode(data)
        return await self._solve("request.post", urljoin(self._base, url), body)

    async def aclose(self) -> None:
        if self._session_id is not None:
            try:
                await self._command({"cmd": "sessions.destroy", "session": self._session_id})
            except httpx.HTTPError:
                # Sidecar already reaped the session (restart/TTL) - nothing to free.
                self._session_id = None
        await self._http.aclose()


def _urlencode(data: Any) -> str:
    if not data:
        return ""
    return urlencode(data)
