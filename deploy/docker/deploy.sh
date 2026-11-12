#!/bin/sh
# Named-version deploy + rollback for EYENET, built ON THE HOST (no registry, no CI).
# Adapted from the MLAB despliegue.sh ~ same failure mode, three EYENET-specific changes
# (see below). Runs on the deploy host, needs docker + git (already required to deploy).
#
#   deploy/docker/deploy.sh deploy            build, tag, up, verify, prune
#   deploy/docker/deploy.sh rollback [VER]    go back to VER, or to the one before running
#   deploy/docker/deploy.sh versions          what is retained, what is running
#
# ---------------------------------------------------------------------------------------
# THE FAILURE MODE THIS CLOSES
#
# `docker compose up --build` on the server IS the deploy. A service with `build:` and a
# plain `image: eyenet:base` gets that tag REWRITTEN every build; the previous image keeps
# the bits but loses the name, left as <none>:<none> ~ alive, on disk, unnameable. So
# "go back to yesterday's build" was not a hard command, it was one that did not exist.
#
# This script keeps `eyenet:base` / `eyenet:stealer` as the LIVE POINTERS compose uses
# (so dev + every `FROM eyenet:base` are untouched) and, beside them, RETAINED versioned
# tags `eyenet:base-<version>` that each build preserves. Rollback just repoints the live
# tag at a retained one and brings it up WITHOUT building.
#
# EYENET vs MLAB, the three differences that changed the design:
#   1. No standalone alembic CLI here (`alembic current` fails: the Config is built
#      programmatically in upgrade_to_head). So the migration-safety check reads the DB's
#      `alembic_version` directly and tests for the revision's file in the TARGET image.
#   2. TWO databases (eyenet + eyenet_audit), each with its own alembic_version on the
#      same migration tree. The check covers both.
#   3. Migrations run on EVERY service boot (upgrade_to_head in the repo init), not a
#      dedicated `migrate` service. The hazard is identical: rolling back across a
#      migration makes the old image's upgrade die on a revision it does not have, and
#      `restart: unless-stopped` turns that into a crash loop. `rollback` refuses it.
#
# What this does NOT give (say it plainly): the artifact is not reproducible from another
# machine, not signed, and lives only on this host. The day a registry exists the swap is
# `docker push` here / `docker pull` there; the tag, the baked label, retention and
# rollback do not change.
set -eu

ROOT=$(cd "$(dirname "$0")/../.." && pwd)

# Classic builder for ALL builds here. The derived images do `FROM eyenet:base`, a tag that
# lives ONLY on this host (no registry); BuildKit tries to RESOLVE such a FROM from a
# registry and fails, while the classic builder uses the local image. It also sidesteps a
# flaky-DNS registry HEAD on the public bases. Drop this the day there is a registry.
export DOCKER_BUILDKIT=0
export COMPOSE_BAKE=0

# The deploy composition = base compose + the lite prod override + the stealer profile
# (core services + ULP extractors; no observability/classifier/incidents). This is the
# documented prod-lite deploy; change here if the box ever runs more.
componer() {
	docker compose \
		-f "$ROOT/deploy/docker/compose.yaml" \
		-f "$ROOT/deploy/docker/compose.prod.lite.yaml" \
		--profile stealer "$@"
}

# The image ROLES this repo builds and that therefore get versioned + pruned. They ride
# the version the build bakes. `base` is first and is the one versions are read from (api
# + every worker share it, so it always exists); `edge` is the Caddy+SPA image.
# tor/classifier/incidents are out of the release set here, like MLAB left db/backup out.
ROLES="base stealer edge"

# Witness service: runs eyenet:base, does the boot migration, and (unlike a migrate job)
# stays alive for `exec`. The source of truth for "what is running".
WITNESS=api

# The DB service + names/user to read alembic_version from (local psql in the pg container
# is trust-auth, no password). Override via env if your compose differs.
DB_SERVICE="${EYENET_DB_SERVICE:-postgres}"
DB_USER="${EYENET_DB_USER:-eyenet}"
DB_MAIN="${EYENET_DB_MAIN:-eyenet}"
DB_AUDIT="${EYENET_DB_AUDIT:-eyenet_audit}"

