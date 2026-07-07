# AromaDiffuser — Network → Pump Trigger

Fire a theatre aroma diffuser on cue from a lighting/show-control desk over the
network. An **ESP32-C3** receives either **sACN (E1.31)** or **OSC** and switches
the diffuser's **air pump** on/off. Push a fader up / fire a cue → scent releases.
Pull it down (or lose the network) → scent stops.

WiFi is set from a **captive-portal config page** — no re-flashing per venue — and
an **always-on status page** shows live state, has a **Test puff** button for tech
rehearsals, and lets you **edit all show settings live** (protocol, universe/channel,
hostname, …) without reopening the portal.

---

## How it works

The diffuser's original controller (the AXTEK MCU board, with its phone app and
built-in scheduler) is a sealed, mask-ROM chip — not reflashable, not worth
reverse-engineering. So we **don't touch its brain**. The scent is released by a
**12 V air pump**; we just drive that pump ourselves and bin the rest.

```
Desk / QLab ──sACN or OSC──▶ [show network] ──▶ ESP32-C3
                                                     │ GPIO10
   value ≥ threshold = pump ON                       ▼
   value < threshold = pump OFF                     relay ──▶ air pump (12 V)
   lost network / failsafe = pump OFF                        from diffuser PSU
```

Reused from the original unit: its **12 V power supply** (the wall brick) and the
**pump** itself. Everything else (the original PCB, app, RTC scheduler) is unused.

**sACN vs OSC** — they fail differently, and the firmware handles each correctly:

