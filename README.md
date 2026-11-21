<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

> # :rotating_light: HEY MORON, THIS PROJECT IS IN EXPERIMENTAL PHASE. :rotating_light:
> # USE AT YOUR OWN RISK! :3
>
> Schema changes land weekly. Migrations exist but are not bulletproof.
> Prod-shaped bugs will land in your lap. If you are reading this and
> thinking "neat, let me run it on real data," think again, then do
> whatever you want anyway, you beautiful cowboy.

---

# EYENET

Observation framework for **forensic analysis of threat actors**. EYENET
consumes [BEHAVE-TEXT](../BEHAVE/BEHAVE-TEXT) behavioral primitives and is a
sibling of DECNET. Built for **small operators** (the analyst running a few
collectors, not an enterprise SOC) with an **operator-grade evidence** posture:
retain full content, audit every access, never hobble the operator.

## Running

EYENET ships as a Docker Compose stack. There is no "install on bare metal" path.

```bash
cp deploy/docker/env.example deploy/docker/.env
# edit .env: set EYENET_DOMAIN, EYENET_ACME_EMAIL, CH creds, Postgres creds, ...
deploy/docker/deploy.sh deploy
```

`deploy.sh deploy` builds the images on the host, tags them with the current
version, brings the stack up with the stealer profile, verifies health, and
prunes old versions. `deploy.sh rollback [VER]` repoints the live tag at a
retained version. `deploy.sh versions` lists what is retained vs. running.

The composition is `compose.yaml` + `compose.prod.lite.yaml` with the `stealer`
profile (core services + ULP extractors; no observability, classifier, or
incidents). Edit `deploy/docker/deploy.sh` if the box should run more.

## Documentation

| Doc | What |
|---|---|
| [`PLAN.md`](PLAN.md) | milestone roadmap |
| [`CLAUDE.md`](CLAUDE.md) | architecture, conventions, traps |
| [`deploy/DEPLOY.md`](deploy/DEPLOY.md) | deployment internals + flags |
| [`development/API_PLAN.md`](development/API_PLAN.md) | HTTP API spec (source of truth for `v1` routes) |
| [`development/MODELS.md`](development/MODELS.md) | table-by-table schema reference |
| [`development/CLASSIFIER_PLAN.md`](development/CLASSIFIER_PLAN.md) | Document Classifier design + build plan |

## License

AGPL-3.0-or-later.
