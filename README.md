# remote-relay

Fire a relay on cue from a lighting or show-control desk over WiFi. An **ESP32-C3**
receives **sACN (E1.31)** or **OSC** and switches a relay on/off — built to trigger
a theatre **aroma diffuser's** air pump, but it's just a network-controlled relay
and works for anything a desk should switch.

Push a fader up / fire a cue → relay closes. Pull it down, or lose the network →
relay opens. Failsafes force it **off** on WiFi loss, on a 2.5 s sACN stream gap,
and after an optional Max-ON timeout.

## Quick start

```bash
pio run -e c3 -t upload      # compile + flash over USB-C
pio device monitor           # watch logs (115200)
```

1. Join the setup WiFi **`AromaDiffuser-setup`** (password `aroma1234`), browse to
   **`http://192.168.4.1/`**, and set your show network + protocol/addresses.
2. Once on your network, it's at **`http://aroma.local/`** — live status, a **Test
   puff** button, and a **Config** page to change protocol, universe/channel,
   hostname, etc. without re-flashing.

## Details

- **[IMPLEMENTATION.md](IMPLEMENTATION.md)** — wiring, bill of materials, safety,
  configuration, bench-testing, and behaviour reference.
- **[ESP32_Relay/](ESP32_Relay/README.md)** — the custom carrier PCB (KiCad).

Target: ESP32-C3 Super Mini · PlatformIO env `c3` · arduino-esp32 v3 (pioarduino).
