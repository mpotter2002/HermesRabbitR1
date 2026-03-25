"""
Rabbit R1 platform adapter for Hermes.

Speaks the OpenClaw/clawdbot-gateway WebSocket protocol so the Rabbit R1
device can talk to Hermes AI (full memory, skills, crons) from anywhere —
not just home WiFi.

Unlike the official OpenClaw setup (LAN-only), this adapter runs on a VM
with a tunnel (Tailscale Funnel or Cloudflare Tunnel) so the R1 works from
any network: home, cellular, travelling.

Architecture:
    R1 (anywhere with internet)
        ↓  wss://yourname.ts.net  (TLS via Tailscale Funnel)
    VM / always-on server
        ↓
    rabbit_r1.py  (this file — BasePlatformAdapter)
        ↓
    Hermes gateway → Claude / local model (full memory, skills, crons)

Protocol reference:
    QR payload:  {"type":"clawdbot-gateway","version":1,"ips":[...],"port":18789,"token":"<hex32>","protocol":"ws"}
    Handshake:   connect.challenge → connect → node.pair.approved → connect.ok
    Chat:        chat.send (R1→server) / chat event (server→R1)

Tunnel options:
    RABBIT_R1_TUNNEL=tailscale   — Tailscale Funnel (default, no extra account)
    RABBIT_R1_TUNNEL=cloudflare  — Cloudflare Tunnel (free account, stable URL)
    RABBIT_R1_TUNNEL=none        — LAN only (home network)
"""

import asyncio
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import time
import uuid
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    WebSocketServerProtocol = Any

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)


# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

def check_rabbit_r1_requirements() -> bool:
    """Return True if all required dependencies are available."""
    if not WEBSOCKETS_AVAILABLE:
        logger.warning("Rabbit R1: 'websockets' package not installed. Run: pip install websockets")
        return False
    return True


# ---------------------------------------------------------------------------
# Tunnel helpers
# ---------------------------------------------------------------------------

def _get_tailscale_funnel_url(port: int) -> Optional[str]:
    """
    Start a Tailscale Funnel on *port* and return the public wss:// URL.
    Returns None if Tailscale is not available or the command fails.
    """
    try:
        # Enable funnel for the port (idempotent — safe to call multiple times)
        subprocess.run(
            ["tailscale", "funnel", str(port)],
            check=True,
            capture_output=True,
            timeout=15,
        )
        # Get the stable public hostname
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = json.loads(result.stdout)
        dns_name = status["Self"]["DNSName"].rstrip(".")
        return f"wss://{dns_name}"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            KeyError, json.JSONDecodeError, FileNotFoundError):
        return None


def _get_cloudflare_tunnel_url(port: int) -> Optional[str]:
    """
    Start a Cloudflare Quick Tunnel (trycloudflare.com) and return the wss:// URL.
    This is a temporary URL — use Tailscale or a named Cloudflare tunnel for stability.
    """
    try:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Parse the tunnel URL from cloudflared's stderr output
        import re
        for _ in range(30):
            line = proc.stderr.readline()
            match = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
            if match:
                https_url = match.group(0)
                return https_url.replace("https://", "wss://")
        return None
    except (FileNotFoundError, Exception):
        return None


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

