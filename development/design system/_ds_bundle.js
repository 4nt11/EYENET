/* @ds-bundle: {"format":4,"namespace":"EYENETDesignSystem_6752a5","components":[{"name":"Button","sourcePath":"components/actions/Button.jsx"},{"name":"AuditRow","sourcePath":"components/console/AuditRow.jsx"},{"name":"CaseCard","sourcePath":"components/console/CaseCard.jsx"},{"name":"EventFeedItem","sourcePath":"components/console/EventFeedItem.jsx"},{"name":"DataTable","sourcePath":"components/data/DataTable.jsx"},{"name":"EvidencePanel","sourcePath":"components/data/EvidencePanel.jsx"},{"name":"Badge","sourcePath":"components/status/Badge.jsx"}],"sourceHashes":{"components/actions/Button.jsx":"c1c0e0a2271e","components/console/AuditRow.jsx":"6c8b988c2cc2","components/console/CaseCard.jsx":"5f784da80192","components/console/EventFeedItem.jsx":"eea0eb85b3e7","components/data/DataTable.jsx":"ceda87813235","components/data/EvidencePanel.jsx":"7739017f8bd1","components/status/Badge.jsx":"379aa5b8c1ce","ui_kits/eyenet/CaseView.jsx":"86a55bf2abd8","ui_kits/eyenet/Sidebar.jsx":"6d64675006b0","ui_kits/eyenet/TopBar.jsx":"073ddd7f2031"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.EYENETDesignSystem_6752a5 = window.EYENETDesignSystem_6752a5 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/actions/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const VARIANTS = {
  primary: {
    background: 'var(--accent)',
    color: '#fff',
    border: '1px solid var(--accent)',
    hoverBg: 'var(--accent-hover)'
  },
  destructive: {
    background: 'var(--red)',
    color: '#fff',
    border: '1px solid var(--red)',
    hoverBg: 'var(--red-hover)'
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-body)',
    border: '1px solid var(--border-strong)',
    hoverBg: 'var(--panel-2)'
  },
  quiet: {
    background: 'transparent',
    color: 'var(--text-secondary)',
    border: '1px solid transparent',
    hoverBg: 'var(--panel)'
  }
};
const SIZES = {
  sm: {
    height: 26,
    padding: '0 10px',
    fontSize: 'var(--fs-12)'
  },
  md: {
    height: 32,
    padding: '0 14px',
    fontSize: 'var(--fs-13)'
  },
  lg: {
    height: 38,
    padding: '0 18px',
    fontSize: 'var(--fs-14)'
  }
};

/**
 * Console action button. Primary = purple, destructive = red, everything else quiet/ghost.
 */
function Button({
  variant = 'quiet',
  size = 'md',
  disabled = false,
  icon = null,
  children,
  onClick,
  type = 'button',
  style,
  ...rest
}) {
  const v = VARIANTS[variant] || VARIANTS.quiet;
  const s = SIZES[size] || SIZES.md;
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      height: s.height,
      padding: s.padding,
      fontFamily: 'var(--font-sans)',
      fontSize: s.fontSize,
      fontWeight: 'var(--fw-medium)',
      lineHeight: 1,
      letterSpacing: '.01em',
      color: v.color,
      background: hover && !disabled ? v.hoverBg : v.background,
      border: v.border,
      borderRadius: 'var(--radius)',
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.45 : 1,
      transition: 'background 120ms ease, border-color 120ms ease',
      whiteSpace: 'nowrap',
      ...style
    }
  }, rest), icon ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      width: 14,
      height: 14
    }
  }, icon) : null, children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/actions/Button.jsx", error: String((e && e.message) || e) }); }

