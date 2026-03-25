# Hermes for Rabbit R1

A native Rabbit R1 platform adapter for [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — talk to Hermes AI (full memory, skills, crons) directly from your R1, from anywhere.

**Tested and working on real R1 hardware** via both Tailscale Funnel and Cloudflare Tunnel.

## The problem with OpenClaw

The official OpenClaw setup only works on your home WiFi. The install script even warns:
> *"Do not run on cloud instances where your IP is publicly accessible."*

Walk out your front door onto cellular — your R1 stops working.

## How this is different

```
R1 (anywhere with internet)
    |  wss://yourname.ts.net  (TLS, Tailscale Funnel)
VM / always-on server
    |
rabbit_r1.py  (Hermes BasePlatformAdapter)
    |
Hermes -> Claude / Ollama (full memory, skills, crons)
```

The adapter runs on a VM with a tunnel so the R1 connects via a stable public `wss://` URL — exactly the same model as Telegram. Works from home, coffee shop, cellular, anywhere.

## Features

- **Works from any network** — not just home WiFi
- **Full Hermes AI** — same memory, skills, and crons as your Telegram/Discord setup
- **Shared memory** — tell Hermes something on Telegram, your R1 already knows it
- **Secure** — TLS end-to-end, random token auth, device ID validation
- **QR code pairing** — printed on startup, scan with R1 to connect
- **Two tunnel options** — Tailscale Funnel (no extra account) or Cloudflare Tunnel (free account)
- **Standard adapter pattern** — same as `telegram.py`, `discord.py`, ready for upstream PR

## Quick start

### 1. Install dependencies

```bash
pip install websockets qrcode
```

### 2. Test the protocol (no Hermes needed)

```bash
# Start Tailscale Funnel
tailscale funnel 18789

# In another terminal
RABBIT_R1_HOST=yourhost.ts.net \
RABBIT_R1_PUBLIC_PORT=443 \
RABBIT_R1_PROTO=wss \
python test_server.py
```

Scan the QR code with your R1. It should echo back your messages.

### 3. Wire into Hermes

```bash
cp gateway/platforms/rabbit_r1.py /path/to/hermes-agent/gateway/platforms/
```

Then apply the integration changes listed in [docs/platforms/rabbit_r1.md](docs/platforms/rabbit_r1.md).

### 4. Configure and run

```bash
export RABBIT_R1_TUNNEL=tailscale   # or cloudflare, or none
export RABBIT_R1_PORT=18789         # optional, default 18789
# RABBIT_R1_TOKEN auto-generates if not set
```

On startup, the adapter will:
1. Open the tunnel on port 18789
2. Print a QR code to the terminal
3. Wait for your R1 to scan and connect

## Tunnel options

| Option | Extra account? | Stability | Setup |
|--------|---------------|-----------|-------|
| **Tailscale Funnel** (default) | No | Stable URL | `tailscale funnel 18789` |
| **Cloudflare Tunnel** | Free account | Stable URL | Install `cloudflared` |
| `none` | N/A | LAN only | Nothing |

Both tunnels have been tested and confirmed working on real R1 hardware.

## Security

- TLS encryption via the tunnel (wss://)
- Random 32-char hex token — required for every connection
- Device ID validation — only your specific R1 is accepted
- Token rotates each session (new QR code = new token)
- No ports raw-exposed to the internet

## Shared memory with other platforms

Because this is a standard Hermes platform adapter, it shares the same Hermes brain as your Telegram, Discord, and other platforms:

- Tell Hermes something on Telegram -> your R1 already knows it
- Set a cron job on your R1 -> can deliver to Telegram
- Same skills and tools available everywhere

## PR to NousResearch/hermes-agent

This is developed here first (tested on real R1 hardware), then submitted as a PR to the main hermes-agent repo. See [docs/platforms/rabbit_r1.md](docs/platforms/rabbit_r1.md) for the full list of 16 integration points.

## Project structure

```
gateway/platforms/rabbit_r1.py   -- main adapter (~600 lines)
test_server.py                   -- standalone test server (no Hermes needed)
tests/gateway/test_rabbit_r1.py  -- unit tests
docs/platforms/rabbit_r1.md      -- integration guide for the PR
```
