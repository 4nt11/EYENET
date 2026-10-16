Immutable audit-trail row — monospace timestamp + actor, action verb, target, optional prose detail. Set `tamper` for integrity/tamper events (turns the row red).

```jsx
<AuditRow time="2026-09-20 12:04:51Z" actor="op.krieg" verb="reclassified"
  target="ART-0091" detail="HIGH → CRITICAL" />
<AuditRow time="2026-09-20 12:03:18Z" actor="op.krieg" verb="sealed" target="CASE-2026-0417" />
<AuditRow time="2026-09-20 11:59:02Z" actor="svc.ingest" tamper
  verb="hash mismatch on" target="ART-0088" />
```

Use `children` for custom action content. Reserve `tamper`/red for integrity failures.
