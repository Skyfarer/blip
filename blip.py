#!/usr/bin/env python3
"""Blip: a tiny e-ink pet that lives in a backpack and feeds on nearby Bluetooth signals."""
import hashlib
import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import time
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "state.json")
W, H = 250, 122
SCALE = 4
NEAR_RSSI = -80
CYCLE_SECONDS = 60
FULL_REFRESH_EVERY = 20
HISTORY_LEN = 60
EATEN_TTL = 24 * 3600  # seconds before an eaten hash is forgotten

log = logging.getLogger("blip")

QUIPS = {
    "sleeping": ["zzz...", "5 more minutes", "dreaming of packets", "shh. sleeping"],
    "party": ["SO MANY FRIENDS", "it's a party!!", "signal buffet!", "best day ever"],
    "surprised": ["ooh, new friends!", "who's that?!", "hello hello!"],
    "hungry": ["so hungry...", "feed me signals", "tummy rumbling", "any bluetooth?"],
    "lonely": ["anyone there?", "so quiet...", "hello...?", "all alone"],
    "happy": ["hi friends!", "nom nom nom", "lots of pals :)", "this is nice"],
    "content": ["hi there", "just vibing", "one friend :)", "*bloop*", "nice backpack"],
}


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in (os.path.join(HERE, "fonts"), "/usr/share/fonts/truetype/dejavu"):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


F_TITLE = font(20, bold=True)
F_SMALL = font(11)
F_SMALL_B = font(11, bold=True)
F_QUIP = font(12, bold=True)
F_Z = font(14, bold=True)


# ---------------------------------------------------------------- pet sprite

def draw_pet(mood, frame, lit):
    """Draw the pet at low resolution; caller scales it up for the pixel-art look."""
    c = Image.new("1", (26, 28), 1)
    d = ImageDraw.Draw(c)
    bounce = mood in ("happy", "party") and frame % 2 == 1
    y = 7 - (2 if bounce else 0)

    # antennae (droop when asleep or hungry), bulbs filled when anyone is near
    if mood in ("sleeping", "hungry", "lonely"):
        tips = [(4, y + 1), (21, y + 1)]
        d.line([(9, y + 2), (tips[0][0] + 1, tips[0][1])], fill=0)
        d.line([(16, y + 2), (tips[1][0] - 1, tips[1][1])], fill=0)
    else:
        wiggle = 1 if (mood == "party" and frame % 2 == 0) else 0
        tips = [(6 - wiggle, y - 4), (19 + wiggle, y - 4)]
        d.line([(9, y + 2), tips[0]], fill=0)
        d.line([(16, y + 2), tips[1]], fill=0)
    for tx, ty in tips:
        d.rectangle([tx - 1, ty - 1, tx + 1, ty + 1], outline=0, fill=0 if lit else 1)

    # feet, then body on top
    fy = y + 14
    d.ellipse([5, fy, 10, fy + 5], outline=0, fill=1)
    d.ellipse([15, fy, 20, fy + 5], outline=0, fill=1)
    d.ellipse([2, y, 23, y + 17], outline=0, fill=1)

    ex, ey = (9, 16), y + 6
    mx, my = 12, y + 11

    if mood == "sleeping":
        for x in ex:
            d.line([(x - 1, ey + 2), (x + 1, ey + 2)], fill=0)
        d.line([(mx, my + 1), (mx + 1, my + 1)], fill=0)
    elif mood in ("happy", "party"):
        for x in ex:
            d.point([(x - 1, ey + 2), (x, ey + 1), (x + 1, ey + 2)], fill=0)
        if mood == "party":
            d.rectangle([mx - 2, my, mx + 3, my + 1], fill=0)
            d.point([(mx - 1, my + 2), (mx, my + 2), (mx + 1, my + 2), (mx + 2, my + 2)], fill=0)
        else:
            d.point([(mx - 1, my), (mx, my + 1), (mx + 1, my + 1), (mx + 2, my)], fill=0)
        for cx in (5, 20):
            d.point([(cx, y + 10), (cx + 1, y + 11), (cx - 1, y + 11)], fill=0)
    elif mood == "surprised":
        for x in ex:
            d.rectangle([x - 1, ey, x + 1, ey + 2], fill=0)
            d.point((x - 1, ey), fill=1)
        d.rectangle([mx - 1, my, mx + 2, my + 3], outline=0)
    elif mood in ("lonely", "hungry"):
        for i, x in enumerate(ex):
            d.rectangle([x - 1, ey + 1, x, ey + 3], fill=0)
            brow = [(x - 2, ey - 1), (x - 1, ey - 1), (x, ey - 2)] if i == 0 else \
                   [(x - 1, ey - 2), (x, ey - 1), (x + 1, ey - 1)]
            d.point(brow, fill=0)
        if mood == "hungry":
            d.rectangle([mx - 1, my + 1, mx + 2, my + 3], outline=0)
            d.point((mx + 3, my + 4), fill=0)  # drool
        else:
            d.point([(mx - 1, my + 2), (mx, my + 1), (mx + 1, my + 1), (mx + 2, my + 2)], fill=0)
    else:  # content, with the occasional blink
        blink = frame % 5 == 3
        for x in ex:
            if blink:
                d.line([(x - 1, ey + 2), (x + 1, ey + 2)], fill=0)
            else:
                d.rectangle([x - 1, ey, x, ey + 2], fill=0)
                d.point((x - 1, ey), fill=1)
        d.point([(mx - 1, my), (mx, my + 1), (mx + 1, my + 1), (mx + 2, my)], fill=0)

    if mood == "party":  # sparkles
        for sx, sy in ((1, 4), (24, 9), (1, 17), (24, 20)):
            if (sx + frame) % 2 == 0:
                d.point([(sx, sy - 1), (sx - 1, sy), (sx, sy), (sx + 1, sy), (sx, sy + 1)], fill=0)
    return c.resize((c.width * SCALE, c.height * SCALE), Image.NEAREST)


