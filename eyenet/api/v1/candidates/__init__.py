# SPDX-License-Identifier: AGPL-3.0-or-later
"""GroupCandidate triage API route group (M9.D3, API_PLAN §3.9 / §4.12).

One operation per ``api_<verb>_<noun>.py``; routers are mounted in
``eyenet/api/v1/__init__.py``. ``_detail.py`` builds the shared
:class:`CandidateDetail`. Eligibility is a STUB (see
``eyenet/services/discovery/eligibility.py``); approve does not gate on it.
"""
