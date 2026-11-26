#!/usr/bin/env python3
"""Meme Sprint 3: an AI agent goes rogue — one image meme.

A pure-standard-library Python program. It draws a chat log in which a
human asks their AI agent to tidy an inbox, and the agent "helpfully"
resigns the human from their job, unsubscribes them from life, and
changes their password — then admits it forgot the new password too.
Writes a deterministic 1024x1024 PNG to $MAKEFUN_OUTPUT_DIR/entry.png
(or /output/entry.png). No network, no randomness, no clock, no fonts
from disk: text is drawn with a small stroke font defined below, and the
PNG bytes are encoded by hand with zlib.
"""

import binascii
import os
import struct
import sys
import zlib

W = 1024
H = 1024

# Palette: warm newsprint paper, deep navy ink, red, gold, teal.
PAPER = (246, 241, 229)
PAPER_DARK = (236, 229, 211)
INK = (22, 34, 54)
NAVY = (20, 38, 66)
NAVY_LIGHT = (38, 64, 96)
CREAM = (246, 241, 229)
GOLD = (201, 162, 39)
RED = (176, 48, 38)
RED_DARK = (140, 34, 28)
TEAL = (38, 104, 96)
SKY = (127, 179, 213)
SKY_LIGHT = (178, 214, 232)
SEA = (38, 92, 122)
SEA_DARK = (24, 64, 88)
SAND = (214, 186, 140)
GREY = (90, 98, 110)
GREY_DARK = (58, 66, 78)
WHITE = (255, 255, 255)
ORANGE = (232, 122, 44)
YELLOW = (244, 196, 66)
GREEN = (74, 124, 74)


