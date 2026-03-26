# Hermes for Rabbit R1

A native Rabbit R1 platform adapter for [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — talk to Hermes AI (full memory, skills, crons) directly from your R1, from anywhere.

**Tested and working on real R1 hardware** via both Tailscale Funnel and Cloudflare Tunnel.

## Why not OpenClaw?

OpenClaw only works on your home WiFi. Their install script even warns:

> *"Do not run on cloud instances where your IP is publicly accessible."*

Walk out your front door onto cellular — your R1 stops working. This adapter fixes that.

| | OpenClaw | This adapter |
|---|---------|-------------|
| Home WiFi | Yes | Yes |
| Coffee shop WiFi | No | **Yes** |
| Cellular / mobile data | No | **Yes** |
| Travelling | No | **Yes** |
| Shared memory with Telegram/Discord | No | **Yes** |
| Skills, crons, tools | No | **Yes** |
| TLS encryption | No | **Yes** |

## How it works

```
R1 (anywhere with internet)
    |  wss://yourhost.ts.net  (TLS encrypted)
    v
Your VM or home server
    |
    v
rabbit_r1.py  (Hermes BasePlatformAdapter)
    |
    v
Hermes -> Claude / Ollama / any AI  (full memory, skills, crons)
```

The adapter runs a WebSocket server with a tunnel so the R1 connects via a stable public `wss://` URL — exactly the same model as Telegram. Works from home, coffee shop, cellular, anywhere.

## Features

- **Works from any network** — not just home WiFi
- **Full Hermes AI** — same memory, skills, and crons as your Telegram/Discord setup
- **Shared memory** — tell Hermes something on Telegram, your R1 already knows it
- **Secure** — TLS end-to-end, random token auth, device ID validation
- **QR code pairing** — saved as PNG and printed on startup, scan with R1 to connect
- **Two tunnel options** — Tailscale Funnel (no extra account) or Cloudflare Tunnel (free account)
- **Standard adapter pattern** — same as `telegram.py`, `discord.py`, ready for upstream PR
- **Cost effective** — works with free local models via Ollama, zero API costs if you want

## Setup guide: VM / cloud server

If you run Hermes on a VM or cloud server (Google Cloud, AWS, DigitalOcean, etc.), you need a tunnel so your R1 can reach it from the internet.

### 1. Install dependencies

```bash
pip install websockets qrcode
```

### 2. Test the protocol first (no Hermes needed)

```bash
# Terminal 1: Start a tunnel
tailscale funnel --bg 18789
# OR: cloudflared tunnel --url http://localhost:18789

# Terminal 2: Run the test server
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

### 4. Configure

Add to your Hermes `.env` file:

```bash
RABBIT_R1_TOKEN=$(openssl rand -hex 32)
RABBIT_R1_TUNNEL=tailscale    # or cloudflare, or none
RABBIT_R1_PUBLIC_URL=wss://yourhost.ts.net  # if tunnel auto-detect fails
```

### 5. Start

```bash
# Make sure the tunnel is running
tailscale funnel --bg 18789

# Restart Hermes
hermes gateway restart
```

The QR code will be saved as a PNG at `~/.hermes/rabbit_r1_qr.png`. Open it on any device and scan with your R1.

## Setup guide: local machine (home server, Raspberry Pi, etc.)

If you run Hermes on a machine on your home network, the R1 can connect directly over WiFi without any tunnel.

### 1. Install dependencies

```bash
pip install websockets qrcode
```

### 2. Configure

```bash
export RABBIT_R1_TUNNEL=none    # no tunnel needed on local network
export RABBIT_R1_PORT=18789
# RABBIT_R1_TOKEN auto-generates if not set
```

### 3. Start Hermes

The adapter will detect your LAN IP and generate a QR code. Scan it with your R1 while on the same WiFi network.

**Want it to work from outside your home too?** Add a tunnel:

```bash
# One-time setup
sudo tailscale set --operator=$USER
tailscale funnel --bg 18789

# Then set in .env:
RABBIT_R1_TUNNEL=tailscale
```

Now your R1 works from anywhere, not just home.

## Getting the QR code

The QR code can be accessed in multiple ways:

| Method | How |
|--------|-----|
| **PNG file** (recommended) | Saved automatically at `~/.hermes/rabbit_r1_qr.png` |
| **Terminal** | Printed in the gateway logs on startup |
| **Generate on any device** | Run the Python snippet below with your token |

Generate a QR code on any machine with Python:

```bash
pip install qrcode
python3 -c "
import qrcode
qr = qrcode.QRCode(border=1)
qr.add_data('{\"type\":\"clawdbot-gateway\",\"version\":1,\"ips\":[\"YOUR_HOST\"],\"port\":443,\"token\":\"YOUR_TOKEN\",\"protocol\":\"wss\"}')
qr.make(fit=True)
qr.print_ascii(invert=True)
"
```

Replace `YOUR_HOST` and `YOUR_TOKEN` with your actual values from the gateway logs.

## Tunnel options

| Option | Extra account? | Stability | Setup |
|--------|---------------|-----------|-------|
| **Tailscale Funnel** (recommended) | No | Stable URL, survives reboots | `tailscale funnel --bg 18789` |
| **Cloudflare Tunnel** | Free account | Stable URL | Install `cloudflared` |
| `none` | N/A | LAN only (home WiFi) | Nothing |

Both tunnels have been tested and confirmed working on real R1 hardware.

## Security

- TLS encryption via the tunnel (wss://) — all traffic encrypted end-to-end
- Random 32-char hex token — required for every connection
- Device ID validation — only your specific R1 is accepted
- Token rotates each session (new QR code = new token)
- No ports raw-exposed to the internet

## Shared memory with other platforms

Because this is a standard Hermes platform adapter, it shares the same Hermes brain as your Telegram, Discord, and other platforms:

- Tell Hermes something on Telegram -> your R1 already knows it
- Set a cron job on your R1 -> can deliver to Telegram
- Same skills and tools available everywhere
- Run Telegram and R1 simultaneously — use whichever device is in your hand

## PR to NousResearch/hermes-agent

This is developed here first (tested on real R1 hardware), then submitted as a PR to the main hermes-agent repo. See [docs/platforms/rabbit_r1.md](docs/platforms/rabbit_r1.md) for the full list of 16 integration points.

## Project structure

```
gateway/platforms/rabbit_r1.py   -- main adapter (~600 lines)
test_server.py                   -- standalone test server (no Hermes needed)
tests/gateway/test_rabbit_r1.py  -- unit tests
docs/platforms/rabbit_r1.md      -- integration guide for the PR
```