# The OCI label the version is baked into (see deploy/docker/Dockerfile). Standard, so
# docker inspect / skopeo / scanners already read it. This, read off the CONTAINER, is the
# truth of "what is running" ~ not the compose `image:` (that is the NEXT up) nor a state file.
LABEL=org.opencontainers.image.version

# Retained versions. Pruned by COUNT, not age: an age rule on a service idle for months
# wipes the whole history on the first new deploy, exactly when the previous version is
# the only thing to roll back to.
RETENTION="${EYENET_DEPLOY_RETENTION:-5}"

# A version this script made, not a hand tag or the plain live pointer. `<UTC>-<gittag>[-dirty]`.
# Anchored on the fixed-width UTC stamp so a text sort IS a time sort (that is where
# "the previous one" comes from, with no separate log).
FORMAT='^[0-9]{8}T[0-9]{6}Z-[0-9A-Za-z][0-9A-Za-z._+-]*$'

# Seconds the witness must stay up with zero restarts to count as "started", not merely
# "created" (a container that dies in CMD exists too, and respawns every few seconds ~
# exactly what a migration-crossing rollback does).
STABLE=15

log() { echo "[deploy] $(date -u +%FT%TZ) $*"; }

# ---- what is running: read the BAKED label off the witness container --------------------
running_version() {
	c=$(componer ps -q "$WITNESS" 2>/dev/null) || return 1
	[ -n "$c" ] || return 1
	docker inspect --format "{{index .Config.Labels \"$LABEL\"}}" "$c"
}

# Retained versions on this host, newest first. Lists the `eyenet:base-<version>` tags and
# strips the `base-` prefix. Text sort = time sort because the stamp is fixed width.
retained_versions() {
	docker image ls --format '{{.Tag}}' eyenet |
		sed -n 's/^base-//p' | grep -E "$FORMAT" | sort -r
}

# ---- "started" vs merely "created" -----------------------------------------------------
# Demands the asked-for label, Running, and ZERO restarts held for STABLE seconds.
check() {
	want="$1"
	have=$(running_version 2>/dev/null || true)
	if [ "$have" != "$want" ]; then
		log "BROKEN: asked for $want, container says ${have:-nothing}"
		return 1
	fi
	c=$(componer ps -q "$WITNESS")
	fmt='{{.State.Status}} {{.RestartCount}}'
	elapsed=0
	while [ "$elapsed" -lt "$STABLE" ]; do
		st=$(docker inspect --format "$fmt" "$c")
		case "$st" in
		"running 0") ;;
		*)
			log "BROKEN: $WITNESS not holding ($st). Last lines:"
			componer logs --tail 20 "$WITNESS" || true
			return 1
			;;
		esac
		sleep 3
		elapsed=$((elapsed + 3))
	done
	# The witness is `api`, but a crash-looping edge/worker would otherwise pass silently
	# (the edge Caddy misconfig did exactly that). No service in the composition may be
	# anything but `running`.
	bad=$(componer ps --format '{{.Name}} {{.State}}' | awk '$2 != "running" {print}')
	if [ -n "$bad" ]; then
		log "BROKEN: service(s) not running after $want came up:"
		printf '%s\n' "$bad" | while IFS= read -r line; do
			[ -n "$line" ] && log "  $line"
		done
		return 1
	fi
	log "running $want, stable; all services up"
}

# ---- can the target image continue from where the DBs are? -----------------------------
# The applied revision is read from each DB's alembic_version (main + audit). The target
# image "knows" a revision if versions/<rev>.py exists in its migration tree (the rev id
# IS the file stem here, e.g. 0022_stealer_processing). No alembic CLI, no DB access from
# the target image ~ pure file test.
db_revisions() {
	for db in "$DB_MAIN" "$DB_AUDIT"; do
		componer exec -T "$DB_SERVICE" \
			psql -U "$DB_USER" -d "$db" -tAc \
			'SELECT version_num FROM alembic_version' 2>/dev/null || true
	done | sed '/^$/d' | sort -u
}

