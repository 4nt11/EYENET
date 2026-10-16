Live event feed row for a streaming console — monospace timestamp, colored left rail by kind, uppercase label, message, and optional source line.

```jsx
<EventFeedItem time="12:04:51" kind="alert" label="BEACON" fresh
  message="Outbound C2 beacon detected" source="host: fin-ws-04 → 185.12.44.9" />
<EventFeedItem time="12:04:47" kind="observe" label="DNS"
  message="Resolution for known-bad domain" source="update.svc-cdn[.]net" />
<EventFeedItem time="12:04:40" kind="info" message="Analyst joined case" />
```

Kinds: `info` | `observe` (purple) | `alert` (red) | `system`. Set `fresh` on a newly-streamed item to flash the purple highlight, then clear it. Reserve `alert`/red for real alerts.
