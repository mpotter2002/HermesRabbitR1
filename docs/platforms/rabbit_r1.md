# Rabbit R1 Platform Adapter — Integration Guide

This document lists every file in `NousResearch/hermes-agent` that needs changes
to fully integrate the Rabbit R1 platform adapter.

## Quick overview

The adapter (`gateway/platforms/rabbit_r1.py`) runs a WebSocket server that speaks
the clawdbot-gateway protocol. A tunnel (Tailscale Funnel or Cloudflare Tunnel)
makes it reachable from anywhere, not just the home LAN.

## Dependencies

```
websockets>=12.0
qrcode>=7.0        # optional, for terminal QR code display
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBIT_R1_TOKEN` | auto-generated | 32-char hex auth token |
| `RABBIT_R1_PORT` | `18789` | Local WebSocket server port |
| `RABBIT_R1_TUNNEL` | `tailscale` | Tunnel mode: `tailscale`, `cloudflare`, or `none` |

## Integration points (16 files)

### 1. Core adapter — `gateway/platforms/rabbit_r1.py` (NEW)

Drop in the full adapter file. Contains `RabbitR1Adapter` and
`check_rabbit_r1_requirements()`.

### 2. Platform enum — `gateway/config.py`

Add to the `Platform` enum:

```python
class Platform(Enum):
    # ... existing platforms ...
    RABBIT_R1 = "rabbit_r1"
```

Add to `_apply_env_overrides()`:

```python
if os.getenv("RABBIT_R1_TOKEN"):
    config.platforms.setdefault("rabbit_r1", {})
    config.platforms["rabbit_r1"]["token"] = os.getenv("RABBIT_R1_TOKEN")
```

### 3. Adapter factory — `gateway/run.py` `_create_adapter()`

```python
elif platform == Platform.RABBIT_R1:
    from gateway.platforms.rabbit_r1 import RabbitR1Adapter, check_rabbit_r1_requirements
    if not check_rabbit_r1_requirements():
        return None
    return RabbitR1Adapter(platform_config)
```

### 4. Authorization — `gateway/run.py` `_is_user_authorized()`

Add to `platform_env_map`:

```python
Platform.RABBIT_R1: "RABBIT_R1_ALLOWED_USERS",
```

Add to `platform_allow_all_map`:

```python
Platform.RABBIT_R1: "RABBIT_R1_ALLOW_ALL",
```

### 5. Session source — `gateway/session.py`

No changes needed. The R1 adapter uses standard `SessionSource` fields.

### 6. System prompt hints — `agent/prompt_builder.py`

Add to `PLATFORM_HINTS`:

```python
Platform.RABBIT_R1: (
    "The user is on a Rabbit R1 device with a small 2.88-inch touchscreen. "
    "Keep responses concise and conversational — no markdown, no long lists. "
    "The device has voice output so short spoken-style answers work best. "
    "Aim for 1-3 sentences unless the user asks for detail. "
    "If the user asks for the R1 QR code or needs to reconnect their R1, "
    "the pairing QR code PNG is saved at ~/.hermes/rabbit_r1_qr.png — "
    "send or share that file. The R1 auto-reconnects using the same QR code "
    "as long as the token has not changed."
),
```

### 7. Toolset — `toolsets.py`

Add a named toolset:

```python
"hermes-rabbit-r1": [
    "hermes-core",
    "hermes-memory",
    "hermes-cron",
],
```

And include it in `hermes-gateway`:

```python
"hermes-gateway": [
    # ... existing platforms ...
    "hermes-rabbit-r1",
],
```

### 8. Cron delivery — `cron/scheduler.py` `_deliver_result()`

Add to `platform_map`:

```python
Platform.RABBIT_R1: adapter.send,
```

### 9. Send message tool — `tools/send_message_tool.py`

Add to `platform_map`:

```python
Platform.RABBIT_R1: _send_rabbit_r1,
```

Add standalone send function:

```python
async def _send_rabbit_r1(chat_id: str, text: str, **kwargs) -> SendResult:
    adapter = _get_adapter(Platform.RABBIT_R1)
    if adapter is None:
        return SendResult(success=False, error="Rabbit R1 adapter not connected")
    return await adapter.send(chat_id, text)
```

### 10. Cronjob tool schema — `tools/cronjob_tools.py`

Update the `deliver` parameter description to include `rabbit_r1`:

```python
"deliver": {
    "description": "Platform to deliver to: telegram, discord, ..., rabbit_r1",
}
```

### 11. Channel directory — `gateway/channel_directory.py`

Add to the session-based discovery list so Hermes can route cron jobs to the R1:

```python
Platform.RABBIT_R1: "rabbit_r1",
```

### 12. Status display — `hermes_cli/status.py`

Add to the platforms display dict:

```python
Platform.RABBIT_R1: "Rabbit R1",
```

### 13. Gateway setup wizard — `hermes_cli/gateway.py`

Add to `_PLATFORMS` list:

```python
("rabbit_r1", "Rabbit R1 (hardware device via WebSocket)"),
```

### 14. PII redaction — `agent/redact.py`

Add device ID redaction pattern:

```python
# Rabbit R1 device IDs (64-char hex)
(r'\b[a-f0-9]{64}\b', '[R1_DEVICE_ID]'),
```

### 15. Documentation

- Update `README.md` — add Rabbit R1 to supported platforms list
- Create `docs/messaging/rabbit_r1.md` — setup and usage guide
- Update env var reference with the three new variables

### 16. Tests — `tests/gateway/test_rabbit_r1.py`

Required test cases:
- `Platform.RABBIT_R1` exists in enum
- Config loading with env overrides
- `RabbitR1Adapter.__init__()` succeeds
- Token generation (auto vs explicit)
- QR payload format validation
- `_handle_connect()` accepts valid token, rejects invalid
- `send()` delivers correct protocol payload
- `get_chat_info()` returns expected structure
- `format_message()` strips markdown correctly
- Session source round-trip
- Authorization env var mapping
- Send message tool routing

## Tunnel setup for users

### Tailscale Funnel (recommended, zero extra accounts)

```bash
# One-time setup
sudo tailscale set --operator=$USER
tailscale funnel 18789
```

### Cloudflare Tunnel (alternative, free account required)

```bash
# Install cloudflared
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
chmod +x cloudflared

# Create a named tunnel (permanent URL)
cloudflared tunnel login
cloudflared tunnel create hermes-r1
cloudflared tunnel route dns hermes-r1 r1.yourdomain.com
cloudflared tunnel run --url http://localhost:18789 hermes-r1
```