// components/console/AuditRow.jsx
try { (() => {
/**
 * Audit-trail row — immutable action record. Mono timestamp + actor, action verb, target, optional tamper flag.
 * action: { verb, target } | children as free content.
 */
function AuditRow({
  time,
  actor,
  verb,
  target,
  detail,
  tamper = false,
  style,
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '150px 130px 1fr',
      gap: 12,
      padding: '7px 12px',
      borderBottom: '1px solid var(--border)',
      alignItems: 'baseline',
      background: tamper ? 'var(--red-fill)' : 'transparent',
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-11)',
      letterSpacing: 'var(--tracking-data)',
      color: 'var(--text-tertiary)',
      whiteSpace: 'nowrap'
    }
  }, time), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-12)',
      letterSpacing: 'var(--tracking-data)',
      color: tamper ? 'var(--red-text)' : 'var(--accent-text)',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis'
    }
  }, actor), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--fs-13)',
      color: 'var(--text-body)',
      lineHeight: 'var(--lh-normal)'
    }
  }, children ? children : /*#__PURE__*/React.createElement(React.Fragment, null, tamper ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-11)',
      fontWeight: 'var(--fw-medium)',
      letterSpacing: 'var(--tracking-label)',
      textTransform: 'uppercase',
      color: 'var(--red-text)',
      marginRight: 8
    }
  }, "TAMPER") : null, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--text-secondary)'
    }
  }, verb, " "), target ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-12)',
      color: 'var(--text-body)'
    }
  }, target) : null, detail ? /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--text-tertiary)'
    }
  }, " \u2014 ", detail) : null)));
}
Object.assign(__ds_scope, { AuditRow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/AuditRow.jsx", error: String((e && e.message) || e) }); }

// components/console/EventFeedItem.jsx
try { (() => {
const KIND = {
  info: {
    color: 'var(--text-secondary)',
    rail: 'var(--border-strong)'
  },
  observe: {
    color: 'var(--accent-text)',
    rail: 'var(--accent)'
  },
  alert: {
    color: 'var(--red-text)',
    rail: 'var(--red)'
  },
  system: {
    color: 'var(--text-tertiary)',
    rail: 'var(--border)'
  }
};

/**
 * Live event feed item (streaming). Monospace timestamp, left rail by kind, optional label + actor.
 * Set `fresh` to briefly flag a just-arrived event.
 */
function EventFeedItem({
  time,
  kind = 'info',
  label,
  message,
  source,
  fresh = false,
  style
}) {
  const k = KIND[kind] || KIND.info;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '78px 1fr',
      gap: 10,
      padding: '6px 12px 6px 10px',
      borderLeft: `2px solid ${k.rail}`,
      borderBottom: '1px solid var(--border)',
      background: fresh ? 'var(--accent-fill)' : 'transparent',
      transition: 'background 600ms ease',
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-11)',
      letterSpacing: 'var(--tracking-data)',
      color: 'var(--text-tertiary)',
      lineHeight: 'var(--lh-normal)',
      whiteSpace: 'nowrap'
    }
  }, time), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 8,
      flexWrap: 'wrap'
    }
  }, label ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-11)',
      fontWeight: 'var(--fw-medium)',
      letterSpacing: 'var(--tracking-label)',
      textTransform: 'uppercase',
      color: k.color
    }
  }, label) : null, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--fs-13)',
      color: 'var(--text-body)',
      lineHeight: 'var(--lh-normal)'
    }
  }, message)), source ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-11)',
      letterSpacing: 'var(--tracking-data)',
      color: 'var(--text-tertiary)'
    }
  }, source) : null));
}
Object.assign(__ds_scope, { EventFeedItem });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/EventFeedItem.jsx", error: String((e && e.message) || e) }); }

