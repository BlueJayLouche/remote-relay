#!/usr/bin/env python3
"""
Route ESP32_Relay.kicad_pcb. GND is the poured plane; this routes the other 6
nets with explicit, hand-planned paths that dodge the dense pad rows (the buck
header, the relay contacts) and put crossing nets on opposite copper layers.
Through-hole pads span both layers, so a net changes layer at a pad — no vias.

Run:  <kicad python> gen_routes.py    (verify after with kicad-cli pcb drc)
"""
import os, pcbnew
from pcbnew import VECTOR2I, FromMM

HERE = os.path.dirname(os.path.abspath(__file__))
board = pcbnew.LoadBoard(os.path.join(HERE, "ESP32_Relay.kicad_pcb"))
for t in list(board.GetTracks()):          # idempotent re-route
    board.Remove(t)

F, B = pcbnew.F_Cu, pcbnew.B_Cu
WIDTH = {"+12V": 1.0, "PUMP": 1.0, "+5V": 0.6, "COIL_DRV": 0.5, "CTRL_IO10": 0.4, "Q_BASE": 0.4}

# (net, [waypoints...], layer). +12V & one COIL leg on the bottom; rest on top.
PATHS = [
    ("+12V", [(120, 153), (146, 126)], B),                              # J1 -> K1 COM
    ("+12V", [(146, 126), (146, 102), (140, 102), (140, 104)], B),      # K1 COM -> U1.1 over the top
    ("+5V", [(110, 116), (140, 109.08)], F),                            # A1 5V -> buck out
    ("+5V", [(140, 109.08), (155, 112)], F),                            # buck out -> D1 K
    ("+5V", [(155, 112), (147.95, 132.05)], F),                         # D1 K -> K1 coil
    ("COIL_DRV", [(162.62, 112), (147.95, 120.05)], B),                 # D1 A -> K1 coil
    ("COIL_DRV", [(147.95, 120.05), (144, 120.05), (144, 138), (142.54, 138)], F),  # K1 coil -> Q1 C
    ("CTRL_IO10", [(123, 128.7), (112, 142)], F),                       # GPIO10 -> R2
    ("CTRL_IO10", [(112, 142), (130, 147)], F),                         # R2 -> R1
    ("Q_BASE", [(137.62, 147), (141.27, 138)], F),                      # R1 -> Q1 B
    ("PUMP", [(160.15, 132.05), (152, 153)], F),                        # K1 NO -> J2
]

for net, pts, layer in PATHS:
    code = board.FindNet(net)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
        t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
        t.SetWidth(FromMM(WIDTH[net]))
        t.SetLayer(layer)
        t.SetNet(code)
        board.Add(t)

pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(os.path.join(HERE, "ESP32_Relay.kicad_pcb"), board)
print("routed", len(PATHS), "paths")
