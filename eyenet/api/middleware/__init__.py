# SPDX-License-Identifier: AGPL-3.0-or-later
"""ASGI middleware for the EYENET v1 API."""

from eyenet.api.middleware.evidence_access import evidence_access_dispatch

__all__ = ["evidence_access_dispatch"]
