# Blip

A tiny e-ink pet that lives in a backpack and feeds on nearby Bluetooth signals.

Blip runs on a Raspberry Pi Zero W with a Waveshare 2.13" e-paper HAT. Once a minute it scans for nearby Bluetooth Low Energy devices (phones, earbuds, watches, smart-home gadgets). Every device it hasn't seen yet today is a "snack". Its mood follows how many devices are nearby: lonely in an empty room, happy at home, and throwing a party in a crowd.

![Blip's moods](docs/moods.png)

## What's on the screen

| Element | Meaning |
|---|---|
| The pet | Pixel-art creature whose face, antennae, and bounce reflect its mood |
| Antenna bulbs | Filled when at least one device is nearby, hollow when nothing is |
| Speech bubble | A random line for the current mood |
| `day N` | Days since Blip was born (first run) |
| `near N` | Devices seen in the last scan with RSSI ≥ −80 dBm |
| `N snacks` | Lifetime count of devices eaten |
| `tummy` | Fullness 0–100. Each new device adds 3 (up to 30 per scan), and it drops by 1 every minute |
| Graph | Nearby-device count for each scan over the last hour |

## Moods

Moods are checked in this order, and the first match wins:

| Mood | When |
|---|---|
| sleeping | 11pm–7am and fewer than 3 devices nearby |
| party | 30+ devices nearby |
| surprised | 4+ new devices in one scan |
| hungry | tummy below 15 |
| lonely | nothing nearby |
| happy | 6+ devices nearby |
| content | otherwise (blinks now and then) |

The thresholds were tuned so a typical house (15–18 devices) reads as happy and only real crowds trigger a party. Adjust them in `pick_mood()`. The lines Blip says are in the `QUIPS` dict at the top of `blip.py`.

When the service stops (shutdown, `systemctl stop`), Blip does a final full refresh showing itself asleep with "powered off. see you soon!". E-ink keeps its image without power, so an unplugged badge still has a face.

## Privacy

Blip only counts devices. Bluetooth addresses are hashed in memory with a random salt that changes every run, and the hashes are cleared each day and never written to disk. Device names are never shown or stored. `state.json` holds only counts, fullness, birth date, and the history graph.

Note: many phones rotate their BLE address every ~15 minutes, so "snacks" overcounts real people. For a pet, that's fine.

## Hardware

- Raspberry Pi Zero W (armv6, Raspberry Pi OS Bookworm)
- Waveshare 2.13" e-Paper HAT **V4** (250×122, black/white)
- Onboard Bluetooth (`hci0`)

## Install

On the Pi, with SPI enabled (`sudo raspi-config nonint do_spi 0`):

```bash
sudo apt install -y python3-pil python3-spidev python3-gpiozero python3-lgpio fonts-dejavu-core bluez

mkdir -p ~/blip/lib
# Copy blip.py and blip.service into ~/blip, then add the Waveshare driver:
git clone --depth 1 https://github.com/waveshare/e-Paper /tmp/e-Paper
cp -r /tmp/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd ~/blip/lib/

sudo cp ~/blip/blip.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now blip
```

Fonts are loaded from `~/blip/fonts/` if present, otherwise from `/usr/share/fonts/truetype/dejavu/`.

The service runs as root because `btmgmt` needs root to start discovery. No venv is needed, because the Waveshare driver only uses system packages (`spidev`, `gpiozero`).

## Operating

```bash
sudo systemctl status blip
sudo journalctl -u blip -f        # one line per scan: found/nearby/new/fullness/mood
sudo systemctl restart blip
```

To reset Blip (new birthday, zero snacks), stop the service and delete `~/blip/state.json`.

## Previewing without hardware

Render every mood to PNGs on any machine with Pillow:

```bash
python3 blip.py --preview out/
```

`docs/moods.png` was built from this output.

## Implementation notes

- **Scanning** uses `btmgmt --index 0 find -l`, a ~10 second LE discovery. `btmgmt` exits immediately if its stdin hits EOF, which is what happens under systemd (stdin is `/dev/null`). So `scan()` holds a stdin pipe open and reads until `discovering off`. Without that, every scan silently returns zero devices.
- **Display**: a full refresh every 20 updates clears ghosting. Partial refreshes (`displayPartial`) happen in between, so the minute-by-minute updates don't flash.
- **Sprite**: the pet is drawn on a 26×28 canvas with Pillow primitives, then scaled 4× with nearest-neighbor for the chunky pixel look.

## History

This Pi was previously a conference badge showing ADS-B aircraft stats at EAA AirVenture (`~/adsb_display` on the Pi, `adsb_display.service`, now disabled). To switch back:

```bash
sudo systemctl disable --now blip
sudo systemctl enable --now adsb_display
```
