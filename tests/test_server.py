"""Protocol tests for the dummy server (no Home Assistant needed)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import ssl
import sys
import types

import pytest

PKG_DIR = Path(__file__).parent.parent / "custom_components" / "gree_dummy_server"

# Load const.py and server.py as a package without running __init__.py (which imports HA).
_pkg = types.ModuleType("gds")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules["gds"] = _pkg
for _name in ("const", "server"):
    _spec = importlib.util.spec_from_file_location(f"gds.{_name}", PKG_DIR / f"{_name}.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[f"gds.{_name}"] = _mod
    _spec.loader.exec_module(_mod)

const = sys.modules["gds.const"]
server = sys.modules["gds.server"]

MAC = "c039378a04e0"


def _config(mode: str, ports: tuple[int, int, int]) -> dict:
    return {
        const.CONF_EXTERNAL_IP: "192.168.1.10",
        const.CONF_DOMAIN_NAME: "eu.dis.gree.com",
        const.CONF_TCP_PORT: ports[0],
        const.CONF_TLS_PORT: ports[1],
        const.CONF_MQTT_MODE: mode,
        const.CONF_MQTT_PORT: ports[2],
        const.CONF_MQTT_HOLD: 0,
    }


def _free_ports(n: int) -> tuple[int, ...]:
    import socket

    socks = [socket.socket() for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = tuple(s.getsockname()[1] for s in socks)
    for s in socks:
        s.close()
    return ports


def _encrypted(obj: dict) -> str:
    pack = server._aes_ecb_encrypt(json.dumps(obj))
    return json.dumps({"t": "pack", "i": 1, "uid": 0, "cid": MAC, "tcid": "", "pack": pack})


def _decode(line: bytes) -> dict:
    msg = json.loads(line)
    if msg.get("t") == "pack":
        return json.loads(server._aes_ecb_decrypt(msg["pack"]))
    return msg


async def _talk(port: int, tls: bool, messages: list[str]) -> list[dict]:
    ctx = None
    if tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=ctx)
    replies = []
    for message in messages:
        writer.write(message.encode() + b"\n")
        await writer.drain()
        replies.append(_decode(await asyncio.wait_for(reader.readline(), 5)))
    writer.close()
    return replies


@pytest.fixture
def ssl_context(tmp_path):
    return server.build_ssl_context(str(tmp_path))


def test_aes_roundtrip():
    text = json.dumps({"t": "dis", "mac": MAC})
    assert server._aes_ecb_decrypt(server._aes_ecb_encrypt(text)) == text


def test_certificate_is_reused(tmp_path):
    server.build_ssl_context(str(tmp_path))
    first = (tmp_path / server.CERT_FILE).read_bytes()
    server.build_ssl_context(str(tmp_path))
    assert (tmp_path / server.CERT_FILE).read_bytes() == first


@pytest.mark.parametrize(
    ("mode", "expected_host"),
    [
        (const.MQTT_MODE_LOCAL, "192.168.1.10"),
        (const.MQTT_MODE_UNRESOLVABLE, const.UNRESOLVABLE_MQTT_HOST),
        (const.MQTT_MODE_NONE, None),
    ],
)
def test_dis_over_tls(ssl_context, mode, expected_host):
    async def run():
        ports = _free_ports(3)
        srv = server.GreeDummyServer(_config(mode, ports), ssl_context)
        await srv.start()
        try:
            (reply,) = await _talk(ports[1], True, [_encrypted({"t": "dis", "mac": MAC, "p": 1, "needMqtt": 1})])
        finally:
            await srv.stop()
        assert reply["t"] == "svr"
        assert reply["ip"] == "192.168.1.10"
        assert reply["tcpPort"] == ports[1]
        assert reply["protocol"] == ""
        if expected_host is None:
            assert "mqttInfo" not in reply
        else:
            assert reply["mqttInfo"]["host"] == expected_host
            assert reply["mqttInfo"]["port"] == ports[2]
        assert srv.devices[MAC]["need_mqtt"] is True

    asyncio.run(run())


def test_dis_over_tcp_without_mqtt(ssl_context):
    async def run():
        ports = _free_ports(3)
        srv = server.GreeDummyServer(_config(const.MQTT_MODE_LOCAL, ports), ssl_context)
        await srv.start()
        try:
            (reply,) = await _talk(ports[0], False, [_encrypted({"t": "dis", "mac": MAC})])
        finally:
            await srv.stop()
        assert reply["protocol"] == "TCP"
        assert reply["tcpPort"] == ports[0]
        assert "mqttInfo" not in reply

    asyncio.run(run())


def test_login_time_heartbeat_session(ssl_context):
    async def run():
        ports = _free_ports(3)
        srv = server.GreeDummyServer(_config(const.MQTT_MODE_LOCAL, ports), ssl_context)
        await srv.start()
        try:
            replies = await _talk(
                ports[1],
                True,
                [
                    json.dumps({"t": "devLogin", "mac": MAC}),
                    json.dumps({"t": "tm"}),
                    json.dumps({"t": "hb", "cid": MAC}),
                ],
            )
        finally:
            await srv.stop()
        assert replies[0] == {"t": "loginRes", "r": 200, "cid": "0439e037c0", "uid": 0}
        assert replies[1]["t"] == "tm"
        assert replies[2] == {"t": "hbok"}
        assert "last_heartbeat" in srv.devices[MAC]

    asyncio.run(run())


def test_port_in_use_raises(ssl_context):
    async def run():
        ports = _free_ports(3)
        blocker = await asyncio.start_server(lambda r, w: None, "0.0.0.0", ports[1])
        srv = server.GreeDummyServer(_config(const.MQTT_MODE_LOCAL, ports), ssl_context)
        try:
            with pytest.raises(OSError):
                await srv.start()
        finally:
            blocker.close()
            await blocker.wait_closed()

    asyncio.run(run())