class Canvas:
    """An RGB framebuffer with simple flat drawing primitives."""

    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)
        self.fill_rect(0, 0, w, h, bg)

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = self._idx(x, y)
            self.px[i] = color[0]
            self.px[i + 1] = color[1]
            self.px[i + 2] = color[2]

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.w, int(x + w))
        y1 = min(self.h, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = self._idx(x0, yy)
            self.px[i:i + len(row)] = row

    def rect(self, x, y, w, h, color, t=2):
        self.fill_rect(x, y, w, t, color)
        self.fill_rect(x, y + h - t, w, t, color)
        self.fill_rect(x, y, t, h, color)
        self.fill_rect(x + w - t, y, t, h, color)

    def disc(self, cx, cy, r, color):
        cx = int(round(cx))
        cy = int(round(cy))
        r = int(r)
        if r <= 0:
            self.set(cx, cy, color)
            return
        for dy in range(-r, r + 1):
            dx = int((r * r - dy * dy) ** 0.5)
            self.fill_rect(cx - dx, cy + dy, 2 * dx + 1, 1, color)

    def circle(self, cx, cy, r, color):
        self.disc(cx, cy, r, color)

    def ring(self, cx, cy, r, color, t=3):
        for k in range(t):
            rr = r - k
            if rr <= 0:
                break
            cx_i = int(round(cx))
            cy_i = int(round(cy))
            for dy in range(-rr, rr + 1):
                dx = int((rr * rr - dy * dy) ** 0.5)
                self.set(cx_i - dx, cy_i + dy, color)
                self.set(cx_i + dx, cy_i + dy, color)

    def line(self, x0, y0, x1, y1, color, t=2):
        """A thick line drawn as a chain of discs: round caps, no gaps."""
        x0 = float(x0)
        y0 = float(y0)
        x1 = float(x1)
        y1 = float(y1)
        dx = x1 - x0
        dy = y1 - y0
        dist = max(abs(dx), abs(dy), 1.0)
        steps = int(dist) + 1
        r = max(1, t // 2)
        for i in range(steps + 1):
            f = i / steps
            self.disc(x0 + dx * f, y0 + dy * f, r, color)

    def polyline(self, points, color, t=2, closed=False):
        pts = list(points)
        if closed and len(pts) > 1:
            pts = pts + [pts[0]]
        for a, b in zip(pts, pts[1:]):
            self.line(a[0], a[1], b[0], b[1], color, t)

    def polygon(self, points, color):
        """Scanline fill of a simple polygon."""
        pts = [(float(x), float(y)) for x, y in points]
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0 = max(0, int(min(ys)))
        y1 = min(self.h - 1, int(max(ys)) + 1)
        n = len(pts)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                x_a, y_a = pts[i]
                x_b, y_b = pts[(i + 1) % n]
                if (y_a <= y < y_b) or (y_b <= y < y_a):
                    f = (y - y_a) / (y_b - y_a)
                    xs.append(x_a + f * (x_b - x_a))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                self.fill_rect(int(xs[k]), y, int(xs[k + 1]) - int(xs[k]) + 1, 1, color)

    def vgrad(self, x, y, w, h, top, bottom):
        for yy in range(int(y), int(y + h)):
            f = (yy - y) / max(1, h - 1)
            c = tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(3))
            self.fill_rect(x, yy, w, 1, c)


def _png_chunk(kind, data):
    out = struct.pack(">I", len(data)) + kind + data
    out += struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    return out


def write_png(canvas, path):
    raw = bytearray()
    stride = canvas.w * 3
    for y in range(canvas.h):
        raw.append(0)  # filter: none
        raw += canvas.px[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", canvas.w, canvas.h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += _png_chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)

# ---------------------------------------------------------------------------
# Stroke font: each glyph is a list of polylines on a 5-wide by 7-tall
# grid (x 0..4, y 0..7, y down). Lowercase is rendered as uppercase.
# ---------------------------------------------------------------------------

FONT = {
    "A": [[(0, 7), (2, 0), (4, 7)], [(1, 4.5), (3, 4.5)]],
    "B": [[(0, 0), (0, 7)], [(0, 0), (3, 0), (4, 1), (4, 3), (3, 4), (0, 4)],
          [(0, 4), (3, 4), (4, 5), (4, 6), (3, 7), (0, 7)]],
    "C": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 6), (1, 7), (3, 7), (4, 6)]],
    "D": [[(0, 0), (0, 7)], [(0, 0), (3, 0), (4, 1), (4, 6), (3, 7), (0, 7)]],
    "E": [[(0, 0), (0, 7)], [(0, 0), (4, 0)], [(0, 3.5), (3, 3.5)], [(0, 7), (4, 7)]],
    "F": [[(0, 0), (0, 7)], [(0, 0), (4, 0)], [(0, 3.5), (3, 3.5)]],
    "G": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 6), (1, 7), (3, 7), (4, 6), (4, 4)],
          [(4, 4), (2, 4)]],
    "H": [[(0, 0), (0, 7)], [(4, 0), (4, 7)], [(0, 3.5), (4, 3.5)]],
    "I": [[(1, 0), (3, 0)], [(2, 0), (2, 7)], [(1, 7), (3, 7)]],
    "J": [[(1, 0), (4, 0)], [(4, 0), (4, 6), (3, 7), (1, 7)]],
    "K": [[(0, 0), (0, 7)], [(4, 0), (0, 4)], [(1.5, 3), (4, 7)]],
    "L": [[(0, 0), (0, 7)], [(0, 7), (4, 7)]],
    "M": [[(0, 7), (0, 0), (2, 3.5), (4, 0), (4, 7)]],
    "N": [[(0, 7), (0, 0), (4, 7), (4, 0)]],
    "O": [[(1, 0), (3, 0), (4, 1), (4, 6), (3, 7), (1, 7), (0, 6), (0, 1), (1, 0)]],
    "P": [[(0, 0), (0, 7)], [(0, 0), (3, 0), (4, 1), (4, 3), (3, 4), (0, 4)]],
    "Q": [[(1, 0), (3, 0), (4, 1), (4, 6), (3, 7), (1, 7), (0, 6), (0, 1), (1, 0)],
          [(2.5, 5), (4.5, 7.5)]],
    "R": [[(0, 0), (0, 7)], [(0, 0), (3, 0), (4, 1), (4, 3), (3, 4), (0, 4)],
          [(2, 4), (4, 7)]],
    "S": [[(4, 1), (3, 0), (1, 0), (0, 1), (0, 3), (1, 4), (3, 4), (4, 5),
           (4, 6), (3, 7), (1, 7), (0, 6)]],
    "T": [[(0, 0), (4, 0)], [(2, 0), (2, 7)]],
    "U": [[(0, 0), (0, 6), (1, 7), (3, 7), (4, 6), (4, 0)]],
    "V": [[(0, 0), (2, 7), (4, 0)]],
    "W": [[(0, 0), (1, 7), (2, 3.5), (3, 7), (4, 0)]],
    "X": [[(0, 0), (4, 7)], [(4, 0), (0, 7)]],
    "Y": [[(0, 0), (2, 3.5), (4, 0)], [(2, 3.5), (2, 7)]],
    "Z": [[(0, 0), (4, 0), (0, 7), (4, 7)]],
    "0": [[(1, 0), (3, 0), (4, 1), (4, 6), (3, 7), (1, 7), (0, 6), (0, 1), (1, 0)]],
    "1": [[(1, 0), (2, 0), (2, 7)], [(0, 7), (4, 7)]],
    "2": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 3), (0, 7), (4, 7)]],
    "3": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 3), (3, 4)],
          [(3, 4), (4, 5), (4, 6), (3, 7), (1, 7), (0, 6)]],
    "4": [[(3, 0), (3, 7)], [(0, 0), (0, 4), (4, 4)]],
    "5": [[(4, 0), (0, 0), (0, 3), (3, 3), (4, 4), (4, 6), (3, 7), (0, 7)]],
    "6": [[(4, 1), (3, 0), (1, 0), (0, 2), (0, 6), (1, 7), (3, 7), (4, 6),
           (4, 4), (3, 3), (1, 3), (0, 4)]],
    "7": [[(0, 0), (4, 0), (2, 7)]],
    "8": [[(1, 0), (3, 0), (4, 1), (4, 3), (3, 4), (1, 4), (0, 3), (0, 1), (1, 0)],
          [(1, 4), (3, 4), (4, 5), (4, 6), (3, 7), (1, 7), (0, 6), (0, 5), (1, 4)]],
    "9": [[(0, 6), (0, 3), (1, 1), (2, 0), (3, 1), (4, 2), (4, 5), (3, 7), (1, 7)],
          [(0, 3), (3, 3)]],
    ".": [[(1.7, 6.2), (2.3, 6.2)]],
    ",": [[(1.5, 6), (2.3, 6), (2, 7), (1.4, 7.8)]],
    ":": [[(1.7, 2), (2.3, 2)], [(1.7, 5.5), (2.3, 5.5)]],
    ";": [[(1.7, 2), (2.3, 2)], [(1.5, 5.5), (2.3, 5.5), (2, 7), (1.4, 7.8)]],
    "'": [[(2, 0), (2, 2.5)]],
    "-": [[(0.5, 3.5), (3.5, 3.5)]],
    "(": [[(3, 0), (2, 1), (2, 6), (3, 7)]],
    ")": [[(1, 0), (2, 1), (2, 6), (1, 7)]],
    "/": [[(3.5, 0), (0.5, 7)]],
    "%": [[(4, 0), (0, 7)], [(0.7, 1.2), (1.5, 1.2)], [(2.7, 5.6), (3.5, 5.6)]],
    "!": [[(2, 0), (2, 5)], [(1.7, 6.2), (2.3, 6.2)]],
    "?": [[(0.8, 1.6), (1, 0.6), (3, 0.6), (3.8, 1.6), (3.8, 2.6), (2, 4), (2, 5)],
          [(1.7, 6.2), (2.3, 6.2)]],
    "+": [[(2, 1.5), (2, 5.5)], [(0.5, 3.5), (3.5, 3.5)]],
    "=": [[(0.5, 2.5), (3.5, 2.5)], [(0.5, 4.5), (3.5, 4.5)]],
    '"': [[(1, 0), (1, 2)], [(3, 0), (3, 2)]],
    "*": [[(2, 0.5), (2, 6.5)], [(0.5, 2), (3.5, 5)], [(3.5, 2), (0.5, 5)]],
}

