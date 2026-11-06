"""Constants for the Gree Local integration."""

DOMAIN = "gree_local"

CONF_EXTERNAL_IP = "external_ip"
CONF_DOMAIN_NAME = "domain_name"
CONF_TCP_PORT = "tcp_port"
CONF_TLS_PORT = "tls_port"
CONF_MQTT_MODE = "mqtt_mode"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_HOLD = "mqtt_hold_seconds"

# How to answer devices that ask for MQTT ("needMqtt": 1, Wi-Fi firmware >= 1.26).
MQTT_MODE_NONE = "none"  # do not send mqttInfo at all
MQTT_MODE_LOCAL = "local_port"  # point MQTT at this server's sink port
MQTT_MODE_UNRESOLVABLE = "unresolvable_host"  # point MQTT at a name that does not resolve
MQTT_MODES = [MQTT_MODE_LOCAL, MQTT_MODE_UNRESOLVABLE, MQTT_MODE_NONE]

DEFAULT_DOMAIN_NAME = "eu.dis.gree.com"
DEFAULT_TCP_PORT = 5000
DEFAULT_TLS_PORT = 1813
DEFAULT_MQTT_MODE = MQTT_MODE_LOCAL
DEFAULT_MQTT_PORT = 1982
DEFAULT_MQTT_HOLD = 0
UNRESOLVABLE_MQTT_HOST = "mqtt.gree-local.invalid"
