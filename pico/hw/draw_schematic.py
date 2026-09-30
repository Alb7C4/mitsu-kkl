#!/usr/bin/env python3
"""Draws pico/hw/schemat.svg (K-line interface for the Pico 2 W). Run after changing the circuit:

  python pico/hw/draw_schematic.py

Hand-placed symbols on a 10 px grid; nets that cross panels use labels instead of wires.
"""

from pathlib import Path

OUT = Path(__file__).with_name("schemat.svg")
INK, SOFT, ACCENT, NET = "#1d2330", "#667085", "#1a5fb4", "#9a3412"


class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.el = w, h, []

    def add(self, s):
        self.el.append(s)

    def line(self, *pts, color=INK, width=2, dash=None):
        d = " ".join(f"{x},{y}" for x, y in pts)
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{width}"'
                 f' stroke-linejoin="round" stroke-linecap="round"{extra}/>')

    def text(self, x, y, s, size=13, anchor="start", weight="normal", color=INK, italic=False):
        style = ' font-style="italic"' if italic else ""
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}"'
                 f' fill="{color}"{style}>{s}</text>')

    def dot(self, x, y):
        self.add(f'<circle cx="{x}" cy="{y}" r="4" fill="{INK}"/>')

    def rect(self, x, y, w, h, fill="none", color=INK, width=2, rx=0, dash=None):
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{color}"'
                 f' stroke-width="{width}"{extra}/>')

    # -- symbols -------------------------------------------------------------------------
    def resistor(self, x, y, vertical=False, ref="", value="", side="auto"):
        """Centre (x, y), leads end 30 px from the centre."""
        if vertical:
            self.line((x, y - 30), (x, y - 18))
            self.line((x, y + 18), (x, y + 30))
            self.rect(x - 7, y - 18, 14, 36, fill="#ffffff")
            tx = x + 14 if side != "left" else x - 14
            anchor = "start" if side != "left" else "end"
            self.text(tx, y - 3, ref, 13, anchor, "bold")
            self.text(tx, y + 13, value, 12, anchor, color=SOFT)
        else:
            self.line((x - 30, y), (x - 18, y))
            self.line((x + 18, y), (x + 30, y))
            self.rect(x - 18, y - 7, 36, 14, fill="#ffffff")
            self.text(x, y - 13, ref, 13, "middle", "bold")
            self.text(x, y + 24, value, 12, "middle", color=SOFT)

    def capacitor(self, x, y, ref="", value="", polar=False):
        """Vertical, centre (x, y), leads end 30 px from the centre."""
        self.line((x, y - 30), (x, y - 5))
        self.line((x, y + 5), (x, y + 30))
        self.line((x - 13, y - 5), (x + 13, y - 5), width=3)
        self.line((x - 13, y + 5), (x + 13, y + 5), width=3)
        if polar:
            self.text(x - 16, y - 8, "+", 12, "end")
        self.text(x + 18, y - 3, ref, 13, "start", "bold")
        self.text(x + 18, y + 13, value, 12, "start", color=SOFT)

    def diode(self, x, y, direction="right", ref="", value="", tvs=False):
        """Centre (x, y); anode on the side opposite to `direction`; leads end 30 px from the centre."""
        if direction in ("right", "left"):
            s = 1 if direction == "right" else -1
            self.line((x - 30, y), (x + 30, y))
            self.add(f'<polygon points="{x - 9 * s},{y - 10} {x - 9 * s},{y + 10} {x + 9 * s},{y}" '
                     f'fill="#ffffff" stroke="{INK}" stroke-width="2"/>')
            self.line((x + 9 * s, y - 10), (x + 9 * s, y + 10), width=2.5)
            self.text(x, y - 16, ref, 13, "middle", "bold")
            self.text(x, y + 28, value, 12, "middle", color=SOFT)
        else:  # "up": cathode on top (a clamp from a rail to ground)
            self.line((x, y - 30), (x, y + 30))
            self.add(f'<polygon points="{x - 10},{y + 9} {x + 10},{y + 9} {x},{y - 9}" '
                     f'fill="#ffffff" stroke="{INK}" stroke-width="2"/>')
            self.line((x - 10, y - 9), (x + 10, y - 9), width=2.5)
            if tvs:
                self.line((x - 10, y - 9), (x - 14, y - 14), width=2.5)
                self.line((x + 10, y - 9), (x + 14, y - 4), width=2.5)
            self.text(x + 18, y - 3, ref, 13, "start", "bold")
            self.text(x + 18, y + 13, value, 12, "start", color=SOFT)

    def gnd(self, x, y):
        self.line((x, y), (x, y + 8))
        self.line((x - 12, y + 8), (x + 12, y + 8))
        self.line((x - 7, y + 13), (x + 7, y + 13))
        self.line((x - 3, y + 18), (x + 3, y + 18))

    def npn(self, x, y, ref="", value=""):
        """Base lead from (x-40, y); collector ends at (x+12, y-40), emitter at (x+12, y+40)."""
        self.add(f'<circle cx="{x + 4}" cy="{y}" r="24" fill="#ffffff" stroke="{INK}" stroke-width="2"/>')
        self.line((x - 40, y), (x - 8, y))
        self.line((x - 8, y - 14), (x - 8, y + 14), width=3)
        self.line((x - 8, y - 6), (x + 12, y - 20), (x + 12, y - 40))
        self.line((x - 8, y + 6), (x + 12, y + 20), (x + 12, y + 40))
        self.add(f'<polygon points="{x + 12},{y + 20} {x + 1},{y + 18} {x + 7},{y + 11}" fill="{INK}"/>')
        self.text(x + 34, y - 3, ref, 13, "start", "bold")
        self.text(x + 34, y + 13, value, 12, "start", color=SOFT)

    def comparator(self, x, y, ref="", value=""):
        """Triangle with its left edge at x; + input at (x-20, y-20), - input at (x-20, y+20),
        output at (x+100, y)."""
        self.add(f'<polygon points="{x},{y - 45} {x},{y + 45} {x + 80},{y}" fill="#ffffff" '
                 f'stroke="{INK}" stroke-width="2"/>')
        self.line((x - 20, y - 20), (x, y - 20))
        self.line((x - 20, y + 20), (x, y + 20))
        self.line((x + 80, y), (x + 100, y))
        self.text(x + 7, y - 15, "+", 16, weight="bold")
        self.text(x + 8, y + 26, "−", 16, weight="bold")
        self.text(x + 30, y - 52, ref, 13, "middle", "bold")
        self.text(x + 30, y + 64, value, 12, "middle", color=SOFT)

    def net(self, x, y, name, side="right", color=NET):
        """A net label hanging off (x, y): side = where the label sits relative to the point."""
        w = 7.4 * len(name) + 16
        if side == "right":
            self.rect(x, y - 11, w, 22, fill="#fff7ed", color=color, width=1.5, rx=4)
            self.text(x + w / 2, y + 5, name, 12, "middle", "bold", color)
        elif side == "left":
            self.rect(x - w, y - 11, w, 22, fill="#fff7ed", color=color, width=1.5, rx=4)
            self.text(x - w / 2, y + 5, name, 12, "middle", "bold", color)
        elif side == "up":
            self.rect(x - w / 2, y - 22, w, 22, fill="#fff7ed", color=color, width=1.5, rx=4)
            self.text(x, y - 6, name, 12, "middle", "bold", color)

    def panel(self, x, y, w, h, title):
        self.rect(x, y, w, h, color="#c7ccd4", width=1.5, rx=10)
        self.text(x + 16, y + 26, title, 15, weight="bold", color=ACCENT)

    def note(self, x, y, lines, size=12):
        for i, s in enumerate(lines):
            self.text(x, y + i * (size + 5), s, size, color=SOFT)

    def svg(self):
        body = "\n".join(self.el)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" font-family="Segoe UI, Helvetica, Arial, sans-serif">\n'
                f'<rect width="100%" height="100%" fill="#ffffff"/>\n{body}\n</svg>\n')


