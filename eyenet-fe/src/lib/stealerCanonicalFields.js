// Canonical field layer for stealer records. Each extracted record
// carries a Map<string,string> `fields` dict whose keys are whatever
// the rule author named them (env_user_name, os_user_name, user, ...).
// This module declares the canonical vocabulary and the per-field
// alias list, so downstream views (drawer tabs, exports, dashboards)
// can read a stable schema regardless of which rule produced the row.
//
// Wazuh-decoder analog: Wazuh ships fixed-name decoded fields (srcip,
// srcuser, program_name, ...) and treats custom fields as extras. We
// do the same thing in reverse direction: canonical names are what the
// UI consumes; raw capture names are the rule-author surface.
//
// The follow-up formalization moves this map INTO each rule's YAML
// (field_map: {capture: canonical.name}) and makes gotractor emit
// canonical keys at extraction time. Until then, this JS applies the
// mapping on the client at render time.

// Dotted namespace, stays flat in record.fields. Pick one canonical
// form per concept and never add a second; if a new synonym appears,
// add it to the alias array.
export const CANONICAL_FIELDS = {
  // Machine identity + hardware fingerprint. The System drawer tab
  // renders this group as its machine profile panel.
  host: {
    'host.computer':      ['env_computer_name', 'os_computer_name', 'os_netbios', 'computer_name', 'ui_computer'],
    'host.user':          ['env_user_name', 'os_user_name', 'user_name', 'user', 'username', 'ui_user_name'],
    'host.domain':        ['env_user_domain', 'user_domain', 'domain'],
    'host.hostname':      ['os_hostname', 'hostname'],
    'host.os':            ['os_version', 'os', 'ui_os'],
    'host.os_language':   ['os_language', 'language', 'locale'],
    'host.os_install':    ['os_install_date', 'install_date'],
    'host.cpu':           ['hw_cpu_product', 'env_cpu_identifier', 'cpu', 'cpu_name'],
    'host.cpu_vendor':    ['hw_cpu_vendor', 'cpu_vendor'],
    'host.cpu_arch':      ['env_cpu_arch', 'cpu_arch'],
    'host.cpu_count':     ['env_cpu_count', 'cpu_count', 'hw_cpu_count'],
    'host.cpu_threads':   ['hw_cpu_threads', 'cpu_threads'],
    'host.gpu':           ['hw_gpu', 'gpu'],
    'host.ram':           ['hw_ram_size', 'ram_size', 'ram'],
    'host.display':       ['hw_display', 'screen_resolution', 'resolution', 'ui_screen'],
    'host.motherboard':   ['hw_motherboard_product', 'motherboard'],
    'host.motherboard_vendor': ['hw_motherboard_vendor'],
    'host.timezone':      ['os_timezone', 'timezone', 'tz'],
    'host.local_date':    ['os_local_date', 'local_date', 'captured_at', 'ui_local_time'],
    'host.machine_guid':  ['ui_machine_guid', 'machine_id', 'machineid'],
    'host.hwid':          ['ui_hwid', 'hwid'],
    'host.appdata':       ['env_appdata', 'appdata'],
    'host.localappdata':  ['env_localappdata', 'localappdata'],
    'host.user_profile':  ['env_user_profile', 'user_profile'],
  },
  // Antivirus + defender state.
  av: {
    'av.name':   ['os_av_name', 'av_name', 'ui_av_name'],
    'av.state':  ['os_av_state', 'av_state'],
  },
  // Stealer build + egress context (stealer_info_yaml / information_v29_shape).
  build: {
    'build.version':      ['build_tag', 'build_version', 'ui_build_version'],
    'build.date':         ['build_date'],
    'build.capture_time': ['build_capture_time', 'ui_capture_time'],
    'build.loader_path':  ['build_loader_path', 'loader_path', 'ui_payload_path'],
    'build.loader_md5':   ['ui_payload_md5'],
    'build.work_dir':     ['ui_work_dir'],
    'build.elevated':     ['build_elevated', 'is_admin', 'elevated'],
  },
  net: {
    'net.egress_ip':  ['build_egress_ip', 'egress_ip', 'ip', 'ui_egress_ip'],
    'net.country':    ['build_country', 'country', 'ui_country'],
  },
  // Credential record shape.
  cred: {
    'cred.url':      ['url', 'host', 'target'],
    'cred.user':     ['user', 'login', 'username'],
    'cred.password': ['password', 'pass'],
    'cred.browser':  ['browser', 'soft', 'profile', 'software'],
  },
  // Cookie record shape (netscape_cookies / cookies_netscape_tsv).
  // Both cookie rules (netscape_cookies, cookies_netscape_tsv) emit
  // cookie_* on every column; standardised at the rule YAML level so
  // raw-query reading tells you exactly what each field is at a glance.
  cookie: {
    'cookie.host':    ['cookie_domain'],
    'cookie.name':    ['cookie_name'],
    'cookie.value':   ['cookie_value'],
    'cookie.path':    ['cookie_path'],
    'cookie.expires': ['cookie_expires_epoch'],
    'cookie.secure':  ['cookie_secure'],
    'cookie.http_only': ['cookie_http_only'],
    'cookie.include_subdomains': ['cookie_include_subdomains'],
  },
  // Process list rows (processes_dash_pid, processes_plain_exe).
  proc: {
    'proc.name': ['name', 'image', 'exe'],
    'proc.pid':  ['pid'],
    'proc.path': ['path', 'cmdline'],
  },
  // Installed software list (software_installed_list).
  software: {
    'software.name':    ['software_name', 'name', 'display_name'],
    'software.version': ['software_version', 'version'],
    'software.vendor':  ['software_vendor', 'vendor', 'publisher'],
  },
};