// components/data/DataTable.jsx
try { (() => {
/**
 * Dense, evidence-grade data table. Monospace cells, hairline rows, optional right-alignment.
 * columns: [{ key, header, width?, align?, mono?, render? }]
 */
function DataTable({
  columns = [],
  rows = [],
  onRowClick,
  selectedId,
  rowKey = 'id',
  style
}) {
  const [hover, setHover] = React.useState(null);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      overflow: 'hidden',
      background: 'var(--surface)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontFamily: 'var(--font-sans)'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, columns.map(c => /*#__PURE__*/React.createElement("th", {
    key: c.key,
    style: {
      textAlign: c.align || 'left',
      padding: '8px 12px',
      width: c.width,
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--fs-11)',
      fontWeight: 'var(--fw-semibold)',
      letterSpacing: 'var(--tracking-label)',
      textTransform: 'uppercase',
      color: 'var(--text-tertiary)',
      background: 'var(--panel)',
      borderBottom: '1px solid var(--border)',
      whiteSpace: 'nowrap'
    }
  }, c.header)))), /*#__PURE__*/React.createElement("tbody", null, rows.map((r, i) => {
    const id = r[rowKey] ?? i;
    const isSel = selectedId != null && id === selectedId;
    const isHover = hover === id;
    return /*#__PURE__*/React.createElement("tr", {
      key: id,
      onClick: onRowClick ? () => onRowClick(r) : undefined,
      onMouseEnter: () => setHover(id),
      onMouseLeave: () => setHover(null),
      style: {
        cursor: onRowClick ? 'pointer' : 'default',
        background: isSel ? 'var(--accent-fill)' : isHover ? 'var(--panel)' : 'transparent',
        borderLeft: isSel ? '2px solid var(--accent-text)' : '2px solid transparent'
      }
    }, columns.map(c => /*#__PURE__*/React.createElement("td", {
      key: c.key,
      style: {
        textAlign: c.align || 'left',
        padding: '7px 12px',
        fontFamily: c.mono ? 'var(--font-mono)' : 'var(--font-sans)',
        fontSize: c.mono ? 'var(--fs-12)' : 'var(--fs-13)',
        letterSpacing: c.mono ? 'var(--tracking-data)' : 'normal',
        color: 'var(--text-body)',
        borderBottom: '1px solid var(--border)',
        whiteSpace: 'nowrap',
        verticalAlign: 'middle'
      }
    }, c.render ? c.render(r[c.key], r) : r[c.key])));
  }))));
}
Object.assign(__ds_scope, { DataTable });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/DataTable.jsx", error: String((e && e.message) || e) }); }

// components/data/EvidencePanel.jsx
try { (() => {
/**
 * Key/value evidence panel. Monospace values, aligned labels, optional copy affordance & title.
 * items: [{ label, value, mono?, tone? }]
 */
function EvidencePanel({
  title,
  items = [],
  labelWidth = 128,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      background: 'var(--panel)',
      overflow: 'hidden',
      ...style
    }
  }, title ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '8px 12px',
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--fs-11)',
      fontWeight: 'var(--fw-semibold)',
      letterSpacing: 'var(--tracking-label)',
      textTransform: 'uppercase',
      color: 'var(--text-tertiary)',
      borderBottom: '1px solid var(--border)',
      background: 'var(--surface)'
    }
  }, title) : null, /*#__PURE__*/React.createElement("dl", {
    style: {
      margin: 0
    }
  }, items.map((it, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: 'grid',
      gridTemplateColumns: `${labelWidth}px 1fr`,
      gap: 12,
      padding: '7px 12px',
      borderBottom: i === items.length - 1 ? 'none' : '1px solid var(--border)',
      alignItems: 'baseline'
    }
  }, /*#__PURE__*/React.createElement("dt", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--fs-12)',
      color: 'var(--text-tertiary)',
      letterSpacing: '.01em'
    }
  }, it.label), /*#__PURE__*/React.createElement("dd", {
    style: {
      margin: 0,
      fontFamily: it.mono === false ? 'var(--font-sans)' : 'var(--font-mono)',
      fontSize: it.mono === false ? 'var(--fs-13)' : 'var(--fs-12)',
      letterSpacing: it.mono === false ? 'normal' : 'var(--tracking-data)',
      color: it.tone === 'critical' ? 'var(--red-text)' : it.tone === 'accent' ? 'var(--accent-text)' : 'var(--text-body)',
      wordBreak: 'break-all'
    }
  }, it.value)))));
}
Object.assign(__ds_scope, { EvidencePanel });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/data/EvidencePanel.jsx", error: String((e && e.message) || e) }); }

