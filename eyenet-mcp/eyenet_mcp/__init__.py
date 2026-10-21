# SPDX-License-Identifier: AGPL-3.0-or-later
"""eyenet-mcp — a thin MCP read lens over the EYENET /v1 API.

The whole job is token economy: call /v1, return terse text (hit lines, compact
records) instead of raw JSON, so the corpus stays out of the model's context
until it asks to open one record. See development/MCP_PLAN.md.
"""
