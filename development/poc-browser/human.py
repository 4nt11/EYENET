# poc-browser: human-input primitives (dependency-free).
#
# The point is NOT perfect realism — it's to erase the dead giveaways of
# automation: teleporting cursors, constant-velocity moves, pixel-perfect
# clicks, zero dwell, metronome timing. Everything here is randomized and eased
# so a client-side scorer sees a distribution that overlaps a human's.
#
# Pure stdlib so it runs (and self-tests) with no browser/Tor. The async helpers
# take a Playwright `page` (typed loosely) and drive its mouse/keyboard.
from __future__ import annotations

import asyncio
import math
import random
from typing import Any

Point = tuple[float, float]


def _rand_control(p0: Point, p1: Point, spread: float) -> Point:
    """A control point off the p0->p1 line — the 'bow' of the curve.

    Offset perpendicular to the straight line by a fraction of its length, so
    longer moves bow more (as a real hand does), with a random side + amount.
    """
    (x0, y0), (x1, y1) = p0, p1
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy) or 1.0
    # unit perpendicular
    px, py = -dy / dist, dx / dist
    offset = random.uniform(-spread, spread) * dist  # noqa: S311 - not crypto
    # also jitter along the line so the two controls aren't symmetric
    t = random.uniform(0.2, 0.8)  # noqa: S311
    bx, by = x0 + dx * t, y0 + dy * t
    return (bx + px * offset, by + py * offset)


def bezier_path(p0: Point, p1: Point, steps: int = 40, spread: float = 0.18) -> list[Point]:
    """Cubic bézier from p0 to p1 with two randomized control points.

    Endpoints are exact; the interior bows off-axis so the path is curved, not a
    ruler line. `steps` points, ease handled by the caller's timing.
    """
    c1 = _rand_control(p0, p1, spread)
    c2 = _rand_control(p0, p1, spread)
    out: list[Point] = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1 - t
        # cubic bézier basis
        x = mt**3 * p0[0] + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * p1[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * p1[1]
        out.append((x, y))
    return out


def _ease_delays(n: int, total: float) -> list[float]:
    """Per-step sleeps summing ~total, slow at both ends (ease-in-out) + jitter.

    A real move accelerates then decelerates; constant step timing is a tell.
    """
    raw = []
    for i in range(n):
        t = i / max(n - 1, 1)
        # ease-in-out weight: fast in the middle, slow at the ends
        w = 0.5 - 0.5 * math.cos(2 * math.pi * t)  # 0..1..0
        raw.append(1.0 - 0.7 * w + random.uniform(0, 0.3))  # noqa: S311
    s = sum(raw) or 1.0
    return [r / s * total for r in raw]


async def human_move(page: Any, to: Point, start: Point | None = None, *, total: float | None = None) -> Point:
    """Move the cursor to `to` along a bézier with eased, jittered timing.

    Returns the end point so callers can chain. `total` is the move duration in
    seconds (defaults to a distance-scaled human value).
    """
    frm = start or (random.uniform(0, 400), random.uniform(0, 300))  # noqa: S311
    dist = math.hypot(to[0] - frm[0], to[1] - frm[1])
    steps = max(12, min(60, int(dist / 12)))
    pts = bezier_path(frm, to, steps=steps)
    dur = total if total is not None else min(1.6, max(0.25, dist / 900) + random.uniform(0.05, 0.25))  # noqa: S311
    for (x, y), d in zip(pts, _ease_delays(len(pts), dur), strict=False):
        await page.mouse.move(x, y)
        await asyncio.sleep(d)
    return to


async def human_click(page: Any, to: Point, start: Point | None = None) -> Point:
    """Move to a point, settle, then click with a human press duration."""
    end = await human_move(page, to, start)
    await asyncio.sleep(random.uniform(0.04, 0.18))  # noqa: S311 - pre-click settle
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.05, 0.14))  # noqa: S311 - press-release gap
    await page.mouse.up()
    return end


async def human_scroll(page: Any, total_px: int, *, down: bool = True) -> None:
    """Scroll `total_px` in human chunks: varied deltas + reading pauses, not one jump."""
    remaining = total_px
    sign = 1 if down else -1
    while remaining > 0:
        chunk = min(remaining, random.randint(90, 320))  # noqa: S311 - wheel notch sizes vary
        # a wheel notch is a few quick deltas, not one big one
        notches = random.randint(2, 5)  # noqa: S311
        for _ in range(notches):
            await page.mouse.wheel(0, sign * (chunk // notches))
            await asyncio.sleep(random.uniform(0.02, 0.09))  # noqa: S311
        remaining -= chunk
        # occasional reading pause mid-scroll
        if random.random() < 0.35:  # noqa: S311
            await asyncio.sleep(random.uniform(0.6, 2.4))  # noqa: S311
        else:
            await asyncio.sleep(random.uniform(0.15, 0.5))  # noqa: S311


async def human_dwell(kind: str = "glance") -> float:
    """Sleep a human amount. 'glance' (scan a list) vs 'read' (a thread/post).

    Lognormal-ish: most dwells short, a long tail of genuinely-reading pauses.
    Returns the slept seconds (for logging).
    """
    base = {"glance": 2.2, "read": 9.0, "think": 4.0}.get(kind, 2.2)
    secs = random.lognormvariate(math.log(base), 0.5)  # noqa: S311
    secs = max(0.5, min(secs, base * 4))
    await asyncio.sleep(secs)
    return secs


async def human_type(page: Any, selector: str, text: str) -> None:
    """Type per-character with human inter-key delays + occasional hesitation."""
    await page.click(selector)
    for ch in text:
        await page.type(selector, ch, delay=0)
        await asyncio.sleep(random.uniform(0.04, 0.18))  # noqa: S311
        if random.random() < 0.06:  # noqa: S311 - a brief think mid-word/phrase
            await asyncio.sleep(random.uniform(0.3, 1.1))  # noqa: S311


def _selfcheck() -> None:
    """Offline sanity for the motion math — no browser/Tor needed."""
    p0, p1 = (10.0, 10.0), (800.0, 420.0)
    path = bezier_path(p0, p1, steps=40)
    assert len(path) == 41, len(path)
    # endpoints exact (bézier interpolates its ends)
    assert path[0] == p0 and abs(path[-1][0] - p1[0]) < 1e-6 and abs(path[-1][1] - p1[1]) < 1e-6
    # curved: path length exceeds the straight-line distance
    straight = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    length = sum(
        math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        for i in range(len(path) - 1)
    )
    assert length > straight, (length, straight)
    # eased timing sums to the target and is slower at the ends than the middle
    delays = _ease_delays(41, 1.0)
    assert abs(sum(delays) - 1.0) < 1e-6, sum(delays)
    assert delays[0] > delays[len(delays) // 2] and delays[-1] > delays[len(delays) // 2]
    print(f"OK  bezier={len(path)}pts  curve_overshoot={length / straight:.3f}x  "
          f"ease[end/mid]={delays[0] / delays[len(delays) // 2]:.2f}")


if __name__ == "__main__":
    _selfcheck()