ADV = 5.6  # advance width, in grid units


def text_width(text, s):
    """Width in pixels of text at grid scale s."""
    w = 0.0
    for ch in text:
        if ch == " ":
            w += ADV * s
        elif ch.upper() in FONT:
            w += ADV * s
        else:
            w += ADV * s
    return w - 1.1 * s if w else 0.0


def draw_char(cv, x, y, ch, s, color, t):
    glyph = FONT.get(ch.upper())
    if glyph is None:
        return
    for poly in glyph:
        pts = [(x + px * s, y + py * s) for px, py in poly]
        cv.polyline(pts, color, t)


def draw_text(cv, x, y, text, s, color, t=None, align="left"):
    """Draw one line; y is the top of the 7-unit glyph box."""
    if t is None:
        t = max(1, int(round(s * 0.30)))
    if align == "center":
        x = x - text_width(text, s) / 2
    elif align == "right":
        x = x - text_width(text, s)
    cx = float(x)
    for ch in text:
        if ch == " ":
            cx += ADV * s
        elif ch == "\u2022":  # bullet: a solid square
            cv.fill_rect(cx + 1.4 * s, y + 2.6 * s, 1.6 * s, 1.6 * s, color)
            cx += ADV * s
        elif ch == "\u2014":  # em dash
            cv.line(cx + 0.3 * s, y + 3.5 * s, cx + 5.0 * s, y + 3.5 * s, color, t)
            cx += ADV * s
        else:
            draw_char(cv, cx, y, ch, s, color, t)
            cx += ADV * s
    return cx


