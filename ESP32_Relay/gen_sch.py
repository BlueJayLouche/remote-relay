#!/usr/bin/env python3
"""
Generate ESP32_Relay.kicad_sch — schematic matching the generated PCB.

KiCad has no Python schematic API, so this writes the .kicad_sch s-expression
directly: it pulls the real symbol definitions (and their pin coordinates) from
KiCad's libraries, places each part, and ties them together with NET LABELS at
each pin (robust, ERC-valid, no fragile wire routing). Net names match the PCB.

Run with KiCad's bundled Python (for the library path; any python3 works too):
  python3 gen_sch.py
Then verify:  kicad-cli sch erc / export netlist
"""
import os, re, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SYM = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/"

# logical -> (symbol library, symbol name, default footprint)
LIB = {
    "R":  ("Device", "R", "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal"),
    "D":  ("Device", "D", "Diode_THT:D_DO-41_SOD81_P7.62mm_Horizontal"),
    "Q":  ("Transistor_BJT", "Q_NPN_EBC", "Package_TO_SOT_THT:TO-92_Inline"),
    "K":  ("Relay", "SANYOU_SRD_Form_C", "Relay_THT:Relay_SPDT_SANYOU_SRD_Series_Form_C"),
    "H8": ("Connector_Generic", "Conn_01x08", "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical"),
    "H4": ("Connector_Generic", "Conn_01x04", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"),
    "T2": ("Connector", "Screw_Terminal_01x02", "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"),
}

def grab(path, name):
    t = open(path).read()
    i = t.find(f'(symbol "{name}"')
    j = i - 1; d = 0; k = j
    while k < len(t):
        if t[k] == '(': d += 1
        elif t[k] == ')':
            d -= 1
            if d == 0: break
        k += 1
    return t[j:k + 1]

def pin_coords(block):
    out = {}
    for pm in re.finditer(r'\(pin\b', block):
        s = pm.start(); d = 0; e = s
        while e < len(block):
            if block[e] == '(': d += 1
            elif block[e] == ')':
                d -= 1
                if d == 0: break
            e += 1
        pj = block[s:e + 1]
        at = re.search(r'\(at ([\-\d.]+) ([\-\d.]+) (\d+)\)', pj)
        num = re.search(r'\(number "([^"]+)"', pj)
        if at and num:
            out[num.group(1)] = (float(at.group(1)), float(at.group(2)), int(at.group(3)))
    return out

# Load symbol blocks + pin maps
sym = {}
for key, (lib, name, _) in LIB.items():
    block = grab(SYM + lib + ".kicad_sym", name)
    libid = f"{lib}:{name}"
    embed = block.replace(f'(symbol "{name}"', f'(symbol "{libid}"', 1)
    sym[key] = dict(libid=libid, embed=embed, pins=pin_coords(block))

def uid():
    return str(uuid.uuid4())

ROOT = uid()

# ── Parts: (ref, type, value, x, y, {pin: net}) ──────────────────────────────
PARTS = [
    ("J1", "T2", "12V IN",   40,  70, {"1": "+12V", "2": "GND"}),
    ("U1", "H4", "MP1584",   75,  70, {"1": "+12V", "2": "GND", "3": "+5V", "4": "GND"}),
    ("A1", "H8", "ESP32-C3 L",120, 80, {"1": "+5V", "2": "GND"}),
    ("A2", "H8", "ESP32-C3 R",160, 80, {"6": "CTRL_IO10"}),
    ("R2", "R",  "10k",      120, 130, {"1": "CTRL_IO10", "2": "GND"}),
    ("R1", "R",  "1k",       150, 130, {"1": "CTRL_IO10", "2": "Q_BASE"}),
    ("Q1", "Q",  "PN2222A",  180, 130, {"1": "GND", "2": "Q_BASE", "3": "COIL_DRV"}),
    ("D1", "D",  "1N4007",   215,  70, {"1": "+5V", "2": "COIL_DRV"}),
    ("K1", "K",  "SRD-05VDC-SL-C", 225, 115, {"1": "+12V", "3": "PUMP", "2": "+5V", "5": "COIL_DRV"}),
    ("J2", "T2", "PUMP",     270, 115, {"1": "PUMP", "2": "GND"}),
]

# Schematic Y is flipped vs symbol library Y; pins are axis-aligned.
OUT2LABEL = {0: 0, 90: 270, 180: 180, 270: 90}   # symbol-outward angle -> sch label angle

instances, wires, labels, ncs = [], [], [], []
for ref, typ, val, X, Y, nets in PARTS:
    s = sym[typ]
    fp = LIB[typ][2]
    instances.append(f'''  (symbol
    (lib_id "{s['libid']}")
    (at {X} {Y} 0)
    (unit 1)
    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
    (uuid "{uid()}")
    (property "Reference" "{ref}" (at {X} {Y - 12.7} 0) (effects (font (size 1.27 1.27))))
    (property "Value" "{val}" (at {X} {Y + 12.7} 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "{fp}" (at {X} {Y} 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (instances (project "ESP32_Relay" (path "/{ROOT}" (reference "{ref}") (unit 1))))
  )''')
    for pnum, net in nets.items():
        px, py, ang = s["pins"][pnum]
        out = (ang + 180) % 360
        import math
        L = 3.81
        sx, sy = px + L * math.cos(math.radians(out)), py + L * math.sin(math.radians(out))
        # transform symbol -> sheet (Y flip)
        tipx, tipy = X + px, Y - py
        stubx, stuby = X + sx, Y - sy
        wires.append(f'  (wire (pts (xy {tipx:.2f} {tipy:.2f}) (xy {stubx:.2f} {stuby:.2f}))'
                     f' (stroke (width 0) (type default)) (uuid "{uid()}"))')
        labels.append(f'  (label "{net}" (at {stubx:.2f} {stuby:.2f} {OUT2LABEL[out]})'
                      f' (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{uid()}"))')
    # Mark every unused pin no-connect so ERC is clean (C3 spare IOs, relay NC).
    for pnum, (px, py, ang) in s["pins"].items():
        if pnum not in nets:
            ncs.append(f'  (no_connect (at {X + px:.2f} {Y - py:.2f}) (uuid "{uid()}"))')

libsyms = "\n".join(s["embed"] for s in sym.values())
doc = f'''(kicad_sch
  (version 20260306)
  (generator "gen_sch.py")
  (generator_version "10.0")
  (uuid "{ROOT}")
  (paper "A3")
  (lib_symbols
{libsyms}
  )
{chr(10).join(wires)}
{chr(10).join(labels)}
{chr(10).join(ncs)}
{chr(10).join(instances)}
  (sheet_instances (path "/" (page "1")))
  (embedded_fonts no)
)
'''
open(os.path.join(HERE, "ESP32_Relay.kicad_sch"), "w").write(doc)
print(f"wrote ESP32_Relay.kicad_sch: {len(PARTS)} parts, {len(labels)} net labels")