rollback_crosses_a_migration() {
	target="$1"
	revs=$(db_revisions)
	if [ -z "$revs" ]; then
		log "could not read alembic_version from the DBs. With the schema state unknown,"
		log "rolling back is blind: not continuing."
		return 0 # treat unknown as "crosses" -> refuse
	fi
	missing=""
	for rev in $revs; do
		if ! docker run --rm --entrypoint python "eyenet:base-$target" -c "
import os, sys, eyenet
# Build the path off eyenet.__file__: the migrations dir is a namespace package (no
# __init__.py), so its own __file__ is None ~ dirname(None) would throw and be misread
# as 'revision missing', falsely refusing a safe rollback.
v = os.path.join(os.path.dirname(eyenet.__file__),
                 'storage', 'postgres_repo', 'migrations', 'versions', '$rev.py')
sys.exit(0 if os.path.exists(v) else 1)
" >/dev/null 2>&1; then
			missing="$missing $rev"
		fi
	done
	if [ -n "$missing" ]; then
		log "REFUSING: the DBs are at$missing, which \`$target\` does not have."
		log "Its boot \`upgrade_to_head\` would die on a revision it cannot locate and the"
		log "service would crash-loop. DOWN-migrate first with the CURRENT image (the only"
		log "one that has the revision), THEN roll back. See deploy/README."
		return 0
	fi
	return 1
}

# ---- prune: by count, after the new one is verified, never the running one -------------
prune() {
	keep=$(retained_versions | head -n "$RETENTION" | tr '\n' ' ')
	cur=$(running_version 2>/dev/null || true)
	for v in $(retained_versions); do
		case " $keep " in *" $v "*) continue ;; esac
		[ "$v" = "$cur" ] && continue
		for role in $ROLES; do
			docker image rm "eyenet:$role-$v" >/dev/null 2>&1 || true
		done
		log "pruned $v"
	done
}

# ---- the images actually have their RUNTIME deps, not just "api starts" -----------------
# check() watches `api`, which never touches spaCy / ulpextract ~ a build where the spaCy
# model download (from spaCy's release server, not pip) or a system lib silently failed
# passes check() and THEN crash-loops `sensor` or `stealer-processor`. preflight exercises
# the real deps in the freshly built images BEFORE they go up. Run after build.
preflight() {
	log "preflight: eyenet:base runtime deps (spaCy model, tdata chain, core)"
	docker run --rm --entrypoint python eyenet:base -c "
import spacy; spacy.load('es_core_news_sm')   # baked model, else the sensor crash-loops
import eyenet.identity_pool._tdata             # opentele + PyQt5/glib (tdata import path)
import telethon, nats, sqlmodel
print('base OK')
" || {
		log "preflight FAILED: eyenet:base is missing a runtime dependency. NOT deploying."
		return 1
	}
	log "preflight: eyenet:stealer runtime deps (ulpextract, clickhouse-connect)"
	docker run --rm --entrypoint sh eyenet:stealer -c \
		'test -x /usr/local/bin/ulpextract && python -c "import clickhouse_connect"' || {
		log "preflight FAILED: eyenet:stealer missing ulpextract / clickhouse-connect."
		return 1
	}
	log "preflight: eyenet:edge (built SPA + valid Caddyfile)"
	docker run --rm --entrypoint sh eyenet:edge -c \
		'test -f /srv/index.html && caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile' \
		>/dev/null 2>&1 || {
		log "preflight FAILED: eyenet:edge has no built SPA or an invalid Caddyfile."
		return 1
	}
	log "preflight OK"
}

# ---- verbs -----------------------------------------------------------------------------

