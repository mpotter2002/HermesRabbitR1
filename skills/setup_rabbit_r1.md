# Setup Rabbit R1

Connect a Rabbit R1 device to this Hermes agent so it can be used as a platform alongside Telegram, Discord, etc. The R1 will share the same memory, skills, and crons as all other platforms.

## What to do

1. **Clone the adapter repo:**
   ```
   cd ~ && git clone https://github.com/mpotter2002/HermesRabbitR1.git
   ```

2. **Read the integration guide carefully:**
   ```
   ~/HermesRabbitR1/docs/platforms/rabbit_r1.md
   ```
   This lists all 16 files that need changes. Follow every integration point.

3. **Copy the adapter file:**
   ```
   cp ~/HermesRabbitR1/gateway/platforms/rabbit_r1.py /path/to/hermes-agent/gateway/platforms/
   ```
   Find the actual hermes-agent install path first (check ~/.hermes/hermes-agent/ or similar).

4. **Apply all 16 integration points** from the guide — Platform enum, adapter factory, authorization maps, prompt hints, toolsets, cron delivery, send message tool, cronjob tools, channel directory, status display, gateway wizard, and PII redaction.

5. **Install dependencies** in the Hermes venv:
   ```
   /path/to/hermes-agent/venv/bin/python -m pip install websockets qrcode
   ```

6. **Set up the tunnel** (so the R1 works from anywhere, not just home WiFi):
   - Check if Tailscale is installed: `which tailscale`
   - **If Tailscale is installed:**
     ```
     sudo tailscale set --operator=$USER
     tailscale funnel --bg 18789
     tailscale funnel status
     ```
   - **If Tailscale is NOT installed** (Linux/VM):
     ```
     curl -fsSL https://tailscale.com/install.sh | sh
     sudo tailscale up
     sudo tailscale set --operator=$USER
     tailscale funnel --bg 18789
     tailscale funnel status
     ```
     After `tailscale up` the user may need to visit a URL in their browser to authenticate — show them the URL and ask them to confirm when done.
   - **If Tailscale is NOT installed** (Mac):
     Tell the user to install Tailscale from tailscale.com/download, sign in, then come back. Once installed, run `tailscale funnel --bg 18789`.
   - **Cloudflare Tunnel alternative** (if user prefers or Tailscale fails):
     ```
     cloudflared tunnel --url http://localhost:18789
     ```
     Parse the trycloudflare.com URL from the output and use that as the public URL.

7. **Configure environment variables** — add to ~/.hermes/.env:
   ```
   RABBIT_R1_TOKEN=<generate with: openssl rand -hex 32>
   RABBIT_R1_TUNNEL=tailscale
   RABBIT_R1_PUBLIC_URL=wss://<tailscale-hostname>
   ```
   Get the hostname from `tailscale status --json | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))"`

8. **Verify all changed files pass syntax check:**
   ```
   find /path/to/hermes-agent -name "*.py" -newer /path/to/hermes-agent/gateway/platforms/rabbit_r1.py -exec python -m py_compile {} \;
   ```

9. **Restart the gateway:**
   ```
   hermes gateway restart
   ```

10. **Send the QR code** to the user. The QR code PNG is saved at `~/.hermes/rabbit_r1_qr.png`. Send this image to the user so they can scan it with their R1.

## Important notes

- Do NOT restart Hermes until all 16 integration points are applied and syntax-checked
- The tunnel (step 6) may require sudo — if you don't have sudo access, ask the user to run the sudo command manually
- If Tailscale Funnel is not available, Cloudflare Tunnel works too: `cloudflared tunnel --url http://localhost:18789`
- The adapter supports websockets 15.x — make sure the handler's path parameter has a default value
