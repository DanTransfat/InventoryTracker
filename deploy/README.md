# Deploying the test version on one server

The whole app runs on one small Linux server with Docker Compose. Only **Caddy** is
reachable from the internet (ports 80 and 443). It fetches a free HTTPS certificate
automatically and forwards requests to the app. MySQL and the Flask API listen only
inside the server.

```
Internet ──443──▶ Caddy (HTTPS) ──▶ nginx (frontend + /api proxy) ──▶ Flask ──▶ MySQL
                  public            private                            private   private
```

## 1. Create the server

Any provider works. You need:

- **Ubuntu 24.04/22.04, Debian 12, AlmaLinux / Rocky Linux / RHEL 8 or 9, or CentOS Stream 9**
  (check with `cat /etc/os-release`)
- **1 GB of RAM or more** (2 GB is more comfortable; the script adds swap on smaller servers)
- **A public IPv4 address**
- **Inbound ports 22, 80 and 443 open** in the provider's firewall. This is a separate
  setting from the server's own firewall: a "security group" on AWS, a "firewall" on
  DigitalOcean, Hetzner and Google Cloud, or "ingress rules" on Oracle Cloud.

Log in with an SSH key, not a password. Servers with password login get constant
automated guessing attempts from bots.

## 2. Run the setup script

The script needs **root**. Either log in as root, or use an account that can run `sudo`.
If you see `<user> is not in the sudoers file`, log in as root instead (many providers
set the root password in their control panel), or give your user sudo rights as root:
`usermod -aG wheel <user>` on AlmaLinux/Rocky/RHEL, `usermod -aG sudo <user>` on
Ubuntu/Debian, then log out and back in.

SSH in, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/DanTransfat/InventoryTracker/main/deploy/setup-vm.sh | sudo bash
```

Logged in as root, `| bash` works too. It takes 5 to 10 minutes on a small server. It:

1. installs Docker,
2. adds swap if the server has under 2 GB of memory,
3. opens ports 22, 80 and 443 in the server's firewall (ufw or firewalld),
4. clones the repo into `/opt/inventory-tracker`,
5. writes `.env` with random passwords (readable only by root),
6. builds and starts everything, then waits until the app answers.

At the end it prints your address, for example `https://203-0-113-7.sslip.io`. That
hostname comes from [sslip.io](https://sslip.io), a free service that resolves any
`<your-ip-with-dashes>.sslip.io` name to that IP, so you get real HTTPS without buying a
domain. The first visit can take up to a minute while the certificate is issued.

**Using your own domain instead:** point its DNS A record at the server's IP, then run
`... | sudo DOMAIN=inventory.example.com bash`. To switch later, edit `SITE_ADDRESS` in
`/opt/inventory-tracker/.env` and run the update script.

## 3. Day-to-day

| Task | Command (on the server) |
| --- | --- |
| Deploy the latest code from GitHub | `sudo /opt/inventory-tracker/deploy/update.sh` |
| Watch logs | `cd /opt/inventory-tracker && sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f` |
| Status | `... ps` (same prefix as above) |
| Back up the database | `sudo /opt/inventory-tracker/deploy/backup.sh` (daily cron line inside the script) |
| Stop | `... down` (data is kept) |
| Wipe and start fresh | `... down -v`, then the update script (deletes all data and reseeds) |

Updates keep the database, `.env` and certificates. New migrations apply automatically
when the API container starts.

## If something goes wrong

| Symptom | Likely cause |
| --- | --- |
| Browser can't connect at all | Ports 80/443 closed in the **provider's** firewall |
| Certificate or "not secure" error | Same as above (Let's Encrypt must reach port 80/443), or a custom domain's DNS isn't pointing at the server yet |
| Script stops at "did not become healthy" | Read the logs it prints. On a 1 GB server without swap, the build may be killed for lack of memory |
| 502 from Caddy right after start | The API is still migrating or seeding; wait 30 seconds |

## Before you share the link

This is a **test** deployment. The app has no login, so anyone with the link can change
inventory data. That is fine for a reviewer, but don't put real data in it. Seed data is
loaded only on the first start, when the database is empty.

## What CI checks

The `deploy-smoke` job in `.github/workflows/ci.yml` starts this same production stack on
every push. It goes through Caddy on port 80 and checks that:

- the page and deep links load,
- the API answers and the ledger reconciles,
- MySQL, Flask and nginx are **not** reachable from outside the host,
- the backup script produces a dump.

HTTPS itself can only be tested on a real server with a public hostname.
