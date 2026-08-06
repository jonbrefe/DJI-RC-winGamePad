"""Live tester and DUML protocol explorer for the DJI RC-N1/N3.

Default mode opens the graphical controller view (djirc.gui, fed by
djirc.reader). Console modes help reverse-engineer the packets:
  --discover           log every packet and highlight changing bytes
  --sweep              also probe other cmd_ids (with --discover)
  --watch SET ID       rapidly poll one command and show its live payload
  --diff               capture neutral vs held-button states and diff them

It never injects keyboard or mouse input, so it is safe to run anywhere.

Run:  python test_control.py [--port COMx] [--discover | --sweep | --watch SET ID | --diff]
"""
import argparse
import sys
import time

import serial

from djirc import protocol as dji
from djirc.gui import run_gui
from djirc.reader import Reader


def _record(buckets, pkt):
    """Bucket a packet by (cmd_set, cmd_id, len) and track which payload bytes changed."""
    if len(pkt) < 13:
        return
    key = (pkt[9], pkt[10], len(pkt))   # (cmd_set, cmd_id, length)
    payload = bytes(pkt[11:-2])          # data between header and CRC
    b = buckets.get(key)
    if b is None:
        buckets[key] = {"count": 1, "base": payload, "changed": set(), "last": payload}
        return
    b["count"] += 1
    base = b["base"]
    for i in range(min(len(payload), len(base))):
        if payload[i] != base[i]:
            b["changed"].add(i)
    b["last"] = payload


def _render(buckets):
    """Print the discover-mode table of packet buckets and their changed bytes."""
    lines = ["\033[2J\033[H",
             "cmd_set cmd_id  len   count  changed bytes (absolute offset=value)",
             "-" * 72]
    for key in sorted(buckets):
        cs, ci, ln = key
        b = buckets[key]
        changed = sorted(b["changed"])
        detail = " ".join(f"{11 + i}={b['last'][i]:02X}" for i in changed) or "(none)"
        lines.append(f" 0x{cs:02X}    0x{ci:02X}   {ln:3d}  {b['count']:6d}   {detail}")
    lines.append("")
    lines.append("Keep sticks centered; press buttons/dials and watch for new changed bytes.")
    lines.append("Ctrl+C to stop.")
    print("\n".join(lines), flush=True)


def discover(preferred_port, sweep=False, sweep_start=0x00, sweep_end=0x3F):
    """Log all received packets and highlight changing bytes to locate buttons.

    Passively records every framed packet while sending the same stick poll
    main.py uses. With sweep=True it also probes cmd_ids in the RC command set
    (cmd_type 0x40, cmd_set 0x06 - the same safe request family) to try to elicit
    other packets.
    """
    try:
        s = dji.open_port(preferred_port)
    except (OSError, serial.SerialException) as e:
        print("Could not open serial port:", e)
        return 1
    if s is None:
        print("DJI RC 'For Protocol' port not found. Controller on and connected?")
        return 1

    print(f"Discovering on {s.name}. Keep controls idle briefly to set a baseline...")
    buckets = {}
    sweep_ids = list(range(sweep_start, sweep_end + 1))
    sweep_pos = 0
    last_render = 0.0
    try:
        dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, 0x24, bytearray.fromhex('01'))
        while True:
            dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, 0x01, bytearray.fromhex(''))
            if sweep and sweep_ids:
                cid = sweep_ids[sweep_pos % len(sweep_ids)]
                sweep_pos += 1
                dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, cid, bytearray.fromhex(''))
            for _ in range(8):
                pkt = dji.read_packet(s)
                if pkt is None:
                    break
                _record(buckets, pkt)
            now = time.time()
            if now - last_render >= 0.2:
                last_render = now
                _render(buckets)
    except serial.SerialException as e:
        print('\n\nCould not read/write:', e)
    except KeyboardInterrupt:
        print('\n\nStopped.')
    finally:
        s.close()
    return 0


def _render_watch(cs, ci, base, now, ever, count, age):
    """Print the watch-mode live payload with a baseline diff row."""
    lines = ["\033[2J\033[H", f"watch cmd_set=0x{cs:02X} cmd_id=0x{ci:02X}  packets={count}"]
    if base is None or now is None:
        lines.append(f"waiting for a matching response... ({age:.1f}s)")
    else:
        idx = range(len(now))
        lines.append("offset: " + ' '.join(f"{11 + i:2d}" for i in idx))
        lines.append("base  : " + ' '.join(f"{base[i]:02X}" if i < len(base) else '..' for i in idx))
        lines.append("now   : " + ' '.join(f"{now[i]:02X}" for i in idx))
        lines.append("diff  : " + ' '.join("^^" if (i < len(base) and now[i] != base[i]) else "  " for i in idx))
        offs = sorted(11 + i for i in ever)
        lines.append("ever-changed offsets: " + (' '.join(map(str, offs)) if offs else "(none)"))
    lines.append("")
    lines.append("Press a button and watch the 'now'/'diff' rows. Ctrl+C to stop.")
    print("\n".join(lines), flush=True)


