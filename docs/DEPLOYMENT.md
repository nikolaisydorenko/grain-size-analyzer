# Deployment

The analyzer is a single Flask process (served by waitress when installed) with no
external services — the database is an embedded DuckDB file next to the app. Any
way you can run a Python process works: a laptop, a VM, a container, a small
home server.

## Configuration

Everything is configured with environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `5066` | HTTP port to listen on |
| `GRAINSIZE_DB` | `./grainsize.duckdb` | Path of the DuckDB results store |

The app also writes to `cache/` (display JPEGs + `index.json`, `folders.json`,
`grid.json`) inside its working directory, so run it from — or install it to — a
directory the service user can write.

## Docker

The simplest deployment:

```bash
docker compose up -d
# open http://localhost:5066
```

Override the port with `PORT` (see `docker-compose.yml`). Persist `cache/` and the
DuckDB file with volumes so your images and measurements survive container
rebuilds.

## systemd (bare metal / VM)

Install to `/opt/grainsize` with a virtualenv:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin grainsize
sudo mkdir -p /opt/grainsize && sudo cp -r . /opt/grainsize
cd /opt/grainsize
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo chown -R grainsize:grainsize /opt/grainsize
```

`/etc/systemd/system/grainsize.service`:

```ini
[Unit]
Description=Grain Size Analyzer (ASTM E112) Flask app
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=grainsize
WorkingDirectory=/opt/grainsize
Environment=PORT=5066
Environment=GRAINSIZE_DB=/opt/grainsize/grainsize.duckdb
ExecStart=/opt/grainsize/.venv/bin/python3 /opt/grainsize/app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now grainsize
journalctl -u grainsize -f     # logs
```

## Operational notes

- **Reverse proxy / TLS:** the app itself speaks plain HTTP. If you expose it
  beyond localhost, put it behind nginx/Caddy/Traefik for TLS and access control —
  there is no built-in authentication.
- **Schema changes:** the table is created with `CREATE TABLE IF NOT EXISTS`,
  which will **not** migrate an existing DB. After upgrading across a schema
  change, stop the service, move the old `grainsize.duckdb` aside, and restart
  (back it up first if it holds real measurements).
- **Backups:** the complete state is `grainsize.duckdb` + the `cache/` folder.
  Copy both to back up a project; restoring is just putting them back.
- **Redeploy:** replace `app.py`, then `systemctl restart grainsize` (or
  `docker compose up -d --build`).