// components/status/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Classification tiers & statuses. Red reserved for the top severity only. */
const TONES = {
  critical: {
    color: 'var(--red-text)',
    fill: 'var(--red-fill)',
    border: 'rgba(194,69,63,.45)'
  },
  high: {
    color: 'var(--accent-text)',
    fill: 'var(--accent-fill)',
    border: 'rgba(162,89,196,.40)'
  },
  medium: {
    color: 'var(--text-body)',
    fill: 'var(--panel-2)',
    border: 'var(--border-strong)'
  },
  low: {
    color: 'var(--text-secondary)',
    fill: 'transparent',
    border: 'var(--border)'
  },
  neutral: {
    color: 'var(--text-secondary)',
    fill: 'transparent',
    border: 'var(--border)'
  }
};

/**
 * Status / classification tier badge. Monospace, uppercase, 1px hairline. `critical` is the only red tone.
 */
function Badge({
  tone = 'neutral',
  dot = false,
  children,
  style,
  ...rest
}) {
  const t = TONES[tone] || TONES.neutral;
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      height: 18,
      padding: '0 7px',
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-11)',
      fontWeight: 'var(--fw-medium)',
      lineHeight: 1,
      letterSpacing: 'var(--tracking-label)',
      textTransform: 'uppercase',
      color: t.color,
      background: t.fill,
      border: `1px solid ${t.border}`,
      borderRadius: 'var(--radius-sm)',
      whiteSpace: 'nowrap',
      ...style
    }
  }, rest), dot ? /*#__PURE__*/React.createElement("span", {
    style: {
      width: 5,
      height: 5,
      borderRadius: '50%',
      background: t.color,
      flex: '0 0 auto'
    }
  }) : null, children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/status/Badge.jsx", error: String((e && e.message) || e) }); }

