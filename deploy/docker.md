# ComplyOS: container deployment

This is a deployment reference for running the ComplyOS dashboard (`complyos
serve-dashboard`) in a container. It complements the systemd/cron templates
under `deploy/systemd/` and `deploy/cron.d/`, which target a bare-metal or VM
host running the periodic notification/expiry/source-intel jobs alongside the
dashboard. Containerizing those jobs too is out of scope here — this covers
the web dashboard service only.

Nothing here is a compliance or security certification. It documents how the
container is built and configured; the operator is responsible for the
authentication, TLS, backup, and retention posture their deployment actually
needs. See `docs/compliance-readiness.md` for the readiness-vs-certification
distinction that applies to the product as a whole.

## Quickstart

Build the image:

```bash
docker build -t complyos:dev .
```

Run it directly, with a local `./data` directory for the SQLite file:

```bash
mkdir -p data
docker run -d \
  --name complyos \
  -p 127.0.0.1:8000:8000 \
  -v "$(pwd)/data:/data" \
  -e COMPLYOS_API_TOKEN="change-me" \
  complyos:dev
```

Or with Compose (see `docker-compose.yml` for the full annotated environment
block):

```bash
docker compose up -d --build
```

Check health, then log in to the shell:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"complyos-dashboard"}
```

Open `http://127.0.0.1:8000/shell/login` in a browser. With
`COMPLYOS_API_TOKEN` set (recommended), enter that token as the login
password — the session pins role `owner`. See "Secured vs insecure-local
posture" below for the alternative.

The container binds `0.0.0.0:8000` *inside* itself (required so Docker's
network can reach it); the host-side exposure is controlled by the `-p` /
`ports:` mapping, which defaults to `127.0.0.1` — loopback only. Nothing is
reachable off the host unless you deliberately change that mapping or put a
reverse proxy in front (see "TLS" below).

## Database location

`complyos serve-dashboard` takes `--host`, `--port`, and `--dry-run` — there
is no `--db` flag. The database location is controlled entirely by the
`COMPLYOS_DATABASE_URL` environment variable (see
`complyos/models/database.py:resolve_database_url`). The image sets a default
of `sqlite:////data/complyos.db`, so with the `/data` volume mounted, no
further configuration is needed for the local-first SQLite path.

To use Postgres instead, override `COMPLYOS_DATABASE_URL` with a
`postgresql+psycopg://...` URL. That requires the `postgres` extra
(`psycopg[binary]`), which is **not** installed in this image — build a
derived image with `pip install .[postgres]` if you need it.

## Secured vs insecure-local posture

By default, with no `COMPLYOS_API_TOKEN` and no opt-in set, the container
fails closed:

- `/api/v1/*` returns `401 unauthorized` — the API refuses to trust
  attacker-controlled role/tenant headers on an unauthenticated surface.
- `/shell/login` refuses with "Console authentication is not configured."
- The legacy unauthenticated `/api/audit`, `/api/summary`, and `/dashboard`
  routes remain reachable in this state (they predate the auth gate) — see
  below for disabling them.

Two ways to run it:

**Secured (recommended for anything beyond a laptop demo).** Set
`COMPLYOS_API_TOKEN` to a real secret:

- `/api/v1/*` requires `Authorization: Bearer <token>`.
- `/shell/login` accepts that same token as the login field and pins the
  session to role `owner`.
- The legacy unauthenticated `/api/audit`, `/api/summary`, and `/dashboard`
  routes become `404` automatically once a token is set (they only stay
  live if you also set `COMPLYOS_ALLOW_INSECURE_LOCAL`, below).
- Optionally set `COMPLYOS_SESSION_SECRET` to sign the shell session cookie
  with a different secret than the API token, so rotating one doesn't log
  everyone out of the other.

**Insecure-local (single trusted operator, loopback only).** Set
`COMPLYOS_ALLOW_INSECURE_LOCAL=1` and leave `COMPLYOS_API_TOKEN` unset:

- `/api/v1/*` trusts caller-supplied `X-Actor-Role` / `X-Tenant-Id` headers
  with no token check.
- `/shell/login` accepts any role selection with no token.
- The legacy `/api/audit`, `/api/summary`, `/dashboard` routes stay live,
  unauthenticated.

Never combine `COMPLYOS_ALLOW_INSECURE_LOCAL` with a host-side port mapping
that isn't `127.0.0.1`. If you need multi-operator or remote access, use the
secured posture and put a reverse proxy with its own access control in
front.

## Backup

The SQLite file under the mounted `/data` volume (`./data/complyos.db` with
the default compose setup) **is the entire application state**: users,
enrollments, evidence ledger, audit snapshots, imports, notifications
outbox, everything. Back it up by copying that file/directory — there is no
separate secrets store or external database to also capture in the default
SQLite configuration.

For a consistent copy while the container is running, either stop the
container first or use SQLite's own backup mechanism (`sqlite3
data/complyos.db ".backup data/complyos.db.bak"`) rather than a raw `cp`,
which can race an in-flight write. See `docs/backup-restore-dr-plan.md` for
the fuller backup/restore/DR posture and RTO/RPO targets.

If you switch `COMPLYOS_DATABASE_URL` to Postgres, back that database up
through your normal Postgres backup path instead — the `/data` volume is
then unused by the application (aside from any exported CSV/evidence
artifacts, if configured to write there).

## TLS

This container serves plain HTTP. Put a TLS-terminating reverse proxy (e.g.
Caddy, nginx, Traefik) in front of it for anything reachable off the host —
do not expose port 8000 directly to the network.

Once a proxy is terminating HTTPS in front of the shell, set
`COMPLYOS_SESSION_SECURE=1` (checked in `complyos/web/shell.py`) so the
`/shell` session cookie gets the `Secure` flag and is only ever sent back
over HTTPS. Leave it unset for local HTTP-only access (the default), since a
`Secure` cookie will not be sent back to the browser over plain HTTP and
you'll get stuck at the login redirect.
