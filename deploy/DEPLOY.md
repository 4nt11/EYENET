# EYENET deploy — method + templates

Single-host systemd deployment: **one `eyenet.target` owns the whole EYENET
service set**, modeled on `../../DECNET/deploy/`. This pass ships the unit
templates + aux configs + this plan. The renderer/installer (`eyenet deploy`) is
specified here and built in the next pass.

> **Second pass (deferred, do not build yet):** a full-Docker path via
> `docker compose`. The systemd/native path here is primary; the compose path
> reuses the same `ExecStart` commands and env, so nothing here is throwaway.

---

## 1. Model

- **Native binaries under systemd.** Each EYENET service is a `Type=simple`
  unit running `{{ venv_dir }}/bin/eyenet <cmd>`. NATS runs as the native
  `nats-server` binary (`eyenet-nats.service`) — it's a single static Go binary,
  lighter than a container and daemon-free.
- **`eyenet.target` is the lifecycle handle.** `Wants=` starts the members;
  each member carries `PartOf=eyenet.target` so `systemctl stop eyenet.target`
  actually brings them down instead of orphaning them. Ordering is per-unit via
  `After=/Wants=eyenet-nats.service`, not the target.
- **Small-operator scope, default cardinality 1** (per project doctrine): one of
  each pipeline worker. The one plural axis is collectors — instanced per
  identity — which is why they're excluded from the target's `Wants=`.

## 2. Service inventory

| Unit | Command | Role | In `eyenet.target`? |
|------|---------|------|:---:|
| `eyenet-nats.service` | `nats-server` | message bus (core NATS, no JetStream) | ✅ |
| `eyenet-api.service` | `eyenet api` | HTTP/2+TLS API (Hypercorn), binds :8443 | ✅ |
| `eyenet-graph.service` | `eyenet graph` | write-decision applier (typed relations) | ✅ |
| `eyenet-supervisor.service` | `eyenet supervisor` | collector observed→desired reconcile | ✅ |
| `eyenet-anchor.service` | `eyenet anchor` | §5.9 signed audit/journal-head heartbeat | ✅ |
| `eyenet-sensor.service` | `eyenet sensor --profile stylometric` | BEHAVE-TEXT primitive dispatch | ✅ |
| `eyenet-engine.service` | `eyenet engine` | attribution profile-candidate emission | ✅ |
| `eyenet-linker.service` | `eyenet linker` | pairwise linkage proposal | ✅ |
| `eyenet-verifier.service` | `eyenet verifier` | GI+NCD linkage confirmation | ✅ |
| `eyenet-classifier.service` | `eyenet classifier` | M10 nsjail document classifier | ✅ ⚠ |
| `eyenet-collector@.service` | `eyenet collector --identity %i` | per-identity collector | ❌ instanced |

⚠ `eyenet-classifier` needs **relaxed** sandboxing (see §6).

## 3. Layout

```
{{ install_dir }}            code checkout + venv (default /opt/eyenet)
{{ install_dir }}/.env.local operator overrides (EnvironmentFile, optional)
{{ venv_dir }}/bin/eyenet    the CLI entrypoint (auto-detected under install_dir)
{{ data_dir }}               main.db, audit.db, jwt/ keys (default /var/lib/eyenet)
{{ data_dir }}/jwt/          JWT + exoneration + anchor keys + deployment_id
/etc/eyenet/                 rendered config + /etc/eyenet/collectors/<id>.env
/var/log/eyenet/             per-unit append logs (rotated)
```

Service identity: system user/group `eyenet` (override `--user/--group`; dev may
pass `--user $USER` to avoid ownership churn).

## 4. Jinja2 template variables

Rendered by the installer with `StrictUndefined`. Required unless a `default()`
is shown in the template:

| var | meaning | default |
|-----|---------|---------|
| `user`, `group` | service identity | `eyenet` |
| `install_dir` | code + venv root | `/opt/eyenet` |
| `venv_dir` | venv to ExecStart from | auto-detect under `install_dir` |
| `data_dir` | DB + keys | `/var/lib/eyenet` |
| `nats_bin` | nats-server path | `/usr/local/bin/nats-server` |
| `nats_host`,`nats_port` | bus listen | `127.0.0.1`, `4222` |
| `nats_url` | worker bus URL | `nats://127.0.0.1:4222` |
| `api_host`,`api_port` | API bind | `127.0.0.1`, `8443` |
| `tls_certfile`,`tls_keyfile` | API TLS (required for non-loopback) | — |
| `cors_origins` | `EYENET_API_CORS_ORIGINS` | empty |
| `supervisor_tick`,`anchor_tick` | tick seconds | `5`, `300` |
| `sensor_profile` | `stylometric`\|`skeleton` | `stylometric` |
| `identities_dir` | collector session files | `{data_dir}/identities` |