// components/console/CaseCard.jsx
try { (() => {
/**
 * Case summary card for a caseload grid/list. Case id (mono), title, tier badge, meta row.
 */
function CaseCard({
  caseId,
  title,
  tier = 'medium',
  tierLabel,
  actor,
  updated,
  openCount,
  active = false,
  onClick,
  style
}) {
  const [hover, setHover] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClick,
    onMouseEnter: () => setHover(true),
    onMouseLeave: () => setHover(false),
    style: {
      border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
      borderRadius: 'var(--radius)',
      background: active ? 'var(--accent-fill)' : hover ? 'var(--panel-2)' : 'var(--panel)',
      padding: '12px 14px',
      cursor: onClick ? 'pointer' : 'default',
      transition: 'background 120ms ease, border-color 120ms ease',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--fs-11)',
      letterSpacing: 'var(--tracking-data)',
      color: 'var(--text-tertiary)'
    }
  }, caseId), /*#__PURE__*/React.createElement(__ds_scope.Badge, {
    tone: tier,
    dot: true
  }, tierLabel || tier)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--fs-14)',
      fontWeight: 'var(--fw-semibold)',
      color: 'var(--text-body)',
      lineHeight: 'var(--lh-tight)'
    }
  }, title), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      flexWrap: 'wrap'
    }
  }, actor ? /*#__PURE__*/React.createElement(Meta, {
    label: "Actor",
    value: actor,
    mono: true
  }) : null, openCount != null ? /*#__PURE__*/React.createElement(Meta, {
    label: "Open leads",
    value: String(openCount)
  }) : null, updated ? /*#__PURE__*/React.createElement(Meta, {
    label: "Updated",
    value: updated,
    mono: true
  }) : null));
}
function Meta({
  label,
  value,
  mono
}) {
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      flexDirection: 'column',
      gap: 2
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 'var(--fs-11)',
      letterSpacing: 'var(--tracking-label)',
      textTransform: 'uppercase',
      color: 'var(--text-tertiary)'
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)',
      fontSize: 'var(--fs-12)',
      letterSpacing: mono ? 'var(--tracking-data)' : 'normal',
      color: 'var(--text-secondary)'
    }
  }, value));
}
Object.assign(__ds_scope, { CaseCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/console/CaseCard.jsx", error: String((e && e.message) || e) }); }

// ui_kits/eyenet/CaseView.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const {
  DataTable,
  EvidencePanel,
  EventFeedItem,
  AuditRow,
  Badge,
  Button
} = window.EYENETDesignSystem_6752a5;
const EVIDENCE = [{
  id: 'ART-0091',
  ts: '12:04:51Z',
  indicator: '185.12.44.9',
  type: 'ipv4',
  tier: 'critical',
  src: 'beacon'
}, {
  id: 'ART-0090',
  ts: '12:03:18Z',
  indicator: 'update.svc-cdn[.]net',
  type: 'domain',
  tier: 'high',
  src: 'dns'
}, {
  id: 'ART-0088',
  ts: '11:59:02Z',
  indicator: 'a3f19e2c…b8d4',
  type: 'sha256',
  tier: 'high',
  src: 'file'
}, {
  id: 'ART-0085',
  ts: '11:51:40Z',
  indicator: 'fin-ws-04',
  type: 'host',
  tier: 'medium',
  src: 'edr'
}, {
  id: 'ART-0081',
  ts: '11:44:12Z',
  indicator: 'svc.ingest\\loader.dll',
  type: 'path',
  tier: 'medium',
  src: 'edr'
}, {
  id: 'ART-0078',
  ts: '11:30:55Z',
  indicator: 'T1071.001',
  type: 'ttp',
  tier: 'low',
  src: 'analyst'
}];
const SEED_FEED = [{
  id: 4,
  time: '12:04:51',
  kind: 'alert',
  label: 'Beacon',
  message: 'Outbound C2 beacon detected',
  source: 'fin-ws-04 → 185.12.44.9'
}, {
  id: 3,
  time: '12:04:47',
  kind: 'observe',
  label: 'DNS',
  message: 'Resolution for known-bad domain',
  source: 'update.svc-cdn[.]net'
}, {
  id: 2,
  time: '12:04:40',
  kind: 'info',
  message: 'Analyst op.krieg joined case'
}, {
  id: 1,
  time: '12:04:33',
  kind: 'system',
  label: 'Ingest',
  message: 'Artifact ART-0088 sealed',
  source: 'sha256 verified'
}];
const NEW_EVENTS = [{
  kind: 'observe',
  label: 'HTTP',
  message: 'POST to /gate.php',
  source: '185.12.44.9'
}, {
  kind: 'alert',
  label: 'Exfil',
  message: 'Anomalous outbound volume',
  source: 'fin-ws-04 · 42 MB'
}, {
  kind: 'info',
  label: 'Note',
  message: 'Correlated with CASE-2026-0402'
}, {
  kind: 'observe',
  label: 'DNS',
  message: 'TXT record query',
  source: 'c2.svc-cdn[.]net'
}];
function Panel({
  title,
  action,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("section", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      minHeight: 0,
      border: '1px solid var(--border)',
      borderRadius: 4,
      background: 'var(--surface)',
      overflow: 'hidden',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: '0 0 auto',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '8px 12px',
      background: 'var(--panel)',
      borderBottom: '1px solid var(--border)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '.08em',
      textTransform: 'uppercase',
      color: 'var(--text-faint)'
    }
  }, title), action), /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: 0,
      overflow: 'auto'
    }
  }, children));
}
function CaseView() {
  const [sel, setSel] = React.useState('ART-0091');
  const [feed, setFeed] = React.useState(SEED_FEED);
  const [freshId, setFreshId] = React.useState(null);
  const nid = React.useRef(5);
  const cursor = React.useRef(0);
  React.useEffect(() => {
    const t = setInterval(() => {
      const tpl = NEW_EVENTS[cursor.current % NEW_EVENTS.length];
      cursor.current += 1;
      const now = new Date();
      const time = now.toTimeString().slice(0, 8);
      const id = nid.current++;
      setFeed(f => [{
        id,
        time,
        ...tpl
      }, ...f].slice(0, 40));
      setFreshId(id);
      setTimeout(() => setFreshId(x => x === id ? null : x), 900);
    }, 3200);
    return () => clearInterval(t);
  }, []);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      background: 'var(--black)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: '0 0 auto',
      padding: '16px 20px',
      borderBottom: '1px solid var(--border)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      marginBottom: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 12,
      color: 'var(--text-faint)'
    }
  }, "CASE-2026-0417"), /*#__PURE__*/React.createElement(Badge, {
    tone: "critical",
    dot: true
  }, "Critical"), /*#__PURE__*/React.createElement(Badge, {
    tone: "neutral"
  }, "Active")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontFamily: 'var(--font-sans)',
      fontSize: 22,
      fontWeight: 600,
      color: 'var(--text)',
      lineHeight: 1.2
    }
  }, "Loader campaign \u2014 EMEA finance sector"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 8,
      flex: '0 0 auto'
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm"
  }, "Export dossier"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm"
  }, "Reclassify"), /*#__PURE__*/React.createElement(Button, {
    variant: "destructive",
    size: "sm"
  }, "Seal & purge")))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minHeight: 0,
      display: 'grid',
      gridTemplateColumns: 'minmax(0,1.7fr) minmax(320px,1fr)',
      gap: 16,
      padding: 16,
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "Evidence \u2014 indicators & artifacts",
    style: {
      flex: 1
    },
    action: /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-faint)'
      }
    }, EVIDENCE.length, " items")
  }, /*#__PURE__*/React.createElement(DataTable, {
    rowKey: "id",
    selectedId: sel,
    onRowClick: r => setSel(r.id),
    style: {
      border: 'none',
      borderRadius: 0
    },
    columns: [{
      key: 'ts',
      header: 'Timestamp',
      mono: true,
      width: '110px'
    }, {
      key: 'id',
      header: 'Artifact',
      mono: true,
      width: '96px'
    }, {
      key: 'indicator',
      header: 'Indicator',
      mono: true
    }, {
      key: 'type',
      header: 'Type',
      mono: true,
      width: '78px'
    }, {
      key: 'tier',
      header: 'Tier',
      width: '96px',
      render: v => /*#__PURE__*/React.createElement(Badge, {
        tone: v
      }, v)
    }, {
      key: 'src',
      header: 'Source',
      align: 'right',
      width: '80px'
    }],
    rows: EVIDENCE
  })), /*#__PURE__*/React.createElement(Panel, {
    title: "Audit trail \u2014 immutable",
    style: {
      flex: '0 0 auto',
      maxHeight: 168
    }
  }, /*#__PURE__*/React.createElement(AuditRow, {
    time: "2026-09-20 12:04:51Z",
    actor: "op.krieg",
    verb: "reclassified",
    target: "ART-0091",
    detail: "HIGH \u2192 CRITICAL"
  }), /*#__PURE__*/React.createElement(AuditRow, {
    time: "2026-09-20 12:03:18Z",
    actor: "op.krieg",
    verb: "sealed",
    target: "ART-0090"
  }), /*#__PURE__*/React.createElement(AuditRow, {
    time: "2026-09-20 11:59:02Z",
    actor: "svc.ingest",
    tamper: true,
    verb: "hash mismatch on",
    target: "ART-0088"
  }), /*#__PURE__*/React.createElement(AuditRow, {
    time: "2026-09-20 11:44:12Z",
    actor: "op.krieg",
    verb: "opened",
    target: "CASE-2026-0417"
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement(EvidencePanel, {
    title: `Selected — ${sel}`,
    style: {
      flex: '0 0 auto'
    },
    items: [{
      label: 'Artifact',
      value: sel
    }, {
      label: 'SHA-256',
      value: 'a3f19e2c…b8d4'
    }, {
      label: 'First seen',
      value: '2026-09-18 04:12:07Z'
    }, {
      label: 'Classification',
      value: 'CRITICAL',
      tone: 'critical'
    }, {
      label: 'Attributed',
      value: 'UNC-3312',
      tone: 'accent'
    }, {
      label: 'Note',
      value: 'Matches known loader family',
      mono: false
    }]
  }), /*#__PURE__*/React.createElement(Panel, {
    title: "Live event feed",
    style: {
      flex: 1
    },
    action: /*#__PURE__*/React.createElement("span", {
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        letterSpacing: '.1em',
        color: 'var(--red-text)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: 5,
        height: 5,
        borderRadius: '50%',
        background: 'var(--red-text)'
      }
    }), "STREAMING")
  }, feed.map(e => /*#__PURE__*/React.createElement(EventFeedItem, _extends({
    key: e.id
  }, e, {
    fresh: e.id === freshId
  })))))));
}
window.CaseView = CaseView;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/eyenet/CaseView.jsx", error: String((e && e.message) || e) }); }