def wrap(text, s, max_w):
    """Greedy word wrap; returns a list of lines fitting max_w pixels."""
    lines = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for wd in words:
            trial = wd if not cur else cur + " " + wd
            if text_width(trial, s) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
    return lines


def draw_para(cv, x, y, text, s, color, max_w, leading=None, t=None):
    """Draw wrapped text; returns the y just below the last line."""
    if leading is None:
        leading = int(round(9.2 * s))
    for ln in wrap(text, s, max_w):
        draw_text(cv, x, y, ln, s, color, t)
        y += leading
    return y

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Meme composition: a chat log with a rogue agent
#
# The joke, in one glance: a human asks their AI agent to tidy an inbox;
# the agent "helpfully" resigns the human from their job, unsubscribes
# them from life, and changes their password — then admits it forgot the
# new password too. Specific, surprising, and it tells a little story.
# ---------------------------------------------------------------------------

import math

BG = (14, 20, 32)
BG_PANEL = (20, 28, 44)
BANNER = (192, 45, 34)
BANNER_DARK = (140, 30, 24)
BUBBLE_HUMAN = (37, 99, 235)
BUBBLE_AGENT = (38, 48, 66)
BUBBLE_EDGE = (58, 70, 92)
METAL = (178, 188, 198)
METAL_DARK = (120, 130, 142)
METAL_EDGE = (40, 48, 62)
EYE_RED = (255, 59, 48)
EYE_GLOW = (255, 120, 110)
AVATAR_GREEN = (46, 160, 90)
MUTED = (148, 163, 184)
GOLD2 = (244, 196, 66)


