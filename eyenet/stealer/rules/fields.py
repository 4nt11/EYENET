# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canonical field-name vocabulary for the stealer rule DSL.

Every field a rule emits (via `extract.fields`, `extract.columns`,
`extract.paths`, `extract.keys`, `map.rename` destinations, or
`normalize[].field`/`host_to`/`scheme_to`/`tld_to`/`to`) MUST be a member
of `CANONICAL_FIELDS` below.

Why this exists: before v1.3.12.2 three stealer-log rules emitted
`login` and `username` while every combolist rule emitted `user` for
the same concept. The ClickHouse rollup MVs read `fields['login']`
unconditionally, so combolist rows dropped the username dimension and
stealer-log rows did not. The dashboard `unique (host, user, password)`
tile was HLL-counting over the wrong tuple.

The vocabulary is seeded from the catalog as it stood on 2026-11-22.
Adding a new field is a one-line edit here plus the rule change; the
goal is to make that edit a deliberate decision, not a typo. Removing
a field requires auditing readers first (the stealer schema + the FE).

`WILDCARD_DIRECTIVES` holds pseudo-field tokens the engine recognises
specially (e.g. `$key` on keyvalue rules means "emit the source key
verbatim"). They are not real field names.
"""

from __future__ import annotations

from typing import Any

# Seeded from eyenet/stealer/rules/catalog/*.yaml as of v1.3.12.2.
# 182 names: the three renamed stealer-log emissions (login -> user,
# username -> user) are folded in, and the pseudo-token `$key` lives in
# WILDCARD_DIRECTIVES below.
CANONICAL_FIELDS: frozenset[str] = frozenset({
    "account_name",
    "adapter_ips",
    "admin_group",
    "anynet_alias",
    "anynet_fingerprint",
    "anynet_id",
    "anynet_last_relay",
    "anynet_network_id",
    "anynet_private_key_pem",
    "app_hash",
    "arch",
    "auto_login",
    "av",
    "browser",
    "browser_count",
    "build",
    "build_capture_time",
    "build_country",
    "build_date",
    "build_egress_ip",
    "build_elevated",
    "build_id",
    "build_loader_path",
    "build_tag",
    "build_version",
    "candidate",
    "captured_at",
    "city",
    "client_stats_hash",
    "clipboard_item",
    "cookie_count",
    "cookie_domain",
    "cookie_expires_epoch",
    "cookie_include_subdomains",
    "cookie_name",
    "cookie_path",
    "cookie_secure",
    "cookie_value",
    "corporate_marker",
    "country",
    "cpu",
    "cpu_cores",
    "cpu_threads",
    "cpu_vendor",
    "credit_card_count",
    "crypter_storefront",
    "csid_expires",
    "csid_value",
    "ddos_tool",
    "discord_token",
    "domain",
    "download_filename",
    "download_time",
    "download_url",
    "elevated",
    "env_appdata",
    "env_computer_name",
    "env_cpu_arch",
    "env_cpu_count",
    "env_cpu_identifier",
    "env_localappdata",
    "env_logon_server",
    "env_onedrive",
    "env_onedrive_commercial",
    "env_path",
    "env_session_name",
    "env_user_domain",
    "env_user_name",
    "env_user_profile",
    "environment",
    "exfil_at",
    "exodus_created_at",
    "exodus_fiat_unit",
    "exodus_passphrase_system",
    "exodus_passphrase_wrap",
    "exodus_updated_at",
    "exodus_version_created",
    "exodus_version_updated",
    "form_count",
    "form_key",
    "form_submit_url",
    "form_value",
    "gaia_id",
    "gpu",
    "gpu_list",
    "grabber_bytes",
    "guid",
    "host",
    "hostname",
    "http_realm",
    "hw_cpu_count",
    "hw_cpu_product",
    "hw_cpu_threads",
    "hw_cpu_vendor",
    "hw_display",
    "hw_gpu",
    "hw_motherboard_product",
    "hw_motherboard_vendor",
    "hw_ram_size",
    "hwid",
    "identity_type",
    "install_date",
    "install_id",
    "integrity_level",
    "ip",
    "is_duplicate",
    "is_elevated",
    "jwt",
    "keyboards",
    "language",
    "last_login",
    "license_cache_hash",
    "license_expiry",
    "license_name",
    "license_state_store",
    "local_date",
    "local_time",
    "log_date",
    "login_id",
    "ls_domain",
    "ls_key",
    "ls_value",
    "messengers",
    "most_recent",
    "msa_user_id",
    "name",
    "os",
    "os_av_name",
    "os_av_state",
    "os_computer_name",
    "os_domain",
    "os_hostname",
    "os_install_date",
    "os_language",
    "os_local_date",
    "os_netbios",
    "os_timezone",
    "os_user_name",
    "os_version",
    "password",
    "password_b64",
    "password_count",
    "password_enc",
    "password_encoding",
    "password_field",
    "payload_path",
    "persona_name",
    "pid",
    "pm_ext_count",
    "port",
    "process_list",
    "process_name",
    "process_path",
    "profile",
    "protocol",
    "ram",
    "refresh_token",
    "relying_party",
    "remember_password",
    "sample_password",
    "sample_url",
    "sample_user",
    "sandbox",
    "scheme",
    "screen",
    "seco_scheme",
    "seco_vendor",
    "seco_version",
    "security_update_version",
    "service_fingerprint",
    "soft",
    "software_name",
    "ssid_expires",
    "ssid_value",
    "steam_id",
    "steam_jwt",
    "steam_login",
    "steam_persona",
    "sub_value",
    "sum_browser_version",
    "sum_extensions_count",
    "sum_language",
    "sum_last_active",
    "sum_profile_path",
    "sum_search_engine",
    "sum_sync",
    "sum_theme",
    "sum_user_agent",
    "target",
    "tdid_expires",
    "tdid_value",
    "time_created",
    "time_last_used",
    "time_password_changed",
    "time_zone",
    "times_used",
    "timezone",
    "tld",
    "token_type",
    "traffic_source",
    "ui_active_window",
    "ui_adapters",
    "ui_admin_group",
    "ui_admin_rights",
    "ui_av",
    "ui_av_name",
    "ui_build_comment",
    "ui_build_id",
    "ui_build_version",
    "ui_capture_time",
    "ui_city",
    "ui_computer",
    "ui_country",
    "ui_cpu",
    "ui_cpu_arch",
    "ui_cpu_count",
    "ui_domain",
    "ui_egress_ip",
    "ui_elevated",
    "ui_gpu",
    "ui_guid",
    "ui_hwid",
    "ui_integrity",
    "ui_keyboard_lang",
    "ui_keyboards",
    "ui_language",
    "ui_local_time",
    "ui_log_date",
    "ui_machine_guid",
    "ui_memory",
    "ui_os",
    "ui_payload_md5",
    "ui_payload_path",
    "ui_processes",
    "ui_ram_mb",
    "ui_screen",
    "ui_smbios_uuid",
    "ui_software",
    "ui_system_lang",
    "ui_timezone",
    "ui_traffic_affid",
    "ui_uptime_min",
    "ui_user_domain",
    "ui_user_hash",
    "ui_user_lang",
    "ui_user_name",
    "ui_work_dir",
    "ui_zip",
    "uptime_minutes",
    "url",
    "user",
    "user_assembly_lang",
    "user_invite_received_enc",
    "user_license_cache_hash",
    "user_remote_peer_blob",
    "user_screen_height",
    "user_screen_width",
    "user_telemetry_consent",
    "user_ui_lang",
    "username_enc",
    "username_field",
    "value",
    "visit_time",
    "visit_title",
    "visit_url",
    "wallet_count",
    "wallet_ext_count",
    "wants_offline_mode",
    "webmail_email",
    "webmail_provider",
    "zip_code",
})

# Pseudo-tokens the DSL engine interprets specially. Not real emitted
# field names; they tell the engine to derive the name from the source
# (e.g. the keyvalue key, the column header).
WILDCARD_DIRECTIVES: frozenset[str] = frozenset({
    "$key",
})


def rule_emitted_field_names(rule: dict[str, Any]) -> list[tuple[str, str]]:
    """Walk a rule dict and return every (source, name) pair where `name` is
    an emission target. `source` is a short label for the key that carried
    it, so error messages can point at the exact field.

    Covers (per the actual catalog conventions, which differ by key):
      * `extract.fields: [a, b, c]`                 -- list items are dests
      * `extract.columns: {col_index: dest}`        -- VALUES are dests
      * `extract.paths:   {dest: "$.jsonpath"}`     -- KEYS are dests
      * `extract.keys:    {source_key: dest}`       -- VALUES are dests
      * `map.rename:      {src_name: dest_name}`    -- VALUES are dests
      * `normalize[].field` (the field being normalized, always a dest)
      * `normalize[].host_to|scheme_to|tld_to|to`   -- derived dests

    Does NOT return the SOURCE sides (jsonpaths, column indices, source
    key names); only emission destinations.
    """
    out: list[tuple[str, str]] = []
    ex = rule.get("extract") or {}

    for name in ex.get("fields") or []:
        if isinstance(name, str):
            out.append(("extract.fields", name))

    for dst in (ex.get("columns") or {}).values():
        if isinstance(dst, str):
            out.append(("extract.columns", dst))

    # paths convention is DEST: SOURCE_JSONPATH -- walk KEYS, not values.
    for dst in (ex.get("paths") or {}).keys():
        if isinstance(dst, str):
            out.append(("extract.paths", dst))

    for dst in (ex.get("keys") or {}).values():
        if isinstance(dst, str):
            out.append(("extract.keys", dst))

    for dst in ((rule.get("map") or {}).get("rename") or {}).values():
        if isinstance(dst, str):
            out.append(("map.rename", dst))

    for step in rule.get("normalize") or []:
        if not isinstance(step, dict):
            continue
        for k in ("field", "host_to", "scheme_to", "tld_to", "to"):
            v = step.get(k)
            if isinstance(v, str):
                out.append((f"normalize[].{k}", v))

    return out


def validate_rule_fields(rule: dict[str, Any]) -> None:
    """Raise ValueError if any emission target in `rule` is not in the
    canonical vocabulary. Called from `_validate_rule_shape` at rule
    create/update, and from the catalog linter.
    """
    allowed = CANONICAL_FIELDS | WILDCARD_DIRECTIVES
    offenders: list[tuple[str, str]] = []
    for source, name in rule_emitted_field_names(rule):
        if name not in allowed:
            offenders.append((source, name))
    if offenders:
        detail = "; ".join(f"{src}={name!r}" for src, name in offenders)
        rid = rule.get("id", "<unknown>")
        raise ValueError(
            f"rule {rid!r} emits non-canonical field name(s): {detail}. "
            f"Add the name to eyenet/stealer/rules/fields.py CANONICAL_FIELDS if it is a "
            f"deliberate new field, or rename the emission to an existing canonical name."
        )
