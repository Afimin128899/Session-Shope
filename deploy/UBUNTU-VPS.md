# Native VPS deployment

Target: Ubuntu 24, public IPv4 `31.77.59.42`, domain `sbandsub.space`.
The bot is already managed by systemd. Keep the existing service, working directory,
Python environment, secrets and database settings. Use Caddy as the HTTPS proxy.

## Prerequisites

- The VPS must contain version 3.0.0, including `miniapp/` and `utils/miniapp.py`.
- DNS A record `sbandsub.space` points to `31.77.59.42`; an AAAA record, if present,
  must also point to this server's working IPv6 address.
- The service's Python environment has dependencies from `requirements.txt`.
- Ports 80/443 are free, and permitted by the VPS and provider firewall.
- The existing bot service has a working `WorkingDirectory` and access to its database.

If the bot service name is unknown, list service names without exposing environment values:

```sh
systemctl list-unit-files --type=service --no-pager | grep -Ei 'bot|shop|telegram'
```

## Clean reinstalled VPS

Use `install-fresh.sh` from the repository (the download command is in `MINIAPP.md`).
It clones into `/opt/session-shope`, prepares a local MariaDB and then invokes
`install.sh --fresh`. Credentials are entered only in the server's interactive
terminal; they are not command-line arguments. A private installer marker in
`/etc/session-shope` permits retries without resetting credentials or taking over
an unrelated database. Source database contents are not restored by this process.

## One-command install (Ubuntu 24)

After updating the checkout and keeping its existing `.env`:

```sh
sudo bash install.sh
```

The script installs Ubuntu packages and project requirements into `.venv-miniapp`,
configures the existing systemd service (or creates one if none exists), waits for
the local API, and configures Caddy for `sbandsub.space`. The domain must point to
`31.77.59.42`, with ports 80/443 available. It preserves `.env` and unrelated Caddy
sites, backs up modified Caddy files, validates configuration before reload, and
restores those files if validation fails.

Selectors: `sudo bash install.sh --service shop.service`, or `--skip-https` to use
an existing reverse proxy. The installer does not pull/reset Git or modify the
working database. It restarts the bot, whose normal startup runs existing schema
migrations. Dependencies require working Ubuntu/Python package repositories.

## Automatic systemd setup

After uploading version 3.0.0 into the existing project directory, run:

```sh
sudo python3 deploy/create_service.py
```

The installer determines the checkout path, looks for its existing systemd unit,
and installs only the Mini App environment drop-in. If no matching service exists,
it can create `session-shope.service` using the checkout owner's account and the
existing `.venv`/`venv` Python. It stops if another unmanaged `bot.py` is already
running or dependencies are unavailable. An existing, different configuration is
preserved. Credentials remain in the project's existing `.env`.

Optional selectors: `--service shop.service` or
`--python /path/to/venv/bin/python`. This configures systemd only;
HTTPS still uses the Caddy steps below.

## Existing bot service

Replace `YOUR-BOT.service` and `/path/to/Session-Shope` below with the real unit and checkout.
Use `deploy/miniapp-systemd.conf` as a drop-in:

```sh
sudo install -d /etc/systemd/system/YOUR-BOT.service.d
sudo install -m 644 /path/to/Session-Shope/deploy/miniapp-systemd.conf \
  /etc/systemd/system/YOUR-BOT.service.d/miniapp.conf
sudo systemctl daemon-reload
sudo systemctl restart YOUR-BOT.service
curl --fail http://127.0.0.1:8080/api/health
```

Do not create another polling service for the same bot token. The drop-in changes
only three non-secret environment variables. Existing DB and Telegram credentials
stay in their current configuration.

## Caddy

Install Caddy from its official Ubuntu/Debian package source, keeping package
signature and TLS verification enabled:
https://caddyserver.com/docs/install#debian-ubuntu-raspbian

If `/etc/caddy/Caddyfile` already serves other sites, add the block from
`deploy/Caddyfile.vps` while preserving those sites. Otherwise install this file:

```sh
sudo install -m 644 /path/to/Session-Shope/deploy/Caddyfile.vps /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
curl --fail https://sbandsub.space/api/health
```

Caddy obtains and renews the HTTPS certificate. Successful `/api/health` establishes
web-process availability only. Finally open the Mini App through the bot to check
Telegram authorization, catalog, balance and a purchase in the intended test account.

## Rollback

Remove only `/etc/systemd/system/YOUR-BOT.service.d/miniapp.conf`, run
`systemctl daemon-reload` and restart the existing bot unit. To remove public access,
remove this domain's Caddy block and validate/reload Caddy, preserving other sites.
No database rollback is required for the optional Mini App.
