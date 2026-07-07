#!/usr/bin/env python3
"""
Generate ESP32_Relay.kicad_pcb — a basic carrier board for the AromaDiffuser:
  12V IN -> MP1584 buck -> 5V -> ESP32-C3 Super Mini + relay coil
  GPIO10 -> 1k -> NPN base -> relay coil (flyback diode) -> SPDT relay
  relay COM = 12V, NO -> PUMP terminal ; 10k pulldown keeps the relay off at boot.

Run with KiCad's bundled Python (has pcbnew):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_board.py

This writes the .kicad_pcb directly (pcbnew has no schematic API). The board
carries its own netlist — do NOT run "Update PCB from schematic" or it clears it.
ponytail: parts placed + netted + GND pour + outline; routing left to KiCad's
router (only ~6 nets). Verify the C3 header pitch and relay pinout before fab.
"""
import os, pcbnew
from pcbnew import VECTOR2I, FromMM

HERE = os.path.dirname(os.path.abspath(__file__))
FPBASE = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"

# (lib, footprint)
HDR8  = ("Connector_PinHeader_2.54mm", "PinHeader_1x08_P2.54mm_Vertical")
HDR4  = ("Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical")
TERM2 = ("TerminalBlock", "TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm")
RELAY = ("Relay_THT", "Relay_SPDT_SANYOU_SRD_Series_Form_C")
TO92  = ("Package_TO_SOT_THT", "TO-92_Inline")
RAX   = ("Resistor_THT", "R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal")
DIODE = ("Diode_THT", "D_DO-41_SOD81_P7.62mm_Horizontal")
HOLE  = ("MountingHole", "MountingHole_3.2mm_M3_DIN965_Pad")  # annular pad -> tie to GND

board = pcbnew.NewBoard(os.path.join(HERE, "ESP32_Relay.kicad_pcb"))

def place(ref, spec, x, y, rot=0, value=""):
    lib, name = spec
    fp = pcbnew.FootprintLoad(os.path.join(FPBASE, lib + ".pretty"), name)
    fp.SetReference(ref)
    if value:
        fp.SetValue(value)
    board.Add(fp)
    fp.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    if rot:
        fp.SetOrientationDegrees(rot)
    return fp

# ── Nets ─────────────────────────────────────────────────────────────────────
def net(name):
    n = pcbnew.NETINFO_ITEM(board, name)
    board.Add(n)
    return n

GND, V12, V5 = net("GND"), net("+12V"), net("+5V")
CTRL, BASE, COILDRV, PUMP = net("CTRL_IO10"), net("Q_BASE"), net("COIL_DRV"), net("PUMP")

# ── Place parts (mm) ─────────────────────────────────────────────────────────
A1 = place("A1", HDR8, 110, 116, value="C3 L:5V,GND,3V3,IO4,IO3,IO2,IO1,IO0")
A2 = place("A2", HDR8, 123, 116, value="C3 R:IO5,IO6,IO7,IO8,IO9,IO10,RX,TX")
U1 = place("U1", HDR4, 140, 104, value="MP1584 12V->5V: VIN+,VIN-,VOUT+,VOUT-")
R2 = place("R2", RAX, 112, 142, value="10k pulldown")
R1 = place("R1", RAX, 130, 147, value="1k base")
Q1 = place("Q1", TO92, 140, 138, value="PN2222A E-B-C")
D1 = place("D1", DIODE, 155, 112, value="1N4007 (band=K -> +5V)")
K1 = place("K1", RELAY, 146, 126, value="5V relay SRD-05VDC-SL-C")
J1 = place("J1", TERM2, 120, 153, value="12V IN")
J2 = place("J2", TERM2, 152, 153, value="PUMP")
for ref, (hx, hy) in {"H1": (106, 106), "H2": (174, 106),
                      "H3": (106, 154), "H4": (174, 154)}.items():
    h = place(ref, HOLE, hx, hy)
    hp = h.FindPadByNumber("1")
    if hp:
        hp.SetNet(GND)            # grounded mounting holes -> no hole-in-pour clearance hit