deploy() {
	stamp=$(date -u +%Y%m%dT%H%M%SZ)
	if ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
		log "not a git checkout: nothing names this release. Not deploying."
		exit 78
	fi
	# Prod only takes TAGGED releases: HEAD must be exactly on a git tag. No loose commits.
	if ! tag=$(git -C "$ROOT" describe --exact-match --tags HEAD 2>/dev/null); then
		log "HEAD is not on a git tag. Tag the release (\`git tag -a vX.Y.Z\`), make sure"
		log "the server has it, then deploy. Prod only publishes named releases."
		exit 78
	fi
	# status --porcelain, not diff: UNTRACKED files enter the build context too, so a new
	# uncommitted module changes the image and the tag would lie. Mark it -dirty.
	dirty=""
	if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
		dirty="-dirty"
		log "working tree is dirty: \`$tag\` does not describe the build; marking -dirty"
	fi

	# A live deploy needs the DNS domain so Caddy can provision Let's Encrypt TLS for it. A
	# dev deploy (localhost, Caddy's internal self-signed CA) must opt in explicitly, so prod
	# never silently ships without a real cert.
	if [ -z "${EYENET_DOMAIN:-}" ] && [ "${EYENET_DEV:-}" != "1" ]; then
		log "EYENET_DOMAIN is not set. A live deploy needs the domain for TLS."
		log "Set EYENET_DOMAIN=your.domain (+ EYENET_ACME_EMAIL), or EYENET_DEV=1 for a dev"
		log "deploy (localhost, Caddy internal CA)."
		exit 78
	fi

	version="$stamp-$tag$dirty"
	export EYENET_VERSION="$version" # consumed as a build arg -> the OCI label
	log "building $version"
	componer build
	preflight || exit 1
	componer up -d
	check "$version"

	# Preserve this build under its versioned tags (the live `eyenet:base` the build just
	# wrote is the mutable pointer; these are the retained history). Done AFTER verify.
	for role in $ROLES; do
		docker tag "eyenet:$role" "eyenet:$role-$version"
	done
	prune
	log "deployed $version"
}

rollback() {
	cur=$(running_version 2>/dev/null || true)
	if [ -z "$cur" ]; then
		log "nothing is running: nowhere to roll back from. Use \`deploy\`."
		exit 1
	fi
	target="${1:-}"
	if [ -z "$target" ]; then
		# "The previous one" = the one before what is RUNNING (not the 2nd in the list;
		# after a rollback those differ, and the 2nd would walk you FORWARD again).
		target=$(retained_versions | grep -A1 -x -F "$cur" | sed -n 2p || true)
	fi
	if [ -z "$target" ]; then
		log "no version before $cur is retained on this host."
		log "Retained: $(retained_versions | tr '\n' ' ')"
		exit 1
	fi
	for role in $ROLES; do
		if ! docker image inspect "eyenet:$role-$target" >/dev/null 2>&1; then
			log "missing \`eyenet:$role-$target\` on this host. A half rollback (base on one"
			log "version, stealer on another) is worse than none. Not continuing."
			exit 1
		fi
	done
	if rollback_crosses_a_migration "$target"; then
		exit 1
	fi

	log "rolling back from $cur to $target"
	# Repoint the live pointers at the retained target, then up WITHOUT build. A rollback
	# that rebuilds from the tree is not a rollback ~ it is another deploy that can fail
	# for the very reason you are rolling back.
	for role in $ROLES; do
		docker tag "eyenet:$role-$target" "eyenet:$role"
	done
	componer up -d --no-build
	check "$target"
	log "rolled back to $target"
}

versions() {
	cur=$(running_version 2>/dev/null || true)
	echo "running: ${cur:-nothing}"
	case "$cur" in
	'' | dev)
		[ "$cur" = dev ] && echo "  ^ a hand build (compose build with no version); cannot roll back to it." ;;
	esac
	echo "retained (max $RETENTION, newest first):"
	retained_versions | sed 's/^/  /'
}

# ---- guard rails -----------------------------------------------------------------------
case "$RETENTION" in
'' | *[!0-9]*)
	log "EYENET_DEPLOY_RETENTION=$RETENTION is not an integer."
	exit 78
	;;
esac
if [ "$RETENTION" -lt 2 ]; then
	log "EYENET_DEPLOY_RETENTION=$RETENTION leaves no previous version ~ nothing to roll back to."
	exit 78
fi

case "${1:-}" in
deploy) deploy ;;
rollback)
	shift
	rollback "$@"
	;;
versions) versions ;;
*)
	echo "usage: $0 deploy | rollback [VERSION] | versions" >&2
	exit 64
	;;
esac
