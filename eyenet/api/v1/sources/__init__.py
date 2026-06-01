# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sources + SourceDomains API route group (M9.D1, API_PLAN §3.8 / §4.13).

One operation per ``api_<verb>_<noun>.py``; routers are mounted in
``eyenet/api/v1/__init__.py``. See ``_detail.py`` for the shared
:class:`SourceDetail` projection used by the get/create/update handlers.
"""