def watch(preferred_port, cmd_set, cmd_id):
    """Rapidly poll one command and show its live payload to locate button bytes."""
    try:
        s = dji.open_port(preferred_port)
    except (OSError, serial.SerialException) as e:
        print("Could not open serial port:", e)
        return 1
    if s is None:
        print("DJI RC 'For Protocol' port not found. Controller on and connected?")
        return 1

    baseline = None
    ever = set()
    count = 0
    last_render = 0.0
    last_seen = time.time()
    try:
        dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, 0x24, bytearray.fromhex('01'))
        while True:
            dji.send_duml(s, 0x0A, 0x06, 0x40, cmd_set, cmd_id, bytearray.fromhex(''))
            payload = None
            for _ in range(8):
                pkt = dji.read_packet(s)
                if pkt is None:
                    break
                if len(pkt) >= 13 and pkt[9] == cmd_set and pkt[10] == cmd_id:
                    payload = bytes(pkt[11:-2])
            if payload is not None:
                count += 1
                last_seen = time.time()
                if baseline is None:
                    baseline = payload
                for i in range(min(len(payload), len(baseline))):
                    if payload[i] != baseline[i]:
                        ever.add(i)
            now = time.time()
            if now - last_render >= 0.1:
                last_render = now
                _render_watch(cmd_set, cmd_id, baseline, payload, ever, count, now - last_seen)
    except serial.SerialException as e:
        print('\n\nCould not read/write:', e)
    except KeyboardInterrupt:
        print('\n\nStopped.')
    finally:
        s.close()
    return 0


# cmd_ids in the RC set (0x06) that returned data during discovery; used as safe getters.
RC_GETTERS = [0x01, 0x03, 0x04, 0x19, 0x1A, 0x1E, 0x25, 0x26, 0x27, 0x2D, 0x2E, 0x2F, 0x38]


def _capture(s, ids, cycles=4):
    """Poll the given cmd_ids a few times and return the latest payload per packet key."""
    snap = {}
    for _ in range(cycles):
        for ci in ids:
            dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, ci, bytearray())
            for _ in range(4):
                pkt = dji.read_packet(s)
                if pkt is None:
                    break
                if len(pkt) >= 13:
                    snap[(pkt[9], pkt[10], len(pkt))] = bytes(pkt[11:-2])
    return snap


def diff_buttons(preferred_port, ids):
    """Capture neutral vs held-button states and report bytes that differ."""
    try:
        s = dji.open_port(preferred_port)
    except (OSError, serial.SerialException) as e:
        print("Could not open serial port:", e)
        return 1
    if s is None:
        print("DJI RC 'For Protocol' port not found. Controller on and connected?")
        return 1

    try:
        dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, 0x24, bytearray.fromhex('01'))
        input("Keep ALL sticks centered and buttons released, then press Enter to capture baseline...")
        neutral = _capture(s, ids)
        input("Now HOLD the button(s) to find (keep sticks centered) and press Enter while holding...")
        held = _capture(s, ids)
    except (serial.SerialException, OSError) as e:
        print("Serial error:", e)
        s.close()
        return 1

    found = False
    for key in sorted(neutral.keys() & held.keys()):
        a, b = neutral[key], held[key]
        diffs = [(11 + i, a[i], b[i]) for i in range(min(len(a), len(b))) if a[i] != b[i]]
        if diffs:
            found = True
            cs, ci, ln = key
            print(f"\ncmd_set=0x{cs:02X} cmd_id=0x{ci:02X} len={ln}:")
            for off, x, y in diffs:
                print(f"   offset {off}: {x:02X} -> {y:02X}")
    if not found:
        print("\nNo byte differed between neutral and held states on these commands.")
        print("=> The buttons are not exposed on this VCOM port.")
    s.close()
    return 0


def main():
    """Dispatch to the GUI or a console mode (--discover/--sweep/--watch/--diff)."""
    parser = argparse.ArgumentParser(description="Live tester and DUML protocol explorer for the DJI RC-N1/N3.")
    parser.add_argument('-p', '--port', help='RC serial port (auto-detected by default)')
    parser.add_argument('--discover', action='store_true',
                        help='Console mode: log all packets and highlight changing bytes (find buttons).')
    parser.add_argument('--sweep', action='store_true',
                        help='With --discover, also probe cmd_ids up to --sweep-end to elicit other packets.')
    parser.add_argument('--sweep-end', metavar='HEX', default='3F',
                        help='Highest cmd_id (hex) to probe with --sweep (default 3F; try FF).')
    parser.add_argument('--watch', nargs=2, metavar=('SET', 'ID'),
                        help='Console mode: rapidly poll one command (hex, e.g. --watch 06 27) '
                             'and show its live payload.')
    parser.add_argument('--diff', action='store_true',
                        help='Two-phase button finder: diff neutral vs held-button captures (most reliable).')
    args = parser.parse_args()

    if args.diff:
        return diff_buttons(args.port, RC_GETTERS)
    if args.watch:
        return watch(args.port, int(args.watch[0], 16), int(args.watch[1], 16))
    if args.discover or args.sweep:
        return discover(args.port, sweep=args.sweep, sweep_end=int(args.sweep_end, 16))

    reader = Reader(args.port)
    reader.start()
    run_gui(reader)
    reader.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
