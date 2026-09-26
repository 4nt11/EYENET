# SPDX-License-Identifier: AGPL-3.0-or-later
"""Incident detection — brag/claim-of-compromise surfacing for the operator.

Threat actors in monitored groups boast about breaches, leaks, intrusions and
ransom. That boast is an evidence gift: a timestamped, actor-attributed claim.

Detection is a tiered cascade, cheap-first:

1. :mod:`eyenet.incidents.prefilter` — a pure, language-neutral STRUCTURAL gate
   (RE2). It fires on universal signals (``.onion``, ``CVE-YYYY-NNNN``,
   credential combos, leak-drop hosts, wallet/IP/hash shapes) that survive
   translation because they are not words. High-recall, cheap; it decides only
   *whether a message is worth adjudicating*, never the verdict.
2. laya — a calibrated multilingual System-1 classifier (added later), run
   alongside the prefilter. High calibrated confidence short-circuits straight
   to extraction; the ambiguous middle escalates to a generative LLM.

The operator triage feed (passive; no in-group footprint) is both the product
and the labeling loop: every confirm/dismiss is a row that calibrates and later
fine-tunes laya. Advisory/flag-only — detection never auto-acts.
"""
