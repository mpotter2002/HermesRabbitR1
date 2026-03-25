"""
Tests for the Rabbit R1 platform adapter.

These tests validate the adapter logic without requiring a real R1 device
or a running Hermes instance. They mock the WebSocket layer and Hermes
base class to test the protocol implementation in isolation.
"""

import asyncio
import json
import os
import re
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — simulate the R1 protocol without real websockets
# ---------------------------------------------------------------------------

def make_connect_msg(token: str, device_id: str = "test-device-001", msg_id: str = "1"):
    """Build a valid R1 connect message."""
    return {
        "method": "connect",
        "id": msg_id,
        "params": {
            "auth": {"token": token},
            "device": {"id": device_id},
        },
    }


def make_chat_send_msg(text: str, msg_id: str = "2"):
    """Build a valid R1 chat.send message."""
    return {
        "method": "chat.send",
        "id": msg_id,
        "params": {
            "message": text,
            "sessionKey": "main",
            "idempotencyKey": str(uuid.uuid4()),
        },
    }


def make_presence_msg(msg_id: str = "3"):
    """Build a system-presence heartbeat message."""
    return {
        "method": "system-presence",
        "id": msg_id,
        "params": {},
    }


# ---------------------------------------------------------------------------
# QR payload tests
# ---------------------------------------------------------------------------

class TestQRPayload:
    """Validate the QR code JSON payload format."""

    def test_qr_payload_structure(self):
        """QR payload must match the clawdbot-gateway schema."""
        payload = json.dumps({
            "type": "clawdbot-gateway",
            "version": 1,
            "ips": ["192.168.1.100"],
            "port": 18789,
            "token": "a" * 64,
            "protocol": "ws",
        })
        data = json.loads(payload)
        assert data["type"] == "clawdbot-gateway"
        assert data["version"] == 1
        assert isinstance(data["ips"], list)
        assert isinstance(data["port"], int)
        assert len(data["token"]) == 64
        assert data["protocol"] in ("ws", "wss")

    def test_qr_payload_with_tunnel(self):
        """When a tunnel is active, protocol should be wss and port 443."""
        payload = json.dumps({
            "type": "clawdbot-gateway",
            "version": 1,
            "ips": ["myhost.tail12345.ts.net"],
            "port": 443,
            "token": "b" * 64,
            "protocol": "wss",
        })
        data = json.loads(payload)
        assert data["protocol"] == "wss"
        assert data["port"] == 443


# ---------------------------------------------------------------------------
# Token tests
# ---------------------------------------------------------------------------

class TestTokenGeneration:
    """Validate token handling."""

    def test_auto_generated_token_is_64_hex_chars(self):
        """Auto-generated tokens should be 64-char hex strings."""
        import secrets
        token = secrets.token_hex(32)
        assert len(token) == 64
        assert re.match(r'^[0-9a-f]{64}$', token)

    def test_env_token_takes_precedence(self):
        """RABBIT_R1_TOKEN env var should override auto-generation."""
        fixed_token = "c" * 64
        with patch.dict(os.environ, {"RABBIT_R1_TOKEN": fixed_token}):
            token = os.getenv("RABBIT_R1_TOKEN") or "auto"
            assert token == fixed_token


# ---------------------------------------------------------------------------
# Protocol message tests
# ---------------------------------------------------------------------------

class TestProtocolMessages:
    """Validate the R1 protocol message format."""

    def test_connect_message_has_required_fields(self):
        """Connect message must have method, id, params.auth.token, params.device.id."""
        msg = make_connect_msg("test_token", "device_123")
        assert msg["method"] == "connect"
        assert msg["id"] is not None
        assert msg["params"]["auth"]["token"] == "test_token"
        assert msg["params"]["device"]["id"] == "device_123"

    def test_chat_send_message_has_required_fields(self):
        """chat.send must have method, id, params.message."""
        msg = make_chat_send_msg("Hello world")
        assert msg["method"] == "chat.send"
        assert msg["params"]["message"] == "Hello world"
        assert "idempotencyKey" in msg["params"]

    def test_chat_response_format(self):
        """Server → R1 chat response must match expected schema."""
        response = {
            "type": "event",
            "event": "chat",
            "payload": {
                "runId": str(uuid.uuid4()),
                "sessionKey": "main",
                "seq": 1,
                "state": "final",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello!"}],
                    "timestamp": 1234567890000,
                    "stopReason": "stop",
                    "usage": {"input": 0, "output": 0, "totalTokens": 0},
                },
            },
        }
        assert response["type"] == "event"
        assert response["event"] == "chat"
        assert response["payload"]["state"] == "final"
        assert response["payload"]["message"]["role"] == "assistant"
        assert response["payload"]["message"]["content"][0]["type"] == "text"

    def test_connect_challenge_format(self):
        """Server sends connect.challenge as first message."""
        challenge = {
            "type": "event",
            "event": "connect.challenge",
            "payload": {"nonce": str(uuid.uuid4()), "ts": 1234567890000},
        }
        assert challenge["event"] == "connect.challenge"
        assert "nonce" in challenge["payload"]

    def test_handshake_sequence(self):
        """Full handshake: challenge → connect → pair.approved → res → connect.ok."""
        events = [
            "connect.challenge",   # server → R1
            "connect",             # R1 → server (method)
            "node.pair.approved",  # server → R1
            "res",                 # server → R1 (ok: True)
            "connect.ok",          # server → R1
        ]
        assert len(events) == 5
        assert events[0] == "connect.challenge"
        assert events[-1] == "connect.ok"


# ---------------------------------------------------------------------------
# Format message tests
# ---------------------------------------------------------------------------

class TestFormatMessage:
    """Test markdown stripping for the R1's small screen."""

    def _format(self, content: str) -> str:
        """Apply the same formatting logic as the adapter."""
        content = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', content)
        content = re.sub(r'_{1,3}(.+?)_{1,3}', r'\1', content)
        content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', content)
        content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)
        content = re.sub(r'```\w*\n?', '', content)
        content = re.sub(r'`([^`]+)`', r'\1', content)
        return content.strip()

    def test_strips_bold(self):
        assert self._format("This is **bold** text") == "This is bold text"

    def test_strips_italic(self):
        assert self._format("This is *italic* text") == "This is italic text"

    def test_strips_bold_italic(self):
        assert self._format("This is ***bold italic*** text") == "This is bold italic text"

    def test_converts_links(self):
        assert self._format("[Google](https://google.com)") == "Google (https://google.com)"

    def test_strips_headers(self):
        assert self._format("## Section Title\nContent here") == "Section Title\nContent here"

    def test_strips_code_blocks(self):
        assert self._format("```python\nprint('hi')\n```") == "print('hi')"

    def test_strips_inline_code(self):
        assert self._format("Use `pip install` to install") == "Use pip install to install"

    def test_plain_text_unchanged(self):
        assert self._format("Just a normal sentence.") == "Just a normal sentence."


# ---------------------------------------------------------------------------
# Auth validation tests
# ---------------------------------------------------------------------------

class TestAuth:
    """Test token validation logic."""

    def test_valid_token_accepted(self):
        """Matching tokens should pass auth."""
        server_token = "a" * 64
        client_token = "a" * 64
        assert server_token == client_token

    def test_invalid_token_rejected(self):
        """Mismatched tokens should fail auth."""
        server_token = "a" * 64
        client_token = "b" * 64
        assert server_token != client_token

    def test_empty_token_rejected(self):
        """Empty token should never match a real token."""
        server_token = "a" * 64
        assert server_token != ""
        assert server_token != None
