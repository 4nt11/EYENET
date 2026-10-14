# SPDX-License-Identifier: AGPL-3.0-or-later
"""Indicator-rule CRUD routes (Wazuh-style tunable extraction ruleset).

Clearance mirrors collector config: ``read:collectors`` to list, ``write:collectors``
to create/patch, ``admin:collectors`` to delete. Disabling or deleting a rule
changes what the collectors extract corpus-wide, so it is an operator-config action,
not a routine analyst one.
"""
