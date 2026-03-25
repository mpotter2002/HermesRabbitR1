"""
Standalone test server for the Rabbit R1 protocol.

Run this BEFORE wiring into Hermes to confirm the R1 can pair and
send/receive messages. No Hermes install needed.

Usage:
    pip install websockets qrcode
    python test_server.py

Then scan the QR code with your R1 and say something.
"""

import asyncio
import json
import secrets
import uuid
import time
import os

try:
    import websockets
except ImportError:
    print("Missing dependency: pip install websockets")
    raise

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

TOKEN = os.getenv("RABBIT_R1_TOKEN") or secrets.token_hex(32)
PORT = int(os.getenv("RABBIT_R1_PORT", "18789"))

clients = {}  # device_id -> websocket


def now_ms():
    return int(time.time() * 1000)


async def send(ws, data):
    try:
        await ws.send(json.dumps(data))
        print(f"  OUT → {data.get('event') or data.get('type')}")
    except Exception:
        pass


def print_qr(host, port, token, protocol="ws"):
    payload = json.dumps({
        "type": "clawdbot-gateway",
        "version": 1,
        "ips": [host],
        "port": port,
        "token": token,
        "protocol": protocol,
    })

    print("\n" + "=" * 60)
    print("  Rabbit R1 — Test Server")
    print("=" * 60)
    print(f"  Host  : {host}")
    print(f"  Port  : {port}")
    print(f"  Token : {token}")
    print()
    print("  Scan with your R1:")
    print()

    if HAS_QRCODE:
        qr = qrcode.QRCode(border=1)
        qr.add_data(payload)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    else:
        print(f"  Payload: {payload}")
        print("  (pip install qrcode for visual QR)")

    print("=" * 60 + "\n")


def get_lan_ip():
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


async def handle_connection(ws, path=""):
    remote = f"{ws.remote_address[0]}:{ws.remote_address[1]}"
    print(f"\n[+] New connection from {remote}")

    # Send challenge
    await send(ws, {
        "type": "event",
        "event": "connect.challenge",
        "payload": {"nonce": str(uuid.uuid4()), "ts": now_ms()},
    })

    device_id = None
    try:
        async for raw in ws:
            msg = json.loads(raw)
            method = msg.get("method") or msg.get("type", "")
            print(f"  IN  ← {method}")

            # Pairing
            if method in ("connect", "gateway.connect"):
                params = msg.get("params", {})
                client_token = params.get("auth", {}).get("token") or params.get("authToken")
                device_id = params.get("device", {}).get("id") or f"r1-{remote}"

                if client_token != TOKEN:
                    print(f"  [!] Auth FAILED — expected {TOKEN}, got {client_token}")
                    await send(ws, {"type": "res", "id": msg.get("id"), "ok": False,
                                    "error": {"code": 401, "message": "Invalid token"}})
                    await ws.close()
                    return

                clients[device_id] = ws
                print(f"  [✓] Device paired: {device_id}")

                await send(ws, {"type": "event", "event": "node.pair.approved",
                                "payload": {"deviceId": device_id, "token": str(uuid.uuid4())}})
                await send(ws, {"type": "res", "id": msg.get("id"), "ok": True,
                                "payload": {"status": "paired", "ts": now_ms()}})
                await send(ws, {"type": "event", "event": "connect.ok",
                                "payload": {"deviceId": device_id, "ts": now_ms()}})
                continue

            if device_id is None:
                continue

            # Chat
            if method == "chat.send":
                text = msg.get("params", {}).get("message", "")
                print(f"\n  💬 R1 said: {text!r}\n")

                # Echo back with a test reply
                reply = f"Test server received: {text!r}. Hermes would answer here."
                await send(ws, {
                    "type": "event",
                    "event": "chat",
                    "payload": {
                        "runId": str(uuid.uuid4()),
                        "sessionKey": "main",
                        "seq": 1,
                        "state": "final",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": reply}],
                            "timestamp": now_ms(),
                            "stopReason": "stop",
                            "usage": {"input": 0, "output": 0, "totalTokens": 0},
                        },
                    },
                })
                await send(ws, {"type": "res", "id": msg.get("id"), "ok": True})

            elif method == "system-presence":
                await send(ws, {"type": "res", "id": msg.get("id"), "ok": True,
                                "payload": {"ts": now_ms()}})

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if device_id:
            clients.pop(device_id, None)
            print(f"\n[-] Device disconnected: {device_id}")


async def main():
    ip = get_lan_ip()
    print_qr(ip, PORT, TOKEN)

    print(f"Waiting for R1 connection on ws://{ip}:{PORT} ...")
    print("(Ctrl+C to stop)\n")

    async with websockets.serve(handle_connection, "0.0.0.0", PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