# Hide the descriptive value text on silk (keeps refs; notes live in properties).
for fp in board.GetFootprints():
    fp.Value().SetVisible(False)
# Hide refs where a clearer silk label replaces them (C3 headers + terminals).
for fp in (A1, A2, J1, J2):
    fp.Reference().SetVisible(False)

# Silk labels so the board is self-documenting (terminals + C3 orientation).
def silk(text, x, y, size=1.0):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    t.SetTextSize(VECTOR2I(FromMM(size), FromMM(size)))
    t.SetTextThickness(FromMM(0.15))
    board.Add(t)

silk("AromaDiffuser", 136, 149)
silk("12V IN", 120, 148)
silk("PUMP", 152, 148)
silk("5V", 110, 113)          # A1 pin 1
silk("IO10", 129, 129, 0.9)   # A2 pin 6

# (footprint, pad number, net)
wire = [
    (J1, "1", V12), (J1, "2", GND),                                  # 12V input
    (U1, "1", V12), (U1, "2", GND), (U1, "3", V5), (U1, "4", GND),   # buck
    (A1, "1", V5),  (A1, "2", GND),                                  # C3: 5V, GND
    (A2, "6", CTRL),                                                 # C3: GPIO10
    (R1, "1", CTRL), (R1, "2", BASE),                                # base resistor
    (R2, "1", CTRL), (R2, "2", GND),                                 # 10k pulldown
    (Q1, "1", GND),  (Q1, "2", BASE), (Q1, "3", COILDRV),            # NPN E,B,C
    (K1, "2", V5),   (K1, "5", COILDRV),                             # relay coil (pins 2,5)
    (K1, "1", V12),  (K1, "3", PUMP),                                # COM=pin1=12V, NO=pin3=pump
    (D1, "1", V5),   (D1, "2", COILDRV),                             # flyback: K->+5V, A->coil
    # K1 pin 4 = NC (unused)
    (J2, "1", PUMP), (J2, "2", GND),                                 # pump out
]
for fp, padnum, n in wire:
    pad = fp.FindPadByNumber(padnum)
    assert pad is not None, f"{fp.GetReference()} pad {padnum} not found"
    pad.SetNet(n)

# ── Board outline (Edge.Cuts rectangle) ──────────────────────────────────────
X0, Y0, X1, Y1 = 100, 100, 180, 160
for (ax, ay, bx, by) in [(X0, Y0, X1, Y0), (X1, Y0, X1, Y1),
                         (X1, Y1, X0, Y1), (X0, Y1, X0, Y0)]:
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetStart(VECTOR2I(FromMM(ax), FromMM(ay)))
    seg.SetEnd(VECTOR2I(FromMM(bx), FromMM(by)))
    seg.SetLayer(pcbnew.Edge_Cuts)
    seg.SetWidth(FromMM(0.15))
    board.Add(seg)

# ── GND pour, both copper layers (inset 0.5 mm from the board edge) ───────────
I = 0.5
for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNetCode(GND.GetNetCode())
    zone.SetLocalClearance(FromMM(0.4))     # keep copper off the mounting holes
    poly = zone.Outline()
    poly.NewOutline()
    for (px, py) in [(X0 + I, Y0 + I), (X1 - I, Y0 + I), (X1 - I, Y1 - I), (X0 + I, Y1 - I)]:
        poly.Append(VECTOR2I(FromMM(px), FromMM(py)))
    board.Add(zone)
pcbnew.ZONE_FILLER(board).Fill(board.Zones())

pcbnew.SaveBoard(os.path.join(HERE, "ESP32_Relay.kicad_pcb"), board)
print("wrote ESP32_Relay.kicad_pcb:",
      len(board.GetFootprints()), "footprints,",
      board.GetNetCount(), "nets")
