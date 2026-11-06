# Changelog

## 1.1.0

- Renamed to **Gree Local** (repository `ha-gree-local`, domain `gree_local`). If you installed 1.0.0,
  remove the old *Gree Dummy Server* integration and add *Gree Local*.
- Security: only clients on the local network (private, loopback, link-local addresses) are served;
  connections from public addresses are rejected and logged.
- README rewritten around the security goal, with a step-by-step setup for non-programmers.

## 1.0.0

- First release.
- Local answers for the Gree Wi-Fi module's cloud handshake: server discovery (`dis`) over TLS 1813 and TCP 5000,
  device login, time and heartbeat.
- Three answers for MQTT firmware (`needMqtt: 1`): local sink port, unresolvable host, or no MQTT info.
- Every address and port can be set in the UI, Home Assistant's LAN IP is detected automatically.
- Tested on the `362001065279` (GRJWB04-J) Wi-Fi module, firmware V1.45.
