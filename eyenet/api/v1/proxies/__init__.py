# SPDX-License-Identifier: AGPL-3.0-or-later
"""Proxy pool + proxy CRUD routers (v1.2.0).

All routers register under the ``proxies`` tag. Scopes:

- ``proxy:read`` baseline on admin + analyst for listing.
- ``proxy:write`` baseline on admin + analyst for CRUD + state flips +
  identity binding.
- ``proxy:admin`` is a GRANT_ONLY_CAPABILITIES scope needed for pool
  create/delete, bulk import, and raw credential reveal.
"""
