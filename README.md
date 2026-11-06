# Gree Dummy Server for Home Assistant

A Home Assistant custom integration (installable from HACS) that answers the
Gree Wi-Fi module's cloud handshake locally, so Gree air conditioners keep
working on your LAN when their internet access is blocked. Control the units
with Home Assistant's built-in **Gree Climate** integration (local UDP 7000).

> [!WARNING]
> Wi-Fi module firmware that asks for MQTT (`needMqtt: 1`, firmware 1.26+ on
> the GRJWB04-J / `362001065279` module) validates a certificate pinned in the
> firmware, so its MQTT connection cannot be faked. For those units this
> integration offers several MQTT answers (see below); which one keeps your
> unit responsive depends on the module. Check the logs after setup.

## How it works

1. All `*.gree.com` DNS names are pointed at Home Assistant.
2. The AC asks "which server should I use?" (`dis`) on TLS port 1813 (or TCP
   5000 on old firmware). This integration replies with Home Assistant's own IP.
3. Login, time and heartbeat requests are answered locally. Nothing leaves your
   network.

## Installation

1. HACS → ⋮ → Custom repositories → add this repository as type **Integration**.
2. Install **Gree Dummy Server** and restart Home Assistant.
3. Settings → Devices & services → Add integration → **Gree Dummy Server**.
   Home Assistant's LAN IP is filled in automatically; every value can be
   changed later via **Configure**.

| Option | Default | Meaning |
|---|---|---|
| Home Assistant IP | auto-detected | Address the ACs connect to |
| Server host name | `eu.dis.gree.com` | Host name announced to the ACs |
| TCP port | 5000 | Plain TCP (old firmware) |
| TLS port | 1813 | TLS (firmware 1.2x and newer) |
| MQTT mode | `local_port` | Answer for MQTT firmware, see below |
| MQTT port | 1982 | MQTT port announced to the ACs |
| MQTT hold seconds | 0 | How long MQTT attempts are kept open before closing |

### MQTT modes (only used when the AC sends `needMqtt: 1`)

- `local_port`: MQTT points at this server, which accepts and drops the
  connection. Reported to keep units responsive, but they retry very often.
  Raise *MQTT hold seconds* to slow the retries down.
- `unresolvable_host`: MQTT points at a host name that does not exist. Also
  reported to keep units responsive, but they send many DNS queries.
- `none`: no MQTT info (behaves like the original cloud being unreachable).

## DNS setup

Point every `*.gree.com` name at Home Assistant. With AdGuard Home add this
custom filtering rule (replace the IP):

```
||gree.com^$dnsrewrite=192.168.0.30
```

Make sure the ACs cannot bypass it: if your router hands out a second DNS
server, or the units may use hard-coded DNS, also block their internet access
on the router (by MAC address). Then power-cycle the units.

## Checking it works

Enable debug logging and watch the log:

```yaml
logger:
  logs:
    custom_components.gree_dummy_server: debug
```

You should see `Device <mac> asked for its server` after an AC restarts, and
the unit should stay available in the Gree Climate integration.

## Credits and license

Protocol handling is based on
[joserebelo/gree-dummy-tls-server](https://codeberg.org/joserebelo/gree-dummy-tls-server)
and [emtek-at/GreeAC-DummyServer](https://github.com/emtek-at/GreeAC-DummyServer).
Licensed under GPL-3.0, like the project it is derived from.