# ---------------------------------------------------------------- layout

def wrap(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines[:2]


def render(state, mood, quip, frame, nearby):
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)

    pet = draw_pet(mood, frame, lit=nearby > 0)
    img.paste(pet, (2, H - pet.height - 2))
    if mood == "sleeping":
        d.text((88, 14), "z", font=F_SMALL_B, fill=0)
        d.text((96, 2), "Z", font=F_Z, fill=0)

    x0 = 112
    d.text((x0, 0), "BLIP", font=F_TITLE, fill=0)
    age = (date.today() - date.fromisoformat(state["born"])).days + 1
    d.text((W - 2, 5), f"day {age}", font=F_SMALL, fill=0, anchor="ra")

    # speech bubble with a tail pointing back at the pet
    bx0, by0, bx1, by1 = x0, 26, W - 2, 60
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=6, outline=0, fill=1, width=1)
    d.polygon([(bx0, by0 + 16), (bx0 - 10, by0 + 26), (bx0, by0 + 24)], fill=1, outline=0)
    d.line([(bx0, by0 + 17), (bx0, by0 + 23)], fill=1)
    lines = wrap(d, quip, F_QUIP, bx1 - bx0 - 10)
    cy = (by0 + by1) / 2 - (len(lines) - 1) * 7
    for i, line in enumerate(lines):
        d.text(((bx0 + bx1) / 2, cy + i * 14), line, font=F_QUIP, fill=0, anchor="mm")

    # stats
    d.text((x0, 64), "near", font=F_SMALL, fill=0)
    d.text((x0 + 28, 64), str(nearby), font=F_SMALL_B, fill=0)
    d.text((W - 2, 64), f"{state['total_eaten']} snacks", font=F_SMALL_B, fill=0, anchor="ra")

    # tummy bar
    d.text((x0, 79), "tummy", font=F_SMALL, fill=0)
    tx0, tx1 = x0 + 40, W - 2
    d.rectangle([tx0, 81, tx1, 90], outline=0)
    fill_w = int((tx1 - tx0 - 3) * state["fullness"] / 100)
    if fill_w > 0:
        d.rectangle([tx0 + 2, 83, tx0 + 2 + fill_w, 88], fill=0)

    # sparkline of nearby-device counts over the last hour
    sx0, sy0, sx1, sy1 = x0, 96, W - 2, H - 2
    d.line([(sx0, sy1), (sx1, sy1)], fill=0)
    hist = state["history"][-(sx1 - sx0) // 2:]
    peak = max(hist + [5])
    for i, v in enumerate(hist):
        x = sx1 - (len(hist) - 1 - i) * 2
        h = round((sy1 - sy0) * v / peak)
        if h:
            d.line([(x, sy1 - h), (x, sy1)], fill=0)
    return img


# ---------------------------------------------------------------- brain

def load_state():
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {"born": date.today().isoformat(), "total_eaten": 0, "fullness": 60,
                  "history": [], "day": date.today().isoformat(), "eaten_today": 0}
    # salt must persist across restarts (not per-run) so a beacon's hash stays
    # stable and it can be recognized as already-eaten; addresses themselves
    # are never stored, only the salted hash.
    state.setdefault("salt", os.urandom(8).hex())
    eaten = state.get("eaten", {})
    if isinstance(eaten, list):  # older format: bare list of hashes, no timestamps
        eaten = dict.fromkeys(eaten, time.time())
    state["eaten"] = eaten
    return state


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


def scan():
    """Return {address: best_rssi} from a ~10s BLE discovery."""
    # btmgmt exits immediately if stdin hits EOF (as under systemd), so hold a pipe open
    # until discovery finishes.
    proc = subprocess.Popen(["btmgmt", "--index", "0", "find", "-l"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            errors="replace")  # device names can contain invalid UTF-8
    lines, deadline = [], time.monotonic() + 30
    for line in proc.stdout:
        lines.append(line)
        if "discovering off" in line or time.monotonic() > deadline:
            break
    proc.kill()
    proc.wait()
    out = "".join(lines)
    found = {}
    for addr, rssi in re.findall(r"dev_found: (\S+) type .*? rssi (-?\d+)", out):
        found[addr] = max(found.get(addr, -999), int(rssi))
    return found


def pick_mood(nearby, new, fullness):
    hour = datetime.now().hour
    if (hour >= 23 or hour < 7) and nearby < 3:
        return "sleeping"
    if nearby >= 30:
        return "party"
    if new >= 4:
        return "surprised"
    if fullness < 15:
        return "hungry"
    if nearby == 0:
        return "lonely"
    if nearby >= 6:
        return "happy"
    return "content"


class Display:
    def __init__(self):
        sys.path.insert(0, os.path.join(HERE, "lib"))
        from waveshare_epd import epd2in13_V4
        self.epd = epd2in13_V4.EPD()
        self.count = 0

    def show(self, img):
        buf = self.epd.getbuffer(img)
        if self.count % FULL_REFRESH_EVERY == 0:
            self.epd.init()
            self.epd.displayPartBaseImage(buf)
        else:
            self.epd.displayPartial(buf)
        self.count += 1

    def goodbye(self, img):
        self.epd.init()
        self.epd.display(self.epd.getbuffer(img))
        self.epd.sleep()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    state = load_state()
    display = Display()
    salt = bytes.fromhex(state["salt"])
    eaten = state["eaten"]  # {hash: time eaten} for beacons already eaten, so they aren't snacked on twice
    frame = 0

    def stop(*_):
        img = render(state, "sleeping", "powered off. see you soon!", 0, 0)
        display.goodbye(img)
        save_state(state)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while True:
        started = time.monotonic()
        today = date.today().isoformat()
        if state["day"] != today:
            state["day"], state["eaten_today"] = today, 0

        found = scan()
        nearby = sum(1 for r in found.values() if r >= NEAR_RSSI)
        new = 0
        now = time.time()
        # most devices rotate their address every ~15 min, so old hashes will never
        # match again; forget them after a day to keep state.json from growing forever
        for h in [h for h, t in eaten.items() if now - t > EATEN_TTL]:
            del eaten[h]
        for addr in found:
            h = hashlib.sha1(salt + addr.encode()).hexdigest()[:16]
            if h not in eaten:
                eaten[h] = now
                new += 1
        state["total_eaten"] += new
        state["eaten_today"] += new
        state["fullness"] = max(0, min(100, state["fullness"] - 1 + min(new, 10) * 3))
        state["history"] = (state["history"] + [nearby])[-HISTORY_LEN:]

        mood = pick_mood(nearby, new, state["fullness"])
        quip = random.choice(QUIPS[mood])
        log.info("found=%d nearby=%d new=%d fullness=%d mood=%s",
                 len(found), nearby, new, state["fullness"], mood)
        display.show(render(state, mood, quip, frame, nearby))
        save_state(state)
        frame += 1
        time.sleep(max(0, CYCLE_SECONDS - (time.monotonic() - started)))


def preview(outdir):
    os.makedirs(outdir, exist_ok=True)
    state = {"born": "2026-09-17", "total_eaten": 142, "fullness": 55,
             "history": [random.randint(0, 9) for _ in range(60)]}
    cases = [("content", 2), ("happy", 7), ("party", 34), ("surprised", 5),
             ("lonely", 0), ("hungry", 1), ("sleeping", 0)]
    for mood, near in cases:
        for frame in (0, 1):
            img = render(state, mood, QUIPS[mood][0], frame, near)
            img.save(os.path.join(outdir, f"{mood}_{frame}.png"))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
    else:
        main()