## 5. The installer — `eyenet deploy` (NEXT PASS, to build)

One-shot root bootstrap, mirroring `decnet init` (`decnet/cli/init.py`). Uses
`jinja2` (`Environment(FileSystemLoader('deploy/'), undefined=StrictUndefined)`).

**Steps (idempotent, each with a `--dry-run` line):**
1. Preflight: require root (unless `--prefix` test mode); require `systemctl`,
   `useradd`, `groupadd`, `systemd-tmpfiles`, `nats-server` on PATH.
2. Resolve venv (fail loud if absent — never ship broken units).
3. Ensure `user`/`group`; seed dirs (`install_dir` 0755, `data_dir` 0750,
   `data_dir/jwt` 0700, `/etc/eyenet` 0755 root:group, `/var/log/eyenet` 0750).
4. Render every `deploy/*.service.j2` + `eyenet.target` → `/etc/systemd/system/`.
5. Render polkit → `/etc/polkit-1/rules.d/`, tmpfiles → `/etc/tmpfiles.d/`,
   copy logrotate → `/etc/logrotate.d/eyenet`.
6. `systemctl daemon-reload`; unless `--no-start`, `systemctl enable --now
   eyenet.target`.

**Flags:** `--dry-run`, `--no-start`, `--force` (overwrite identical),
`--deinit` (stop+disable, remove units/polkit/tmpfiles, preserve data),
`--purge` (with `--deinit`: also wipe `data_dir`/logs + user/group),
`--user/--group/--install-dir/--venv-dir/--data-dir`, `--prefix` (test root).

**Command name:** `eyenet deploy` — NOT `eyenet init`. `eyenet init` is the
existing DB-init command (`rm data/*.db && eyenet init`); host provisioning is a
distinct concern and must not overload it.

## 6. Security hardening

All units carry the baseline: `NoNewPrivileges`, `ProtectSystem=full`,
`ProtectHome=read-only`, `PrivateTmp`, `Protect{KernelTunables,KernelModules,
ControlGroups}`, `RestrictSUIDSGID`, `LockPersonality`, empty capability set,
tight `ReadWritePaths` ({{ data_dir }} + /var/log/eyenet only).

**Exception — `eyenet-classifier`:** M10 runs untrusted extraction inside
nsjail, which needs its own user/mount/pid namespaces + seccomp. That collides
with systemd sandboxing, so the classifier unit deliberately drops
`NoNewPrivileges` and `RestrictNamespaces` and is marked **REQUIRES TUNING**.
Host prereqs: unprivileged userns enabled; `nsjail` on PATH; an ABI-matched
extract venv (py3.14) with pymupdf/docx/tesseract/presidio. Harden incrementally
only after a real classify runs end-to-end.

## 7. First-run prerequisites (out of band)

- **TLS**: real cert/key for `api_host` (self-signed only for loopback/dev).
- **Admin**: bootstrap the first admin — `eyenet user create --role admin
  --generate` — then self-grant `admin:clearance` via `eyenet user scopes` for
  the clearance surface (grant-only scope; 403 until granted — see
  `development/TODO.md`).
- **spaCy** `es_core_news_sm` (~13MB) auto-fetches on first sensor run → needs
  outbound network once (or pre-bake at build).
- **Classifier** models (spaCy/presidio) + extract venv as in §6.

## 8. Operate

```bash
sudo eyenet deploy --install-dir /opt/eyenet --data-dir /var/lib/eyenet \
    --tls-certfile /etc/eyenet/tls/cert.pem --tls-keyfile /etc/eyenet/tls/key.pem
systemctl status eyenet.target
journalctl -u eyenet-api -f              # or tail /var/log/eyenet/eyenet.api.log
# per-identity collector:
printf 'COLLECTOR_TYPE=telegram\n' | sudo tee /etc/eyenet/collectors/scout01.env
sudo systemctl enable --now eyenet-collector@scout01.service
sudo systemctl restart eyenet.target     # PartOf= fans restart to all members
```

## 9. Open decisions

- **Docker-compose second pass** (deferred): a `compose.yaml` running the same
  services as containers, one NATS container, shared volume for `data_dir`.
  Reuses these `ExecStart` commands verbatim.
- **NATS exposure**: loopback-only by default. Multi-host (remote collectors)
  needs NATS TLS + auth before widening `--addr` — not in scope here.
- **`MissingGreenlet` teardown noise**: benign SQLAlchemy+aiosqlite
  connection-finalizer warning in the bus workers ("Exception during reset");
  harmless but worth a cleanup ticket (session/pool disposal on shutdown).