// Human-readable labels for the canonical keys, used when rendering
// detail tables. Falls back to the key itself if unlisted.
export const CANONICAL_LABELS = {
  'host.computer': 'Computer',
  'host.user': 'User',
  'host.domain': 'Domain',
  'host.hostname': 'Hostname',
  'host.os': 'OS',
  'host.os_language': 'Language',
  'host.os_install': 'OS installed',
  'host.cpu': 'CPU',
  'host.cpu_vendor': 'CPU vendor',
  'host.cpu_arch': 'Architecture',
  'host.cpu_count': 'CPU cores',
  'host.cpu_threads': 'CPU threads',
  'host.gpu': 'GPU',
  'host.ram': 'RAM',
  'host.display': 'Display',
  'host.motherboard': 'Motherboard',
  'host.motherboard_vendor': 'Motherboard vendor',
  'host.timezone': 'Timezone',
  'host.local_date': 'Local time',
  'host.appdata': 'AppData',
  'host.localappdata': 'LocalAppData',
  'host.user_profile': 'User profile',
  'host.machine_guid': 'Machine GUID',
  'host.hwid': 'HWID',
  'av.name': 'Antivirus',
  'av.state': 'AV state',
  'build.version': 'Stealer tag',
  'build.date': 'Build date',
  'build.capture_time': 'Captured at',
  'build.loader_path': 'Loader path',
  'build.loader_md5': 'Loader MD5',
  'build.work_dir': 'Work dir',
  'build.elevated': 'Elevated',
  'net.egress_ip': 'Egress IP',
  'net.country': 'Country',
};

/**
 * Collapse a records[] array (each with a raw fields dict) into one
 * canonical {canonical_key: value} map. Later records override earlier
 * ones for the same canonical key; pass records in priority order
 * (stealer_info_yaml is more complete than environment_windows, so put
 * it last). Alias precedence inside a single record follows the order
 * declared in CANONICAL_FIELDS.
 */
export function canonicalize(records, group) {
  const spec = CANONICAL_FIELDS[group];
  if (!spec) return {};
  const out = {};
  for (const r of records ?? []) {
    const f = r?.fields ?? {};
    for (const [canonical, aliases] of Object.entries(spec)) {
      if (out[canonical]) continue;
      for (const a of aliases) {
        if (f[a] !== undefined && f[a] !== '') { out[canonical] = f[a]; break; }
      }
    }
  }
  return out;
}

/** Group canonical keys by their dot-prefix (host, av, build, net, ...). */
export function groupByPrefix(canonical) {
  const groups = {};
  for (const [k, v] of Object.entries(canonical)) {
    const prefix = k.split('.')[0];
    (groups[prefix] ||= []).push([k, v]);
  }
  return groups;
}

export const PREFIX_LABELS = {
  host: 'Machine',
  av: 'Antivirus',
  build: 'Stealer build',
  net: 'Network',
  cred: 'Credentials',
  cookie: 'Cookies',
  proc: 'Processes',
  software: 'Software',
};