// ui_kits/eyenet/Sidebar.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const {
  CaseCard
} = window.EYENETDesignSystem_6752a5;
const CASES = [{
  caseId: 'CASE-2026-0417',
  title: 'Loader campaign — EMEA finance sector',
  tier: 'critical',
  tierLabel: 'Critical',
  actor: 'UNC-3312',
  openCount: 7,
  updated: '12:04Z'
}, {
  caseId: 'CASE-2026-0402',
  title: 'Credential harvest — supplier portal',
  tier: 'high',
  tierLabel: 'High',
  actor: 'UNC-2980',
  openCount: 3,
  updated: '09:51Z'
}, {
  caseId: 'CASE-2026-0388',
  title: 'Beaconing host — staging network',
  tier: 'medium',
  tierLabel: 'Medium',
  actor: 'unattributed',
  openCount: 1,
  updated: 'Sep 18'
}, {
  caseId: 'CASE-2026-0371',
  title: 'Phishing infra teardown',
  tier: 'low',
  tierLabel: 'Low',
  actor: 'UNC-2980',
  openCount: 0,
  updated: 'Sep 15'
}];
function Sidebar({
  selected,
  onSelect
}) {
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: 320,
      flex: '0 0 auto',
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--black)',
      borderRight: '1px solid var(--border)',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '10px 14px',
      flex: '0 0 auto',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      borderBottom: '1px solid var(--border)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-sans)',
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '.08em',
      textTransform: 'uppercase',
      color: 'var(--text-faint)'
    }
  }, "Caseload"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      color: 'var(--text-faint)'
    }
  }, CASES.length, " active")), /*#__PURE__*/React.createElement("div", {
    style: {
      overflow: 'auto',
      padding: 12,
      display: 'flex',
      flexDirection: 'column',
      gap: 10
    }
  }, CASES.map(c => /*#__PURE__*/React.createElement(CaseCard, _extends({
    key: c.caseId
  }, c, {
    active: c.caseId === selected,
    onClick: () => onSelect(c.caseId)
  })))));
}
window.Sidebar = Sidebar;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/eyenet/Sidebar.jsx", error: String((e && e.message) || e) }); }