class RabbitR1Adapter(BasePlatformAdapter):
    """
    Rabbit R1 platform adapter.

    Runs a WebSocket server that speaks the clawdbot-gateway protocol.
    On startup, optionally opens a Tailscale Funnel or Cloudflare Tunnel
    so the R1 can reach it from anywhere, not just home WiFi.

    Config env vars:
        RABBIT_R1_TOKEN   — hex32 auth token (auto-generated if not set)
        RABBIT_R1_PORT    — WebSocket server port (default: 18789)
        RABBIT_R1_TUNNEL  — "tailscale" | "cloudflare" | "none" (default: "tailscale")
    """

    # R1 has no hard message length limit but keep responses readable on the small screen
    MAX_MESSAGE_LENGTH = 2000

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.RABBIT_R1)

        self._port: int = int(os.getenv("RABBIT_R1_PORT", "18789"))
        self._tunnel_mode: str = os.getenv("RABBIT_R1_TUNNEL", "tailscale").lower()

        # Token: from env, from config, or auto-generate
        token = os.getenv("RABBIT_R1_TOKEN") or getattr(config, "token", None)
        self._token: str = token or secrets.token_hex(32)

        # Runtime state
        self._server = None
        self._server_task: Optional[asyncio.Task] = None
        self._public_url: Optional[str] = None

        # device_id → websocket mapping for connected R1 devices
        self._clients: Dict[str, WebSocketServerProtocol] = {}

    # ------------------------------------------------------------------
    # BasePlatformAdapter — required methods
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Start the WebSocket server and (optionally) open the tunnel."""
        if not check_rabbit_r1_requirements():
            return False

        # Start the tunnel first so we know the public URL for the QR code
        self._public_url = await self._start_tunnel()

        # Start the WebSocket server
        try:
            self._server = await websockets.serve(
                self._handle_connection,
                "0.0.0.0",
                self._port,
            )
            logger.info(f"Rabbit R1: WebSocket server listening on port {self._port}")
        except OSError as e:
            logger.error(f"Rabbit R1: Failed to start WebSocket server: {e}")
            return False

        self._mark_connected()

        # Print the QR code and pairing info to the console
        await self._print_pairing_info()

        return True

    async def disconnect(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._clients.clear()
        self._mark_disconnected()
        logger.info("Rabbit R1: disconnected")

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a text reply back to the R1 device identified by *chat_id*."""
        ws = self._clients.get(chat_id)
        if not ws:
            return SendResult(success=False, error=f"Device {chat_id!r} not connected")

        run_id = str(uuid.uuid4())
        payload = {
            "type": "event",
            "event": "chat",
            "payload": {
                "runId": run_id,
                "sessionKey": "main",
                "seq": 1,
                "state": "final",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": content}],
                    "timestamp": _now_ms(),
                    "stopReason": "stop",
                    "usage": {"input": 0, "output": 0, "totalTokens": 0},
                },
            },
        }
        try:
            await ws.send(json.dumps(payload))
            return SendResult(success=True, message_id=run_id)
        except Exception as e:
            logger.warning(f"Rabbit R1: send failed for {chat_id}: {e}")
            return SendResult(success=False, error=str(e))

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Return metadata about the chat (device) identified by *chat_id*."""
        connected = chat_id in self._clients
        return {
            "name": "Rabbit R1",
            "type": "dm",
            "chat_id": chat_id,
            "connected": connected,
        }

    def format_message(self, content: str) -> str:
        """
        Strip markdown formatting for the R1's small screen.
        The R1 renders plain text — bold/italic/links just add noise.
        """
        # Remove markdown bold/italic
        content = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', content)
        content = re.sub(r'_{1,3}(.+?)_{1,3}', r'\1', content)
        # Remove markdown links [text](url) → text (url)
        content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', content)
        # Remove markdown headers
        content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)
        # Remove code block markers
        content = re.sub(r'```\w*\n?', '', content)
        content = re.sub(r'`([^`]+)`', r'\1', content)
        return content.strip()

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """Send a 'thinking' state to the R1 — shows a loading indicator."""
        ws = self._clients.get(chat_id)
        if not ws:
            return
        payload = {
            "type": "event",
            "event": "chat",
            "payload": {
                "runId": str(uuid.uuid4()),
                "sessionKey": "main",
                "seq": 0,
                "state": "thinking",
                "message": {
                    "role": "assistant",
                    "content": [],
                    "timestamp": _now_ms(),
                },
            },
        }
        try:
            await ws.send(json.dumps(payload))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # WebSocket connection handling
    # ------------------------------------------------------------------

    async def _handle_connection(self, ws: WebSocketServerProtocol, path: str) -> None:
        """Handle a new WebSocket connection from an R1 device."""
        remote = f"{ws.remote_address[0]}:{ws.remote_address[1]}"
        logger.debug(f"Rabbit R1: new connection from {remote}")

        # Step 1 — send the challenge immediately
        nonce = str(uuid.uuid4())
        await self._send(ws, {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": nonce, "ts": _now_ms()},
        })

        device_id: Optional[str] = None
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"Rabbit R1: invalid JSON from {remote}")
                    continue

                method = msg.get("method") or msg.get("type", "")

                # ----------------------------------------------------------
                # Pairing / auth handshake
                # ----------------------------------------------------------
                if method in ("connect", "gateway.connect"):
                    device_id = await self._handle_connect(ws, msg, remote)
                    if device_id is None:
                        break  # auth failed — connection closed inside handler
                    continue

                # Drop everything until the device is authenticated
                if device_id is None:
                    logger.warning(f"Rabbit R1: unauthenticated message from {remote}, ignoring")
                    continue

                # ----------------------------------------------------------
                # Chat
                # ----------------------------------------------------------
                if method == "chat.send":
                    await self._handle_chat_send(ws, msg, device_id)

                # ----------------------------------------------------------
                # Heartbeat — just acknowledge it
                # ----------------------------------------------------------
                elif method == "system-presence":
                    await self._send(ws, {
                        "type": "res",
                        "id": msg.get("id"),
                        "ok": True,
                        "payload": {"ts": _now_ms()},
                    })

                # ----------------------------------------------------------
                # Abort an in-progress generation
                # ----------------------------------------------------------
                elif method == "chat.abort":
                    await self.cancel_background_tasks(device_id)
                    await self._send(ws, {"type": "res", "id": msg.get("id"), "ok": True})

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if device_id and device_id in self._clients:
                del self._clients[device_id]
                logger.info(f"Rabbit R1: device disconnected: {device_id}")

    async def _handle_connect(
        self,
        ws: WebSocketServerProtocol,
        msg: dict,
        remote: str,
    ) -> Optional[str]:
        """
        Validate the token and complete the pairing handshake.
        Returns the device_id on success, None on failure.
        """
        msg_id = msg.get("id")
        params = msg.get("params", {})

        # Extract token — R1 sends it at params.auth.token
        client_token = (
            params.get("auth", {}).get("token")
            or params.get("authToken")
            or msg.get("token")
        )
        # Extract device ID
        device_id = (
            params.get("device", {}).get("id")
            or params.get("deviceId")
            or f"r1-{remote}"
        )

        if client_token != self._token:
            logger.warning(f"Rabbit R1: auth failed from {remote} (bad token)")
            await self._send(ws, {
                "type": "res",
                "id": msg_id,
                "ok": False,
                "error": {"code": 401, "message": "Invalid token"},
            })
            await ws.close()
            return None

        # Auth passed — register the device
        self._clients[device_id] = ws
        logger.info(f"Rabbit R1: device paired: {device_id} from {remote}")

        await self._send(ws, {
            "type": "event",
            "event": "node.pair.approved",
            "payload": {"deviceId": device_id, "token": str(uuid.uuid4())},
        })
        await self._send(ws, {
            "type": "res",
            "id": msg_id,
            "ok": True,
            "payload": {"status": "paired", "ts": _now_ms()},
        })
        await self._send(ws, {
            "type": "event",
            "event": "connect.ok",
            "payload": {"deviceId": device_id, "ts": _now_ms()},
        })

        return device_id

    async def _handle_chat_send(
        self,
        ws: WebSocketServerProtocol,
        msg: dict,
        device_id: str,
    ) -> None:
        """Route an incoming chat.send message into the Hermes message pipeline."""
        params = msg.get("params", {})
        text = params.get("message", "").strip()

        if not text:
            return

        # Acknowledge the request immediately so the R1 doesn't time out
        await self._send(ws, {"type": "res", "id": msg.get("id"), "ok": True})

        source = self.build_source(
            chat_id=device_id,
            chat_name="Rabbit R1",
            chat_type="dm",
            user_id=device_id,
            user_name="R1 User",
        )

        event = MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=source,
            message_id=params.get("idempotencyKey") or str(uuid.uuid4()),
        )

        await self.handle_message(event)

    # ------------------------------------------------------------------
    # Tunnel helpers
    # ------------------------------------------------------------------

    async def _start_tunnel(self) -> Optional[str]:
        """Start the configured tunnel and return the public wss:// URL."""
        # Allow hardcoding the public URL via env var — useful when running
        # as a systemd service where subprocess tunnel detection may fail.
        explicit_url = os.getenv("RABBIT_R1_PUBLIC_URL")
        if explicit_url:
            logger.info(f"Rabbit R1: using explicit public URL: {explicit_url}")
            return explicit_url

        if self._tunnel_mode == "none":
            return None

        loop = asyncio.get_event_loop()

        if self._tunnel_mode == "tailscale":
            url = await loop.run_in_executor(
                None, _get_tailscale_funnel_url, self._port
            )
            if url:
                logger.info(f"Rabbit R1: Tailscale Funnel active at {url}")
            else:
                logger.warning(
                    "Rabbit R1: Tailscale Funnel unavailable — "
                    "R1 will only work on local network. "
                    "Run 'tailscale funnel 18789' manually or set RABBIT_R1_TUNNEL=none."
                )
            return url

        if self._tunnel_mode == "cloudflare":
            url = await loop.run_in_executor(
                None, _get_cloudflare_tunnel_url, self._port
            )
            if url:
                logger.info(f"Rabbit R1: Cloudflare Tunnel active at {url}")
            else:
                logger.warning("Rabbit R1: Cloudflare Tunnel unavailable")
            return url

        logger.warning(f"Rabbit R1: Unknown tunnel mode {self._tunnel_mode!r}, skipping tunnel")
        return None

    # ------------------------------------------------------------------
    # QR code / pairing info
    # ------------------------------------------------------------------

    async def _print_pairing_info(self) -> None:
        """Print pairing instructions and QR code to the console."""
        # Build the QR payload
        if self._public_url:
            # Strip wss:// scheme — the payload uses host + port separately
            host = self._public_url.replace("wss://", "").replace("ws://", "")
            port = 443  # Tailscale/Cloudflare terminate TLS on 443
        else:
            host = _get_lan_ip()
            port = self._port

        qr_data = json.dumps({
            "type": "clawdbot-gateway",
            "version": 1,
            "ips": [host],
            "port": port,
            "token": self._token,
            "protocol": "wss" if self._public_url else "ws",
        })

        print("\n" + "=" * 60)
        print("  Rabbit R1 — Hermes Gateway")
        print("=" * 60)
        if self._public_url:
            print(f"  Public URL : {self._public_url}")
            print(f"  Works from : anywhere (home, cellular, travelling)")
        else:
            print(f"  Local URL  : ws://{host}:{port}")
            print(f"  Works from : home network only")
        print(f"  Token      : {self._token}")
        print()
        print("  Scan the QR code below with your Rabbit R1:")
        print()

        if QRCODE_AVAILABLE:
            qr = qrcode.QRCode(border=1)
            qr.add_data(qr_data)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        else:
            print(f"  QR payload : {qr_data}")
            print()
            print("  (Install 'qrcode' for a visual QR code: pip install qrcode)")

        print("=" * 60 + "\n")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    async def _send(ws: WebSocketServerProtocol, data: dict) -> None:
        """Send a JSON message to a WebSocket client, ignoring closed connections."""
        try:
            await ws.send(json.dumps(data))
        except websockets.exceptions.ConnectionClosed:
            pass


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    """Current time in milliseconds."""
    return int(time.time() * 1000)


def _get_lan_ip() -> str:
    """Best-effort LAN IP detection for the QR code fallback."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
