# mitsu-kkl firmware for the Raspberry Pi Pico 2 W (MicroPython): a Wi-Fi access point that
# serves the live data page (web/) and reads the engine ECU over the K-line with MUT-II.
# Runs on power-up. Settings in config.json (see config.json and README.md next to this file).
import asyncio
import gc
import json

import network
from machine import Pin

import httpd
from hub import Hub
from kline import KLine

DEFAULTS = {
    "ssid": "mitsu-kkl", "password": "mitsukkl", "country": "PL",
    "uart": 0, "tx_gpio": 0, "rx_gpio": 1, "invert_tx": True, "invert_rx": False,  # hw/schemat.svg
    "pin1_gpio": 2, "pin1_active_high": True, "http_port": 80, "auto_connect": True,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open("config.json") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError) as e:
        print("config.json:", e, "- using defaults")
    return cfg


def version():
    try:
        from version import VERSION
        return VERSION
    except ImportError:
        return "dev"


def start_ap(cfg):
    try:
        network.country(cfg["country"])
    except (AttributeError, ValueError):
        pass
    ap = network.WLAN(network.AP_IF)
    if len(cfg["password"]) >= 8:
        ap.config(essid=cfg["ssid"], password=cfg["password"])
    else:  # WPA2 needs 8+ characters; an empty/short password means an open network
        ap.config(essid=cfg["ssid"], security=0)
    ap.active(True)
    return ap


async def main():
    cfg = load_config()
    ap = start_ap(cfg)
    kl = KLine(cfg)
    pin1 = Pin(cfg["pin1_gpio"], Pin.OUT) if cfg["pin1_gpio"] is not None else None
    try:
        led = Pin("LED", Pin.OUT)
    except (TypeError, ValueError):
        led = Pin(25, Pin.OUT)
    hub = Hub(cfg, kl, pin1, led, version())
    await httpd.serve(hub, cfg["http_port"])
    print("mitsu-kkl %s: Wi-Fi '%s', open http://%s/" % (hub.version, cfg["ssid"], ap.ifconfig()[0]))
    asyncio.create_task(hub.flusher())
    asyncio.create_task(hub.blinker())
    if cfg["auto_connect"]:
        hub.connect()
    while True:
        await asyncio.sleep(10)
        gc.collect()


if __name__ == "__main__":
    asyncio.run(main())
