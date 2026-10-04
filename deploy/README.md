# Deploying the test version on one server

The whole app runs on one Linux server with Docker Compose. You choose how visitors
reach it:

| Mode | How visitors get in | Inbound ports | Address |
| --- | --- | --- | --- |
| `https` (default) | Straight to your server; **Caddy** handles HTTPS | 80 and 443 open | `https://<your-ip-with-dashes>.sslip.io`, or your own domain |
| `tunnel` | Through Cloudflare. A **Cloudflare Tunnel** container connects *out* from your server, and requests come back down that connection | **None** | Random `https://<words>.trycloudflare.com`; changes when the tunnel restarts |

```
https:   Internet ──443──▶ Caddy ──▶ nginx (app + /api) ──▶ Flask ──▶ MySQL
tunnel:  Internet ──▶ Cloudflare ◀── outbound ── cloudflared ──▶ nginx ──▶ Flask ──▶ MySQL
```

In both modes MySQL, Flask and nginx listen only inside the server.

**Which to pick:** use `tunnel` if you can't or don't want to open ports, or just need a
link for a reviewer quickly. Use `https` for an address that stays the same.

## 1. The server

- **Linux:** Ubuntu 24.04/22.04, Debian 12, AlmaLinux / Rocky Linux / RHEL 8 or 9, or CentOS
  Stream 9. Check with `cat /etc/os-release`.
- **Memory:** 1 GB or more. 2 GB is more comfortable; with root, the script adds swap on
  smaller servers.
- **https mode only:** a public IPv4 address, with inbound ports 80 and 443 open in the
  provider's firewall. That is a separate setting from the server's own firewall: a
  "security group" on AWS, a "firewall" on DigitalOcean, Hetzner and Google Cloud.

**Docker already installed?** The script detects it and skips the install. It needs
Docker Compose v2: `docker compose version` should print a version.

## 2. Run the setup script

You need **one** of these:

- **root**, or a user that can run `sudo`. The script can then also install Docker, add
  swap and open firewall ports.
- **a user that can run `docker`** without sudo. Check with `docker ps`: if it lists
  containers, or an empty table, without a permission error, you're fine. The
  root-only steps are skipped and the app goes in `~/inventory-tracker`. To give a user
  this access, run as root `usermod -aG docker <user>`, then log out and back in.

**Tunnel mode (no open ports):**

```bash
curl -fsSL https://raw.githubusercontent.com/DanTransfat/InventoryTracker/main/deploy/setup-vm.sh | MODE=tunnel bash
```

**https mode:**

```bash
curl -fsSL https://raw.githubusercontent.com/DanTransfat/InventoryTracker/main/deploy/setup-vm.sh | bash
```

To use sudo, put it before the variables: `... | sudo MODE=tunnel bash`. To use your own
domain in https mode, point its DNS A record at the server and add `DOMAIN=inventory.example.com`.

The first run takes 5 to 10 minutes on a small server. It:

1. checks for Docker, git and curl, and installs what's missing (needs root),
2. adds swap on servers with under 2 GB of memory (needs root),
3. opens ports 80 and 443 in ufw or firewalld (https mode, needs root; skipped in tunnel mode),
4. clones the repo,
5. writes `.env` with random passwords, readable only by you,
6. builds and starts everything, waits until the app answers, and prints the address.

**Switching modes later:** run the same command again with the other `MODE`. Passwords
and data are kept.

## 3. Day-to-day

Run these in the app folder (`/opt/inventory-tracker` as root, else `~/inventory-tracker`),
as the same user that ran setup:

| Task | Command |
| --- | --- |
| Deploy the latest code from GitHub | `deploy/update.sh` |
| Watch logs | `docker compose logs -f` |
| Status | `docker compose ps` |
| Current tunnel address | `docker compose logs tunnel \| grep trycloudflare` |
| Back up the database | `deploy/backup.sh` (daily cron line inside the script) |
| Stop | `docker compose down` (data is kept) |
| Wipe and start fresh | `docker compose down -v`, then `deploy/update.sh` (deletes all data and reseeds) |

Plain `docker compose` picks the right files for your mode from `COMPOSE_FILE` in `.env`.
Updates keep the database, `.env` and certificates, and new migrations apply automatically.

## If something goes wrong

| Symptom | Likely cause |
| --- | --- |
| `is not in the sudoers file` | That user can't use sudo. Log in as root, or use a user in the `docker` group (section 2) |
| `this user can't use Docker` | Same as above |
| https mode: browser can't connect | Ports 80/443 closed in the **provider's** firewall. Or use tunnel mode |
| https mode: certificate error | Same as above (Let's Encrypt must reach the server), or your domain's DNS isn't pointing at it yet |
| Tunnel address stopped working | The tunnel restarted and got a new address. Run `docker compose logs tunnel \| grep trycloudflare` |
| "did not become healthy" | Read the logs the script prints. On a 1 GB server without swap, the build may run out of memory |
| 502 right after start | The API is still migrating or seeding; wait 30 seconds |

## Before you share the link

This is a **test** deployment. The app has no login, so anyone with the link can change
inventory data. That's fine for a reviewer, but don't put real data in it. Cloudflare
describes quick tunnels as meant for testing, with no uptime guarantee. For a fixed tunnel
address, create a named tunnel in a free Cloudflare account; see the comment at the top of
`docker-compose.tunnel.yml`.

## What CI checks

On every push, two jobs in `.github/workflows/ci.yml` start the production stack:

- **deploy-smoke (https mode, served over plain HTTP):** checks the pages, the API and the
  ledger through Caddy. It also checks that MySQL, Flask and nginx are not reachable from
  outside, and that the backup script works.
- **deploy-tunnel:** checks that no ports are open, then opens a real Cloudflare tunnel and
  loads the app through its public address.

HTTPS certificates in https mode can only be tested on a real server with a public address.