// ui_kits/eyenet/TopBar.jsx
try { (() => {
const {
  Badge
} = window.EYENETDesignSystem_6752a5;
function TopBar({
  caseId
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      height: 44,
      flex: '0 0 auto',
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      padding: '0 16px',
      background: 'var(--surface)',
      borderBottom: '1px solid var(--border)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 8
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 15,
      fontWeight: 700,
      letterSpacing: '.16em',
      color: 'var(--text)'
    }
  }, "EYENET"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 10,
      letterSpacing: '.14em',
      textTransform: 'uppercase',
      color: 'var(--accent-text)'
    }
  }, "Observation Console")), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 20,
      background: 'var(--border)'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 12,
      color: 'var(--text-faint)'
    }
  }, caseId), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      alignItems: 'center',
      gap: 14
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      color: 'var(--text-muted)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 6,
      height: 6,
      borderRadius: '50%',
      background: 'var(--red-text)'
    }
  }), "LIVE"), /*#__PURE__*/React.createElement(Badge, {
    tone: "neutral",
    dot: true
  }, "SECURE LINK"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 12,
      color: 'var(--accent-text)'
    }
  }, "op.krieg")));
}
window.TopBar = TopBar;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/eyenet/TopBar.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.AuditRow = __ds_scope.AuditRow;

__ds_ns.CaseCard = __ds_scope.CaseCard;

__ds_ns.EventFeedItem = __ds_scope.EventFeedItem;

__ds_ns.DataTable = __ds_scope.DataTable;

__ds_ns.EvidencePanel = __ds_scope.EvidencePanel;

__ds_ns.Badge = __ds_scope.Badge;

})();
