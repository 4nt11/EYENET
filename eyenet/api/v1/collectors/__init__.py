# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collectors API route group (M9.D2, API_PLAN §3.9 / §4.11).

One operation per ``api_<verb>_<noun>.py``; routers are mounted in
``eyenet/api/v1/__init__.py``. NOTE: ``/collectors/health`` must mount before
``/collectors/{collector_id}`` so the literal isn't parsed as a UUID path param.
"""
