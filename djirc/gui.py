"""Skeuomorphic Tk GUI for the DJI RC-N1/N3 controller tester.

`run_gui(reader)` renders a controller-shaped window and refreshes it ~30x/s from
a reader object exposing: latest (0x01 stick bytes | None), aux (0x27 button bytes
| None), battery (int | None), count (int), status (str), connected (bool), and a
stop() method.
"""
import math
import time
import tkinter as tk

from . import protocol as dji

PACKET_LEN = dji.STICK_LEN
AUX_LEN = dji.AUX_LEN

# Button bitfield (byte 29 of the 0x27 packet) with display labels.
BUTTON_BITS = [
    (29, 0x02, "Fn"),
    (29, 0x04, "Photo/Video"),
    (29, 0x60, "Shutter/Record"),
    (29, 0x80, "Return to home"),
]
# Flight-mode switch (byte 28 of the 0x27 packet) with display names.
VALUE_FIELDS = [(28, "Flight mode", {0x00: "Sport", 0x10: "Normal", 0x20: "Cinematic"})]


def run_gui(reader):
    """Draw the controller-style Tk window and refresh it from `reader` state."""
    WIN = "#eef0f2"
    BODY, BODY_EDGE, BODY_HI, BODY_LO = "#b9bcc0", "#8a8d92", "#c9cbce", "#9a9da2"
    SHOULDER, HUMP = "#41454a", "#2c2f33"
    SOCKET, RECESS, KNOB, KNOB_EDGE, GLOSS = "#9a9ea4", "#8a8e94", "#33363b", "#5c6067", "#4a4e54"
    BTN, BTN_EDGE = "#a6a9ae", "#8a8d92"
    ORANGE, TEXT_D, WHITE, DIM = "#ec6b2d", "#33363b", "#f4f5f6", "#6f7276"
    KR, TRAVEL = 38, 20

    root = tk.Tk()
    root.title("DJI RC-N1/N3 Controller Test")
    root.configure(bg=WIN)
    root.minsize(780, 640)

    status = tk.Canvas(root, height=28, bg=WIN, highlightthickness=0)
    status.pack(fill="x", padx=16, pady=(10, 0))
    status_dot = status.create_oval(2, 9, 16, 23, fill="#d24b3a", outline="")
    status_text = status.create_text(24, 16, anchor="w", fill=TEXT_D,
                                     font=("Segoe UI", 11, "bold"), text="Connecting...")
    rate_text = status.create_text(740, 16, anchor="e", fill=DIM,
                                   font=("Segoe UI", 10), text="")
    status.bind("<Configure>", lambda e: status.coords(rate_text, e.width - 6, 16))

    cc = tk.Canvas(root, width=740, height=520, bg=WIN, highlightthickness=0)
    cc.pack(padx=8)

    def rr(x0, y0, x1, y1, r, **kw):
        """Draw a rounded rectangle as a smoothed polygon on the controller canvas."""
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return cc.create_polygon(pts, smooth=True, **kw)

    # Body (~1.5:1) + subtle bevel.
    rr(30, 40, 710, 490, 54, fill=BODY, outline=BODY_EDGE, width=2)
    cc.create_line(90, 44, 650, 44, fill=BODY_HI, width=3)
    cc.create_line(90, 484, 650, 484, fill=BODY_LO, width=3)

    # Top folds.
    cc.create_polygon(140, 28, 320, 28, 302, 72, 158, 72, fill=SHOULDER, outline="")
    rec_id = cc.create_polygon(420, 28, 600, 28, 582, 72, 438, 72,
                               fill=SHOULDER, outline="")   # Shutter/Record trigger
    for hx0, hx1, sx0, sx1 in ((142, 318, 159, 301), (422, 598, 439, 581)):
        cc.create_line(hx0, 30, hx1, 30, fill="#565b61", width=2)
        cc.create_line(sx0, 71, sx1, 71, fill="#22252a", width=2)
    rec_txt = cc.create_text(510, 48, fill=WHITE, font=("Segoe UI", 9, "bold"), text="REC")

    # Center phone clamp / USB holder, integrated into the top edge.
    rr(335, 24, 405, 76, 10, fill=HUMP, outline="")
    cc.create_line(358, 32, 382, 32, fill="#5a5e64", width=3)
    cc.create_rectangle(364, 76, 376, 86, fill=HUMP, outline="")

    # Zoom ribbed wheel on the left fold.
    rr(195, 38, 275, 58, 7, fill=HUMP, outline="")
    for x in range(205, 270, 8):
        cc.create_line(x, 42, x, 54, fill="#4a4e54", width=1)
    dial_marker = cc.create_line(235, 40, 235, 56, fill=ORANGE, width=3)
    cc.create_text(235, 88, fill=DIM, font=("Segoe UI", 8), text="zoom")

    # Fn + Photo/Video (top corners).
    fn_id = rr(44, 118, 108, 152, 15, fill=BTN, outline=BTN_EDGE)
    fn_txt = cc.create_text(76, 135, fill=TEXT_D, font=("Segoe UI", 10, "bold"), text="Fn")
    pv_id = rr(632, 118, 696, 152, 15, fill=BTN, outline=BTN_EDGE)
    pv_txt = cc.create_text(664, 135, fill=TEXT_D, font=("Segoe UI", 10, "bold"), text="P/V")

    # Sticks (upper third) with recess, center reference, knob + gloss.
    def stick(cx, cy):
        """Draw a stick socket + center reference and return its (knob, gloss) ids."""
        cc.create_oval(cx - 58, cy - 58, cx + 58, cy + 58, fill=SOCKET, outline=BODY_EDGE, width=2)
        cc.create_oval(cx - 48, cy - 48, cx + 48, cy + 48, fill=RECESS, outline="")
        cc.create_oval(cx - 28, cy - 28, cx + 28, cy + 28, outline="#8a8e94", dash=(2, 4))
        cc.create_line(cx - 9, cy, cx + 9, cy, fill="#8a8e94")
        cc.create_line(cx, cy - 9, cx, cy + 9, fill="#8a8e94")
        kid = cc.create_oval(cx - KR, cy - KR, cx + KR, cy + KR, fill=KNOB, outline=KNOB_EDGE, width=3)
        gid = cc.create_oval(cx - 22, cy - 22, cx - 6, cy - 6, fill=GLOSS, outline="")
        return kid, gid

    left_knob = stick(215, 175)
    right_knob = stick(525, 175)
    cc.create_text(215, 250, fill=TEXT_D, font=("Segoe UI", 9, "bold"), text="Left stick")
    cc.create_text(215, 266, fill=DIM, font=("Segoe UI", 8),
                   text="\u25b2\u25bc Throttle    \u25c0\u25b6 Yaw")
    left_val = cc.create_text(215, 282, fill=DIM, font=("Consolas", 8), text="0, 0")
    cc.create_text(525, 250, fill=TEXT_D, font=("Segoe UI", 9, "bold"), text="Right stick")
    cc.create_text(525, 266, fill=DIM, font=("Segoe UI", 8),
                   text="\u25b2\u25bc Pitch    \u25c0\u25b6 Roll")
    right_val = cc.create_text(525, 282, fill=DIM, font=("Consolas", 8), text="0, 0")

    # Lower button cluster.
    rth_id = cc.create_oval(274, 324, 326, 376, fill=BTN, outline=BTN_EDGE, width=2)
    cc.create_rectangle(294, 335, 298, 365, fill=ORANGE, outline="")
    cc.create_rectangle(302, 335, 306, 365, fill=ORANGE, outline="")

    rr(338, 338, 412, 362, 11, fill=HUMP, outline="")
    mode_marker = cc.create_rectangle(368, 340, 382, 360, fill=ORANGE, outline="")
    mode_letters = {}
    for nm, lx, lab in (("Cinematic", 357, "C"), ("Normal", 375, "N"), ("Sport", 393, "S")):
        mode_letters[nm] = cc.create_text(lx, 326, fill=DIM, font=("Segoe UI", 9, "bold"), text=lab)
    MODE_X = {"Cinematic": 357, "Normal": 375, "Sport": 393}

    cc.create_oval(424, 324, 476, 376, fill=BTN, outline=BTN_EDGE, width=2)
    cc.create_arc(440, 340, 460, 360, start=115, extent=310, style="arc", outline=TEXT_D, width=2)
    cc.create_line(450, 336, 450, 350, fill=TEXT_D, width=2)

    # Battery LEDs (lower face).
    battery_leds = []
    for i in range(4):
        x = 350 + i * 16
        battery_leds.append(cc.create_oval(x, 408, x + 8, 416, fill="#8a8d92", outline=""))
    battery_text = cc.create_text(374, 432, fill=DIM, font=("Segoe UI", 8), text="Battery: --")

    button_shapes = {
        "Fn": (fn_id, fn_txt),
        "Photo/Video": (pv_id, pv_txt),
        "Shutter/Record": (rec_id, rec_txt),
        "Return to home": (rth_id, None),
    }
    mode_off, _mname, mode_map = VALUE_FIELDS[0]

    # Developer panel (collapsible, hidden by default).
    baseline = {"aux": None}
    dev_shown = {"v": False}
    dev_bar = tk.Frame(root, bg=WIN)
    dev_bar.pack(fill="x", padx=16)
    dev_frame = tk.Frame(root, bg=WIN)
    cells = []
    grid = tk.Frame(dev_frame, bg=WIN)
    grid.pack(padx=4, pady=6, anchor="w")
    for i in range(AUX_LEN):
        cell = tk.Label(grid, text=f"{i:02d}\n--", width=4, height=2, relief="solid",
                        borderwidth=1, font=("Consolas", 9), bg="#dfe1e4", fg="#333")
        cell.grid(row=(i // 10) * 2, column=i % 10, padx=1, pady=1)
        cells.append(cell)

    def set_baseline():
        if reader.aux is not None:
            baseline["aux"] = reader.aux

    tk.Button(dev_frame, text="Set baseline", command=set_baseline, bg=BODY, fg=TEXT_D,
              relief="flat", padx=8).pack(anchor="w", padx=4, pady=(0, 6))

    def toggle_dev():
        dev_shown["v"] = not dev_shown["v"]
        if dev_shown["v"]:
            dev_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
            dev_btn.config(text="\u25be  Developer / raw packet (0x27)")
        else:
            dev_frame.pack_forget()
            dev_btn.config(text="\u25b8  Developer / raw packet (0x27)")

    dev_btn = tk.Button(dev_bar, text="\u25b8  Developer / raw packet (0x27)",
                        command=toggle_dev, bg=WIN, fg=DIM, relief="flat", anchor="w",
                        font=("Segoe UI", 9))
    dev_btn.pack(fill="x", pady=4)

    rate = {"count": 0, "t": 0.0}

    def set_knob(pair, cx, cy, vx, vy):
        """Move a stick knob (and its gloss) to the axis position, clamped to the socket."""
        kid, gid = pair
        fx, fy = vx / 32768.0, vy / 32768.0
        mag = math.hypot(fx, fy)
        if mag > 1.0:
            fx, fy = fx / mag, fy / mag
        x, y = cx + fx * TRAVEL, cy - fy * TRAVEL
        cc.coords(kid, x - KR, y - KR, x + KR, y + KR)
        cc.coords(gid, x - 22, y - 22, x - 6, y - 6)

    def update():
        """Refresh every widget from the reader ~30x/s and reschedule itself."""
        status.itemconfig(status_text, text=reader.status)
        status.itemconfig(status_dot, fill="#3fb463" if reader.connected else "#d24b3a")
        pct = reader.battery
        if reader.connected and pct is not None:
            cc.itemconfig(battery_text, text=f"Battery: {pct}%")
            lit = round(pct / 25)
        else:
            cc.itemconfig(battery_text, text="Battery: --")
            lit = 0
        for i, lid in enumerate(battery_leds):
            cc.itemconfig(lid, fill="#3fb463" if i < lit else "#8a8d92")
        now = time.time()
        if now - rate["t"] >= 0.5:
            rps = (reader.count - rate["count"]) / max(now - rate["t"], 1e-3)
            status.itemconfig(rate_text, text=f"{reader.count} pkts   {rps:4.0f}/s")
            rate["count"], rate["t"] = reader.count, now

        sticks = reader.latest
        if sticks is not None and len(sticks) == PACKET_LEN:
            lx, ly = dji.parse_input(sticks[22:24]), dji.parse_input(sticks[19:21])
            rx, ry = dji.parse_input(sticks[13:15]), dji.parse_input(sticks[16:18])
            set_knob(left_knob, 215, 175, lx, ly)
            set_knob(right_knob, 525, 175, rx, ry)
            cc.itemconfig(left_val, text=f"{lx:+d}, {ly:+d}")
            cc.itemconfig(right_val, text=f"{rx:+d}, {ry:+d}")
            frac = max(-1.0, min(1.0, dji.parse_input(sticks[25:27]) / 32768.0))
            mx = 235 + frac * 32
            cc.coords(dial_marker, mx, 40, mx, 56)
        else:
            set_knob(left_knob, 215, 175, 0, 0)
            set_knob(right_knob, 525, 175, 0, 0)
            cc.itemconfig(left_val, text="0, 0")
            cc.itemconfig(right_val, text="0, 0")
            cc.coords(dial_marker, 235, 40, 235, 56)

        aux = reader.aux
        if aux is not None and len(aux) == AUX_LEN:
            if baseline["aux"] is None:
                baseline["aux"] = aux
            base = baseline["aux"]
            for off, mask, bname in BUTTON_BITS:
                on = off < len(aux) and (aux[off] & mask) != 0
                shape, txt = button_shapes[bname]
                idle = SHOULDER if bname == "Shutter/Record" else BTN
                cc.itemconfig(shape, fill=(ORANGE if on else idle))
                if txt is not None:
                    idle_fg = WHITE if bname == "Shutter/Record" else TEXT_D
                    cc.itemconfig(txt, fill=(WHITE if on else idle_fg))
            cur = mode_map.get(aux[mode_off]) if mode_off < len(aux) else None
            if cur in MODE_X:
                mx = MODE_X[cur]
                cc.coords(mode_marker, mx - 7, 340, mx + 7, 360)
            for nm, tid in mode_letters.items():
                cc.itemconfig(tid, fill=(ORANGE if nm == cur else DIM))
            if dev_shown["v"]:
                for i, cell in enumerate(cells):
                    b = aux[i]
                    changed = b != base[i]
                    cell.config(text=f"{i:02d}\n{b:02X}",
                                bg="#f7c9a8" if changed else "#dfe1e4",
                                fg="#a0430f" if changed else "#333")
        root.after(33, update)

    def on_close():
        reader.stop()
        root.after(150, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    update()
    root.mainloop()