| | sACN (E1.31) | OSC |
|---|---|---|
| Style | continuous DMX stream | fire-and-forget events (e.g. QLab) |
| Trigger | one universe + channel, value ≥ threshold | one address, arg ≥ 0.5 / non-zero (bare message = ON) |
| Stream-loss failsafe | **yes** — no packets for 2.5 s = OFF | n/a (events don't stream); pump holds last command |
| Stuck-on safety | covered by failsafe | the **Max-ON watchdog** + **lost-WiFi = OFF** |

Both protocols also fail to OFF the instant **WiFi drops** (lost network = lost
control).

---

## ⚠️ Safety — read first

1. **Scent failsafes are built in.** Losing WiFi forces the pump OFF (both
   protocols). On **sACN**, a 2.5 s gap in the stream also forces OFF. On **OSC**
   (events, no stream), set **Max ON seconds** in the config page to a sensible
   cap (e.g. 30) so a missed "off" cue or a crashed QLab can't leave scent pumping
   forever. A dead show-network can never flood the house.
2. **Boot-safe pump.** Use a **HIGH-level-trigger** relay module and fit a **10 kΩ
   resistor from GPIO10 to GND**. That guarantees the pump stays OFF during boot,
   reset, and any firmware crash. (A low-level-trigger module would fire the pump
   on every reset — don't use one here.)
3. **Mains.** If your pump turns out to be **AC mains** (see "Confirm the pump"
   below), all pump-side wiring must be done by someone competent to work on
   mains, in an enclosure, fused, with proper isolation. The relay handles AC or
   DC; *you* handle it safely.
4. **Scent in a room lingers.** Test dosing in the actual venue with the HVAC
   running. Short bursts go a long way. Check for audience allergies/asthma per
   your venue's policy.

---

## Bill of materials

| Qty | Part | Notes |
|----|------|-------|
| 1 | ESP32-C3 Super Mini | You have these. WiFi-only is fine — both sACN and OSC run over WiFi. |
| 1 | **HIGH-level-trigger** opto-isolated relay module (5 V coil) | Switches the pump. Handles AC *or* DC, so we don't need to know which yet. |
| 1 | 10 kΩ resistor | GPIO10 → GND, keeps pump OFF at boot. |
| 1 | 12 V→5 V buck (MP1584 or similar) | Powers the C3 + relay coil off the diffuser's 12 V. *Or* just power the C3 from any USB brick. |
| — | The diffuser's 12 V PSU + its pump | Salvaged from the original unit. |
| — | Hookup wire, an enclosure | Stage kit lives hard — box it. |

Silent / solid-state alternative: swap the relay for a logic-level N-MOSFET
(e.g. IRLZ44N) + flyback diode — **DC pump only**. Ask and I'll give that variant.

**Custom PCB:** the wiring above uses off-the-shelf modules. There's also an
all-on-board carrier PCB (ESP32-C3 + transistor + relay + buck on one board) in
[`ESP32_Relay/`](ESP32_Relay/README.md) — a generated KiCad project, DRC-clean,
ready to route and fab. Read its "verify before fab" notes first (esp. the mains
caveat).

---

## Wiring

ESP32-C3 Super Mini:

| C3 pin | Connects to | Why |
|--------|-------------|-----|
| `GPIO10` | relay `IN` (and 10 kΩ to GND) | pump control; pulldown = boot-safe OFF |
| `5V`   | buck 5 V out | board power |
| `GND`  | common ground (buck, relay, PSU) | **all grounds must be common** |
| `GPIO8` | onboard LED (built-in) | status indicator, no wiring needed |

Pump power circuit (relay switches the pump's low side):

```
12V PSU (+) ─────────────▶ pump (+)
pump (−) ───▶ relay COM
relay NO ───▶ 12V PSU (−)         ← relay closes = pump runs
relay VCC ◀── 5V      relay GND ──▶ common GND      relay IN ◀── GPIO10
```

> The C3's GPIO is 3.3 V; opto-isolated relay modules trigger fine from 3.3 V
> while their coil runs off the 5 V `VCC`. Keep **one common ground** between the
> C3, the buck and the relay or the relay won't switch reliably.

---

## Build & flash (PlatformIO)

```bash
# from this folder
pio run -e c3 -t upload      # compile + flash over USB-C
pio device monitor           # watch logs (115200)
```

If the C3 won't auto-enter its bootloader: **hold BOOT (GPIO9), tap RST, release
BOOT**, then run upload again.

On the serial monitor you should see:

```
AromaDiffuser  proto=sACN
Config AP: "AromaDiffuser-setup"  pass: aroma1234  (browse to 192.168.4.1)
WiFi up: 192.168.x.x
sACN: universe=1 channel=1 threshold=128
Web UI: http://aroma.local
[pump] ON
[pump] off
```

---

## Configure for your show (web page)

First-time setup uses a **captive-portal config page** (WiFiManager) — nothing to
re-flash. The portal opens automatically on **first boot** (no WiFi saved), or
**on demand**: hold the **BOOT** button while powering up. After it's on your
network, you can also change everything except WiFi live at `http://aroma.local/`
(see "Changing settings later" below).

1. From a phone/laptop, join the WiFi network **`AromaDiffuser-setup`** (password
   **`aroma1234`**).
2. The config page pops up (or browse to **`http://192.168.4.1/`** — type the full
   `http://`, or the browser may search instead of connecting). Set:
   - **WiFi** — pick your show network + password
   - **Protocol** — `sacn` or `osc`
   - **[sACN] universe** (1–63999), **channel** (1–512), **threshold** (1–255, default 128)
   - **[OSC] address** (default `/aroma`) and **UDP port** (default 8000)
   - **Max ON seconds** (0 = unlimited) — stuck-on safety; **set this for OSC**
3. Save. The unit stores it in flash, reboots, and connects. It remembers across
   power cycles — next show day it just powers up and runs.

Fill in only the fields for your chosen protocol; the others are ignored.

**Changing settings later — two ways:**
- **Live (normal case):** just browse to **`http://aroma.local/`** on the show
  network and edit protocol / universe / channel / threshold / OSC / Max-ON /
  hostname in the **Config** section — no portal, no BOOT button. Saving stores to
  flash and reboots (~2 s) to apply. See "Live status & config page" below.
- **WiFi portal:** to change the **WiFi network** (or if it's unreachable), hold
  **BOOT** at power-up to reopen the captive portal (times out after 3 min and
  carries on with saved settings).

**Driving it from the desk:**
- **sACN** — patch a channel at the universe/slot you set; send **≥ threshold**
  to release, below it to stop.
- **OSC** — send to the device IP, your UDP port, address `/aroma` (or what you
  set). `/aroma 1` (or `1.0`, or a bare `/aroma`) releases; `/aroma 0` stops.
  In **QLab**, two Network cues — one `/aroma 1` on the scent cue, one `/aroma 0`
  to stop.

WiFi reliability for show day: put this on a **dedicated router/AP**, not house
WiFi. sACN over congested WiFi drops packets, and a 2.5 s gap trips the failsafe
OFF mid-cue. A quiet dedicated 2.4 GHz AP for the show network is plenty.

> The setup AP is **WPA2**, password **`aroma1234`** (an open softAP fails to
> associate with macOS/iOS on the ESP32-C3). Change it in `configure()` if you want.

---

## Live status & config page

Once running, the unit serves an always-on page at **`http://aroma.local/`** (or
its IP) — leave it open on a phone at the tech table:

- Live **pump state** (big indicator), protocol, IP, WiFi signal, and the active
  config.
- A **Test puff** button fires the pump for **2 s** regardless of whether a desk
  is connected — so you can prove the scent works during focus, before any cue
  exists.
- A **Config** section to edit protocol, universe/channel/threshold, OSC
  address/port, Max-ON, and **hostname** live. Saving writes to flash and reboots
  (~2 s) to apply — the page shows "saved — rebooting…", then reconnect.

The status view polls a tiny `/status.json`; it runs alongside sACN/OSC without
disturbing cue timing. (`aroma.local` needs mDNS/Bonjour — built into macOS/iOS;
on Windows use the IP shown on the serial monitor.)

> **Hostname:** if you change it in the Config section, the `.local` address
> changes too — the unit is then at **`http://<newname>.local/`** (the old
> `aroma.local` stops resolving). Note it down, or find it by IP.

---

## Bench test before you trust it on stage

1. Flash, open the serial monitor, confirm `WiFi up:` and an IP.
2. Open **`http://aroma.local`** and hit **Test puff** — the relay clicks and the
   pump runs for 2 s. Quickest proof the hardware works, no desk needed.
3. Send a real cue:
   - **sACN** — from **sACNView** / **QLC+** / your desk, set the universe + channel
     to `255`. Serial prints `[pump] ON`, LED solid, pump runs; drop to `0` → off.
   - **OSC** — from QLab or a tool like **Protokol/OSC sender**, send `/aroma 1`
     then `/aroma 0`.
4. **Failsafe test (do this!):** with the pump ON, pull the network / kill the
   sender. On sACN it goes off within 2.5 s; on OSC, drop WiFi and it goes off
   immediately. Verify before you trust it in front of an audience.

---

## Behaviour reference

| Situation | Pump | Onboard LED |
|-----------|------|-------------|
| Config portal open (first boot / BOOT held) | OFF | — |
| WiFi connecting / lost | OFF (forced) | fast blink |
| Value below threshold / OSC "off" | OFF | off |
| Value at/above threshold / OSC "on" | **ON** | solid |
| No sACN for 2.5 s | OFF (forced) | off |
| Web "Test puff" pressed | **ON** for 2 s | solid |
| Max-ON seconds exceeded | OFF (forced) | off |
| Boot / reset / crash | OFF (pulldown) | — |

---

## Still to confirm — measure the pump

We sized everything around a 12 V DC pump (the board has a 12 V rail). Before
final wiring, trigger the original diffuser once via its app and meter the
**AC/PUMP** connector while it runs:

- **Voltage + AC or DC?** Confirms PSU + relay rating. If it's AC mains, see Safety #3.
- **Current draw** (or the pump's printed rating) — confirms a standard relay
  copes (it almost certainly does).

Send me those two numbers and I'll confirm the relay/PSU choice.

---

## Upgrade paths (only if you actually need them)

- **Timed bursts** — auto-puff of fixed length per trigger so a held fader doesn't
  over-saturate (start a timer on the rising edge, auto-off after N ms). Max-ON is
  a blunt version of this today.
- **Variable intensity** — PWM the pump from the channel/arg value via a MOSFET.
- **Manual ON/OFF + all-stop on the web page** — the page has a Test puff today;
  add latching control if an operator wants to drive it by hand.
- **Wired Ethernet** — swap the C3 for a WT32-ETH01; same logic, real Ethernet,
  no WiFi packet loss. Best if the desk network is wired.

Say which and I'll extend the sketch.
