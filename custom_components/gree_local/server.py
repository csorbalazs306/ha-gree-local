"""Local stand-in for the Gree cloud, so Gree Wi-Fi modules work without internet.

Protocol handling is based on joserebelo's gree-dummy-tls-server
(https://codeberg.org/joserebelo/gree-dummy-tls-server, GPL-3.0) and
emtek-at's GreeAC-DummyServer. This module has no Home Assistant imports,
so it can be run and tested on its own.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
import datetime as dt
import ipaddress
import json
import logging
import os
import ssl
import time
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.x509.oid import NameOID

from .const import (
    CONF_DOMAIN_NAME,
    CONF_EXTERNAL_IP,
    CONF_MQTT_HOLD,
    CONF_MQTT_MODE,
    CONF_MQTT_PORT,
    CONF_TCP_PORT,
    CONF_TLS_PORT,
    MQTT_MODE_LOCAL,
    MQTT_MODE_UNRESOLVABLE,
    UNRESOLVABLE_MQTT_HOST,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_KEY = b"a3K8Bx%2r8Y7#xDh"
READ_TIMEOUT = 60
CERT_FILE = "selfsigned.crt"
KEY_FILE = "private.key"


def is_lan_address(host: Any) -> bool:
    """True for addresses that can only come from the local network (private, loopback, link-local)."""
    try:
        ip = ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _aes_ecb_encrypt(plain: str) -> str:
    data = plain.encode()
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    enc = Cipher(algorithms.AES(DEFAULT_KEY), modes.ECB()).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode()


def _aes_ecb_decrypt(pack: str) -> str:
    dec = Cipher(algorithms.AES(DEFAULT_KEY), modes.ECB()).decryptor()
    text = (dec.update(base64.b64decode(pack)) + dec.finalize()).decode(errors="ignore")
    return text[: text.rindex("}") + 1]


def build_ssl_context(storage_dir: str) -> ssl.SSLContext:
    """Create (once) a self-signed certificate and return a permissive TLS context.

    Blocking: run it in an executor.
    """
    os.makedirs(storage_dir, exist_ok=True)
    cert_path = os.path.join(storage_dir, CERT_FILE)
    key_path = os.path.join(storage_dir, KEY_FILE)
    if not (os.path.isfile(cert_path) and os.path.isfile(key_path)):
        _LOGGER.info("Generating self-signed certificate in %s", storage_dir)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "gree-local")])
        now = dt.datetime.now(dt.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .sign(key, hashes.SHA256())
        )
        with open(key_path, "wb") as f:
            f.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                )
            )
        os.chmod(key_path, 0o600)
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # The Wi-Fi modules use old TLS stacks; accept whatever they offer.
    with suppress(ValueError, ssl.SSLError):
        ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    with suppress(ssl.SSLError):
        ctx.set_ciphers("ALL:@SECLEVEL=0")
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return ctx


class GreeLocalServer:
    """Answers the Gree Wi-Fi module's cloud handshake locally."""

    def __init__(self, config: dict[str, Any], ssl_context: ssl.SSLContext) -> None:
        self._cfg = config
        self._ssl = ssl_context
        self._servers: list[asyncio.Server] = []
        self._tasks: set[asyncio.Task] = set()
        self._mqtt_hits = 0
        self._rejected: set[str] = set()
        self.devices: dict[str, dict[str, Any]] = {}

    def _reject_non_lan(self, writer: asyncio.StreamWriter) -> bool:
        """Drop connections that do not come from the local network. Returns True if rejected."""
        peer = writer.get_extra_info("peername")
        host = peer[0] if peer else None
        if is_lan_address(host):
            return False
        if host not in self._rejected:
            self._rejected.add(host)
            _LOGGER.warning("Rejected connection from non-local address %s (only LAN clients are served)", host)
        writer.close()
        return True

    async def start(self) -> None:
        """Open the listening sockets; raises OSError if a port is taken."""
        try:
            self._servers.append(
                await asyncio.start_server(
                    lambda r, w: self._handle(r, w, tls=False), "0.0.0.0", self._cfg[CONF_TCP_PORT]
                )
            )
            self._servers.append(
                await asyncio.start_server(
                    lambda r, w: self._handle(r, w, tls=True),
                    "0.0.0.0",
                    self._cfg[CONF_TLS_PORT],
                    ssl=self._ssl,
                    ssl_handshake_timeout=15,
                )
            )
            if self._cfg[CONF_MQTT_MODE] == MQTT_MODE_LOCAL:
                self._servers.append(
                    await asyncio.start_server(self._mqtt_sink, "0.0.0.0", self._cfg[CONF_MQTT_PORT])
                )
                self._spawn(self._report_mqtt_hits())
        except OSError:
            await self.stop()
            raise
        _LOGGER.info(
            "Gree Local server listening: tcp=%s tls=%s mqtt=%s (mode %s), announcing %s / %s",
            self._cfg[CONF_TCP_PORT],
            self._cfg[CONF_TLS_PORT],
            self._cfg[CONF_MQTT_PORT],
            self._cfg[CONF_MQTT_MODE],
            self._cfg[CONF_EXTERNAL_IP],
            self._cfg[CONF_DOMAIN_NAME],
        )

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for server in self._servers:
            server.close()
        for server in self._servers:
            with suppress(Exception):
                await asyncio.wait_for(server.wait_closed(), 5)
        self._servers.clear()

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- Gree handshake (TCP 5000 / TLS 1813) ---------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, tls: bool) -> None:
        task = asyncio.current_task()
        if task:
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        if self._reject_non_lan(writer):
            return
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("Connection from %s (tls=%s)", peer, tls)
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), READ_TIMEOUT)
                if not line:
                    break
                message = line.decode(errors="ignore").strip()
                _LOGGER.debug("Received from %s: %s", peer, message)
                request = json.loads(message)
                encrypted = request.get("t") == "pack"
                if encrypted:
                    if request.get("i") != 1:
                        _LOGGER.warning("Request from %s uses a device key, cannot decrypt", peer)
                        break
                    request = json.loads(_aes_ecb_decrypt(request["pack"]))
                    _LOGGER.debug("Decrypted from %s: %s", peer, request)
                reply, keepalive, encrypted = self._reply(request, tls, encrypted, peer)
                if reply is None:
                    break
                plain = json.dumps(reply, separators=(",", ":"))
                _LOGGER.debug("Reply to %s: %s", peer, plain)
                if encrypted:
                    plain = json.dumps(
                        {
                            "t": "pack",
                            "i": 1,
                            "uid": 0,
                            "cid": "",
                            "tcid": request.get("mac", "") if request.get("t") == "dis" else "",
                            "pack": _aes_ecb_encrypt(plain),
                        },
                        separators=(",", ":"),
                    )
                writer.write(plain.encode() + b"\n")
                await writer.drain()
                if not keepalive:
                    break
        except TimeoutError:
            _LOGGER.debug("Connection from %s timed out", peer)
        except (ConnectionError, ssl.SSLError, ValueError, KeyError) as err:
            _LOGGER.debug("Connection from %s failed: %s", peer, err)
        finally:
            writer.close()
            with suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 5)

    def _reply(
        self, req: dict[str, Any], tls: bool, encrypted: bool, peer: Any
    ) -> tuple[dict[str, Any] | None, bool, bool]:
        """Return (reply, keep connection open, encrypt reply)."""
        kind = req.get("t")
        if kind == "dis":
            mac = req.get("mac", "")
            port = self._cfg[CONF_TLS_PORT] if tls else self._cfg[CONF_TCP_PORT]
            ip = self._cfg[CONF_EXTERNAL_IP]
            reply: dict[str, Any] = {
                "t": "svr",
                "ip": ip,
                "ip2": ip,
                "Ip3": ip,
                "host": self._cfg[CONF_DOMAIN_NAME],
                "udpPort": port,
                "tcpPort": port,
                "protocol": "" if tls else "TCP",
                "datHost": "",
                "datHostPort": 0,
            }
            mode = self._cfg[CONF_MQTT_MODE]
            if req.get("needMqtt") and mode in (MQTT_MODE_LOCAL, MQTT_MODE_UNRESOLVABLE):
                reply["mqttInfo"] = {
                    "host": ip if mode == MQTT_MODE_LOCAL else UNRESOLVABLE_MQTT_HOST,
                    "port": int(self._cfg[CONF_MQTT_PORT]),
                    "username": mac or "gree",
                    "password": "gree-local",
                }
            self.devices.setdefault(mac, {}).update(
                {"ip": peer[0] if peer else None, "last_dis": time.time(), "need_mqtt": bool(req.get("needMqtt"))}
            )
            _LOGGER.info(
                "Device %s (%s) asked for its server, need_mqtt=%s",
                mac,
                peer and peer[0],
                bool(req.get("needMqtt")),
            )
            return reply, False, True
        if kind == "devLogin":
            m = req.get("mac", "")
            cid = m[8:10] + m[14:16] + m[2:4] + m[10:12] + m[4:6] + m[0:2]
            self.devices.setdefault(m, {})["last_login"] = time.time()
            _LOGGER.info("Device %s logged in", m)
            return {"t": "loginRes", "r": 200, "cid": cid, "uid": 0}, True, encrypted
        if kind == "tm":
            return {"t": "tm", "time": time.strftime("%Y-%m-%d %H:%M:%S")}, True, encrypted
        if kind == "hb":
            self.devices.setdefault(req.get("cid", ""), {})["last_heartbeat"] = time.time()
            return {"t": "hbok"}, True, encrypted
        _LOGGER.warning("Unknown request type %r from %s: %s", kind, peer, req)
        return None, False, encrypted

    # --- MQTT sink ------------------------------------------------------------

    async def _mqtt_sink(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Accept MQTT/TLS attempts and drop them (real Gree MQTT uses a pinned certificate)."""
        if self._reject_non_lan(writer):
            return
        self._mqtt_hits += 1
        try:
            hold = float(self._cfg.get(CONF_MQTT_HOLD, 0))
            if hold > 0:
                with suppress(Exception):
                    await asyncio.wait_for(reader.read(-1), hold)
        finally:
            writer.close()
            with suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 2)

    async def _report_mqtt_hits(self) -> None:
        while True:
            await asyncio.sleep(60)
            if self._mqtt_hits:
                _LOGGER.info("MQTT sink: %d connection attempts in the last minute", self._mqtt_hits)
                self._mqtt_hits = 0
