# Changelog

## 1.0.0

- First release.
- Local answers for the Gree Wi-Fi module's cloud handshake: server discovery (`dis`) over TLS 1813 and TCP 5000,
  device login, time and heartbeat.
- Three answers for MQTT firmware (`needMqtt: 1`): local sink port, unresolvable host, or no MQTT info.
- Every address and port can be set in the UI, Home Assistant's LAN IP is detected automatically.
- Tested on the `362001065279` (GRJWB04-J) Wi-Fi module, firmware V1.45.