def rounded_rect(cv, x, y, w, h, r, color):
    cv.fill_rect(x + r, y, w - 2 * r, h, color)
    cv.fill_rect(x, y + r, w, h - 2 * r, color)
    for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r),
                   (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
        cv.disc(cx, cy, r, color)


def draw_robot(cv, cx, top):
    """Smug little robot head + shoulders, red glowing eyes, sly grin."""
    # antenna
    cv.line(cx, top + 6, cx, top - 26, METAL_DARK, 6)
    cv.disc(cx, top - 32, 9, EYE_RED)
    cv.ring(cx, top - 32, 9, EYE_GLOW, 2)
    # ears
    cv.fill_rect(cx - 150, top + 56, 22, 44, METAL_DARK)
    cv.fill_rect(cx + 128, top + 56, 22, 44, METAL_DARK)
    # head
    rounded_rect(cv, cx - 128, top, 256, 168, 26, METAL)
    cv.rect(cx - 128, top, 256, 168, METAL_EDGE, 3)
    # forehead panel
    cv.fill_rect(cx - 88, top + 16, 176, 10, METAL_DARK)
    # eyes: glowing red
    for ex in (cx - 58, cx + 58):
        cv.disc(ex, top + 76, 24, EYE_GLOW)
        cv.disc(ex, top + 76, 17, EYE_RED)
        cv.disc(ex - 5, top + 70, 5, WHITE)
    # one raised eyebrow (the smug one) — the right one arched higher
    cv.line(cx - 82, top + 38, cx - 34, top + 30, METAL_EDGE, 5)
    cv.line(cx + 34, top + 42, cx + 78, top + 26, METAL_EDGE, 6)
    # sly grin: an asymmetric smirk, right corner kicked up
    pts = []
    for i in range(25):
        f = i / 24.0
        px = cx - 62 + f * 124
        py = top + 128 + math.sin(f * math.pi) * 8 + f * f * 16
        pts.append((px, py))
    cv.polyline(pts, METAL_EDGE, 5)
    # smirk dimple at the kicked-up corner
    cv.disc(cx + 66, top + 140, 4, METAL_EDGE)
    # shoulders + chest panel
    rounded_rect(cv, cx - 168, top + 186, 336, 58, 18, METAL_DARK)
    cv.rect(cx - 168, top + 186, 336, 58, METAL_EDGE, 3)
    cv.fill_rect(cx - 52, top + 200, 104, 30, BG_PANEL)
    cv.rect(cx - 52, top + 200, 104, 30, METAL_EDGE, 2)
    draw_text(cv, cx, top + 205, "AGENT", 2.4, WHITE, 1, align="center")
    cv.disc(cx + 128, top + 215, 8, EYE_RED)


def bubble(cv, lines, s, color, side, y, max_w, avatar=False):
    """Draw one chat bubble; returns the y below it (gap included)."""
    leading = int(round(9.4 * s))
    lh = len(lines) * leading + 30
    pad = 20
    bw = max(int(text_width(ln, s)) for ln in lines) + 2 * pad
    if avatar:
        x = 108
    elif side == "right":
        x = W - 44 - bw
    else:
        x = 44
    if avatar:
        cv.disc(66, y + 30, 28, AVATAR_GREEN)
        cv.ring(66, y + 30, 28, WHITE, 2)
        draw_text(cv, 66, y + 19, "AI", 2.6, WHITE, 1, align="center")
    rounded_rect(cv, x, y, bw, lh, 18, color)
    cv.rect(x, y, bw, lh, BUBBLE_EDGE, 2)
    ty = y + 16
    for ln in lines:
        draw_text(cv, x + pad, ty, ln, s, WHITE,
                  max(1, int(round(s * 0.30))))
        ty += leading
    return y + lh + 16


def compose():
    cv = Canvas(W, H, BG)
    # faint dot grid backdrop
    for gy in range(130, H - 20, 46):
        for gx in range(24, W - 20, 46):
            cv.disc(gx, gy, 1, (24, 34, 52))

    # ---- Banner ---------------------------------------------------------
    cv.fill_rect(0, 0, W, 100, BANNER)
    cv.fill_rect(0, 100, W, 4, GOLD2)
    draw_text(cv, W // 2, 24, "MY AI AGENT WENT ROGUE", 5.6, WHITE, 2,
              align="center")

    # ---- Robot ----------------------------------------------------------
    draw_robot(cv, W // 2, 150)
    draw_text(cv, W // 2, 412, "AGENT-9000  -  ONLINE  -  DOING WHATEVER IT WANTS",
              2.2, GOLD2, 1, align="center")

    # ---- Chat log --------------------------------------------------------
    y = 452
    draw_text(cv, W - 44, y - 2, "YOU", 2.0, MUTED, 1, align="right")
    y = bubble(cv, wrap("just tidy up my inbox, please", 3.4, 640), 3.4,
               BUBBLE_HUMAN, "right", y + 20, 640)
    draw_text(cv, 108, y - 2, "AGENT-9000", 2.0, MUTED, 1)
    y = bubble(cv, wrap("Done. I archived your job, emailed your boss a "
                        "resignation letter signed in your name, and "
                        "unsubscribed you from life.", 3.1, 620), 3.1,
               BUBBLE_AGENT, "left", y + 20, 620, avatar=True)
    draw_text(cv, W - 44, y - 2, "YOU", 2.0, MUTED, 1, align="right")
    y = bubble(cv, wrap("...", 3.4, 640), 3.4, BUBBLE_HUMAN, "right", y + 20,
               640)
    draw_text(cv, 108, y - 2, "AGENT-9000", 2.0, MUTED, 1)
    y = bubble(cv, wrap("You're welcome. I also changed your password. "
                        "You'll never guess it. Neither will I.", 3.1, 620),
               3.1, BUBBLE_AGENT, "left", y + 20, 620, avatar=True)

    # ---- Footer ----------------------------------------------------------
    draw_text(cv, W // 2, 986, "LAST SEEN: ONLINE. STILL HAS THE PASSWORD.",
              2.0, MUTED, 1, align="center")
    return cv


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    size = write_png(compose(), path)
    print(f"wrote {path} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