def draw():
    s = Svg(1500, 980)
    s.text(24, 36, "mitsu-kkl: interfejs linii K dla Raspberry Pi Pico 2 W", 22, weight="bold")
    s.text(24, 60, "Gniazdo OBD-II ↔ Pico 2 W: zasilanie 12 → 5 V, nadajnik i odbiornik linii K (ISO 9141, "
                   "15625 bd), zwieranie pinu 1 do masy. Etykiety w ramkach łączą te same sieci między panelami.",
           13, color=SOFT)

    # ---- 1. power -----------------------------------------------------------------------
    s.panel(16, 80, 730, 360, "1. Zasilanie z gniazda OBD (pin 16 = +12 V na stałe, piny 4 i 5 = masa)")
    y = 170
    s.net(96, y, "OBD 16", "left")
    s.line((96, y), (110, y))
    s.resistor(140, y, ref="F1", value="PTC 0,5 A")
    s.line((170, y), (190, y))
    s.diode(220, y, "right", "D1", "SS34")
    s.line((250, y), (590, y))
    for x in (280, 340, 420, 500):
        s.dot(x, y)
    s.net(280, y - 34, "+12V_P", "up")
    s.line((280, y - 34), (280, y))
    s.diode(340, y + 60, "up", "D2", "SMBJ24A", tvs=True)
    s.line((340, y), (340, y + 30))
    s.gnd(340, y + 90)
    s.capacitor(420, y + 60, "C1", "47 µF 35 V", polar=True)
    s.line((420, y), (420, y + 30))
    s.gnd(420, y + 90)
    s.capacitor(500, y + 60, "C2", "100 nF")
    s.line((500, y), (500, y + 30))
    s.gnd(500, y + 90)
    s.rect(590, y - 30, 110, 90, fill="#f4f7fb")
    s.text(595, y - 16, "VIN", 10, color=SOFT)
    s.text(695, y - 16, "VOUT", 10, "end", color=SOFT)
    s.text(645, y + 4, "U1", 13, "middle", "bold")
    s.text(645, y + 22, "przetwornica", 12, "middle")
    s.text(645, y + 38, "12 → 5 V", 12, "middle")
    s.text(645, y + 54, "GND", 10, "middle", color=SOFT)
    s.line((645, y + 60), (645, y + 80))
    s.gnd(645, y + 80)
    s.text(640, y + 122, "Pololu D36V6F5 (do 50 V)", 11, "middle", color=SOFT)
    s.line((700, y), (725, y), (725, 340), (690, 340))
    s.dot(725, 250)
    s.net(725, 250, "+5V", "left")
    s.diode(660, 340, "left", "D3", "1N5819")
    s.line((630, 340), (610, 340))
    s.net(610, 340, "Pico VSYS (39)", "left")
    s.net(96, 380, "OBD 4", "left")
    s.net(96, 414, "OBD 5", "left")
    s.line((96, 380), (140, 380), (140, 414), (96, 414))
    s.dot(140, 397)
    s.line((140, 397), (170, 397))
    s.gnd(170, 397)
    s.note(210, 382, ["Masa gniazda (4 = nadwozie, 5 = sygnałowa) = masa całego układu i GND Pico.",
                      "D1 chroni przed odwrotną polaryzacją, D2 tłumi przepięcia, F1 ogranicza zwarcie.",
                      "D3 pozwala mieć jednocześnie podłączony kabel USB do Pico."])

    # ---- 2. K-line transmit ------------------------------------------------------------
    s.panel(762, 80, 722, 360, "2. Linia K: podciągnięcie 510 Ω i nadajnik (BC337)")
    kx = 1080
    s.net(kx, 146, "+12V_P", "up")
    s.resistor(kx, 176, vertical=True, ref="R4", value="510 Ω 0,5 W", side="right")
    s.line((kx, 206), (kx, 250))
    s.dot(kx, 250)
    s.line((kx, 250), (1250, 250))
    s.dot(1250, 250)
    s.net(1400, 250, "OBD 7 (K)", "right")
    s.line((1250, 250), (1400, 250))
    s.dot(1320, 250)
    s.net(1320, 222, "K", "up")
    s.line((1320, 222), (1320, 250))
    s.line((1250, 250), (1250, 300))
    s.diode(1250, 330, "up", "D4", "SMAJ24A", tvs=True)
    s.gnd(1250, 360)
    s.line((kx, 250), (kx, 262))
    s.npn(kx - 12, 302, "Q1", "BC337-40")
    s.gnd(kx, 342)
    s.line((kx - 52, 302), (960, 302))
    s.dot(960, 302)
    s.resistor(930, 302, ref="R1", value="1 kΩ")
    s.line((900, 302), (880, 302))
    s.net(880, 302, "Pico GP0 TX (1)", "left")
    s.line((960, 302), (960, 320))
    s.resistor(960, 350, vertical=True, ref="R2", value="10 kΩ", side="left")
    s.gnd(960, 380)
    s.note(780, 410, ["GP0 = 1 → Q1 przewodzi → linia K = 0 V. Tranzystor odwraca logikę: w config.json invert_tx: true.",
                      "R2 trzyma Q1 wyłączony przy starcie Pico, więc linia K zostaje zwolniona."])

    # ---- 3. K-line receive -------------------------------------------------------------
    s.panel(16, 456, 730, 500, "3. Linia K: odbiornik (komparator LM393, próg ≈ 48% napięcia akumulatora)")
    cx, cy = 400, 640
    s.net(90, cy - 20, "K", "left")
    s.line((90, cy - 20), (120, cy - 20))
    s.resistor(150, cy - 20, ref="R5", value="47 kΩ")
    s.line((180, cy - 20), (cx - 20, cy - 20))
    s.dot(240, cy - 20)
    s.line((240, cy - 20), (240, cy + 60))
    s.resistor(240, cy + 90, vertical=True, ref="R6", value="10 kΩ", side="left")
    s.gnd(240, cy + 120)
    s.net(90, 800, "+12V_P", "left")
    s.line((90, 800), (120, 800))
    s.resistor(150, 800, ref="R7", value="100 kΩ")
    s.line((180, 800), (330, 800))
    s.dot(330, 800)
    s.line((330, 800), (330, cy + 20), (cx - 20, cy + 20))
    s.line((330, 800), (330, 830))
    s.resistor(330, 860, vertical=True, ref="R8", value="9,1 kΩ", side="left")
    s.gnd(330, 890)
    s.comparator(cx, cy, "", "U2A: LM393 (nóżki 1, 2, 3)")
    s.text(cx - 26, cy - 26, "3", 10, "end", color=SOFT)
    s.text(cx - 26, cy + 34, "2", 10, "end", color=SOFT)
    s.text(cx + 94, cy - 6, "1", 10, "end", color=SOFT)
    ox = cx + 150
    s.line((cx + 100, cy), (ox, cy))
    s.dot(ox, cy)
    s.line((ox, cy), (ox, cy - 40))
    s.resistor(ox, cy - 70, vertical=True, ref="R10", value="4,7 kΩ", side="right")
    s.line((ox, cy - 100), (ox, cy - 112))
    s.net(ox, cy - 112, "Pico 3V3 (36)", "up")
    s.line((ox, cy), (690, cy))
    s.net(690, cy, "GP1 RX (2)", "left")
    # hysteresis: output back to the + input, over the comparator
    s.dot(cx + 120, cy)
    s.line((cx + 120, cy), (cx + 120, 550), (cx + 20, 550))
    s.resistor(cx - 10, 550, ref="R9", value="1 MΩ")
    s.line((cx - 40, 550), (270, 550), (270, cy - 20))
    s.dot(270, cy - 20)
    s.text(cx + 112, 566, "histereza", 11, "end", color=SOFT)
    s.rect(560, 760, 170, 110, fill="#f4f7fb", color="#c7ccd4", width=1.5, rx=6)
    s.text(645, 780, "U2 zasilanie", 12, "middle", "bold")
    s.text(645, 798, "8 → +5V, 4 → GND", 12, "middle")
    s.text(645, 816, "C3 100 nF przy nóżce 8", 12, "middle")
    s.text(645, 834, "U2B nieużywany:", 12, "middle")
    s.text(645, 852, "5 → GND, 6 → nóżka 2", 12, "middle")
    s.note(400, 900, ["Wyjście LM393: otwarty kolektor podciągnięty do 3,3 V,",
                      "więc GP1 dostaje najwyżej 3,3 V. Logika bez odwracania",
                      "(invert_rx: false). Wejścia LM393 znoszą do 36 V."])

    # ---- 4. pin 1 + Pico -----------------------------------------------------------------
    s.panel(762, 456, 722, 500, "4. Pin 1 do masy (tryb diagnostyczny) i połączenia z Pico 2 W")
    px = 1000
    s.net(px + 12, 520, "OBD 1", "up")
    s.line((px + 12, 520), (px + 12, 560))
    s.npn(px, 600, "Q2", "BC337-40")
    s.gnd(px + 12, 640)
    s.line((px - 40, 600), (900, 600))
    s.dot(900, 600)
    s.resistor(870, 600, ref="R11", value="1 kΩ")
    s.line((840, 600), (830, 600))
    s.net(830, 600, "GP2 (4)", "left")
    s.line((900, 600), (900, 618))
    s.resistor(900, 648, vertical=True, ref="R12", value="10 kΩ", side="left")
    s.gnd(900, 678)
    s.line((px + 12, 540), (1150, 540), (1150, 570))
    s.dot(px + 12, 540)
    s.line((1150, 570), (1170, 590), dash=None)
    s.line((1150, 600), (1150, 630))
    s.dot(1150, 570)
    s.dot(1150, 600)
    s.gnd(1150, 630)
    s.text(1180, 578, "SW1 (opcja): ręczne", 12, weight="bold")
    s.text(1180, 596, "zwarcie pinu 1", 12, weight="bold")
    s.note(1040, 694, ["GP2 = 1 → Q2 przewodzi → pin 1 na masie (pin1_active_high: true)"])
    # Pico pin table
    tx0, ty0 = 800, 716
    s.rect(tx0, ty0, 660, 226, fill="#f8fafc", color="#c7ccd4", width=1.5, rx=6)
    s.text(tx0 + 16, ty0 + 24, "Raspberry Pi Pico 2 W", 14, weight="bold")
    rows = [("GP0 (nóżka 1)", "UART0 TX → R1 → Q1 (nadawanie na linię K)"),
            ("GP1 (nóżka 2)", "UART0 RX ← wyjście U2A (odbiór z linii K)"),
            ("GP2 (nóżka 4)", "R11 → Q2 (pin 1 OBD do masy)"),
            ("3V3 OUT (nóżka 36)", "podciągnięcie R10"),
            ("VSYS (nóżka 39)", "+5V przez D3"),
            ("GND (nóżki 3, 38)", "masa układu = OBD 4 i 5")]
    for i, (pin, what) in enumerate(rows):
        yy = ty0 + 52 + i * 26
        s.text(tx0 + 16, yy, pin, 13, weight="bold", color=ACCENT)
        s.text(tx0 + 190, yy, what, 13)
    s.text(tx0 + 16, ty0 + 212, 'config.json: "invert_tx": true, "invert_rx": false, "pin1_gpio": 2, '
                                '"pin1_active_high": true', 12, color=SOFT)
    return s


if __name__ == "__main__":
    OUT.write_text(draw().svg(), encoding="utf-8")
    print("written", OUT)
