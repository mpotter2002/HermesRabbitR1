# Hermes for Rabbit R1

A native Rabbit R1 platform adapter for [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — talk to Hermes AI (full memory, skills, crons) directly from your R1, from anywhere.

## The problem with OpenClaw

The official OpenClaw setup only works on your home WiFi. The install script even warns:
> *"Do not run on cloud instances where your IP is publicly accessible."*

Walk out your front door onto cellular — your R1 stops working.

## How this is different

```
R1 (anywhere with internet)
    ↓  wss://yourname.ts.net  (TLS, Tailscale Funnel)
VM / always-on server
    ↓
rabbit_r1.py  (Hermes BasePlatformAdapter)
    ↓
Hermes → Claude / Ollama (full memory, skills, crons)
```

The adapter runs on a VM with a Tailscale Funnel (or Cloudflare Tunnel) so the R1 connects via a stable public `wss://` URL — exactly the same model as Telegram. Works from home, coffee shop, cellular, anywhere.

## Features

- Works from any network — not just home WiFi
- Full Hermes AI — same memory, skills, and crons as your Telegram/Discord setup
- Secure — TLS end-to-end via Tailscale Funnel, token auth, port never raw-exposed
- QR code printed on startup — scan with R1 to pair
- Auto-starts Tailscale Funnel on platform startup
- Follows the standard `BasePlatformAdapter` pattern (same as `telegram.py`, `discord.py`)

## Setup

### 1. Install dependencies

```bash
pip install websockets qrcode
```

### 2. Configure

```bash
export RABBIT_R1_TOKEN=$(openssl rand -hex 32)   # or set a fixed token
export RABBIT_R1_PORT=18789                       # optional, default 18789
export RABBIT_R1_TUNNEL=tailscale                 # tailscale | cloudflare | none
```

### 3. Drop the adapter into hermes-agent

```bash
cp gateway/platforms/rabbit_r1.py /path/to/hermes-agent/gateway/platforms/
```

Then apply the small wiring changes listed in [docs/platforms/rabbit_r1.md](docs/platforms/rabbit_r1.md).

### 4. Start Hermes

On startup, the adapter will:
1. Open a Tailscale Funnel on port 18789
2. Print a QR code to the terminal
3. Wait for your R1 to scan and connect

## Tunnel options

| Option | Stability | Cost | Setup |
|--------|-----------|------|-------|
| Tailscale Funnel (default) | Stable URL | Free | Already installed with Hermes |
| Cloudflare Tunnel | Stable URL | Free | Requires `cloudflared` |
| `RABBIT_R1_TUNNEL=none` | LAN only | Free | No tunnel needed |

## PR to NousResearch/hermes-agent

This is developed here first (to test on a real R1), then submitted as a PR to the main hermes-agent repo. See [docs/platforms/rabbit_r1.md](docs/platforms/rabbit_r1.md) for the full list of integration points.

## Shared memory with other platforms

Because this is a standard Hermes platform adapter, it shares the same Hermes brain as your Telegram, Discord, and other platforms:

- Tell Hermes something on Telegram → your R1 already knows it
- Set a cron job on your R1 → can deliver to Telegram
- Same skills and tools available everywhere
