# Raspberry Pi Spotify Streamer

A minimal Spotify-only audio streamer for Raspberry Pi 5.

This project turns a clean Raspberry Pi OS / Debian-based Pi into a simple
Spotify Connect receiver with USB DAC output and a local fullscreen Now Playing
touch UI. Audio playback is handled by Raspotify/librespot; the web app is only
for metadata and optional Spotify Web API controls.

## What It Builds

- Spotify Connect receiver using Raspotify/librespot
- ALSA output to a USB DAC, such as a Schiit Modi
- Local FastAPI web UI on `http://localhost:3000`
- Fullscreen Chromium kiosk for HDMI/touchscreen display
- systemd services for boot startup and crash restart
- Spotify Web API metadata:
  - album art
  - artist
  - track title
  - album
  - progress
  - play/pause state
- Optional touchscreen controls:
  - previous
  - play/pause
  - next
  - seek
  - repeat

The web UI does not play audio. If the UI crashes, Spotify playback continues
through Raspotify.

## Target Hardware

- Raspberry Pi 5
- Raspberry Pi OS or Debian-based Linux
- USB DAC
- HDMI or DSI touchscreen/display
- Network connection to Spotify

The setup was originally built and tested on Debian 13 `trixie` / Raspberry Pi
5 with a Schiit Modi 3 USB DAC.

## Quick Start

On the Pi:

```bash
sudo apt-get update
sudo apt-get -y install git
git clone git@github.com:yudovenko/raspberry-spotify-streamer.git
cd raspberry-spotify-streamer
cp config.example config.local
nano config.local
sudo ./scripts/setup.sh ./config.local
```

After setup, choose the configured Spotify Connect device in Spotify. The
default name is:

```text
Canton RC-L
```

## Configuration

Edit `config.local` before running the installer.

Important values:

```bash
DEVICE_NAME="Canton RC-L"
USB_DAC_MATCH="Schiit Modi"
ALSA_DEVICE=""
KIOSK_USER="yaroslav"
INSTALL_KIOSK="yes"
```

If `ALSA_DEVICE` is empty, the installer searches ALSA cards for
`USB_DAC_MATCH` and configures:

```text
hw:CARD=<detected-card-id>,DEV=0
```

If auto-detection fails, find the device manually:

```bash
aplay -l
aplay -L
```

Then set, for example:

```bash
ALSA_DEVICE="hw:CARD=S3,DEV=0"
```

Use `plughw` only if direct `hw` output fails with your DAC:

```bash
ALSA_DEVICE="plughw:CARD=S3,DEV=0"
```

## Hi-Fi Playback Settings

The default installer profile is quality-oriented:

```bash
LIBRESPOT_DEVICE="hw:CARD=<detected-card-id>,DEV=0"
LIBRESPOT_BITRATE="320"
LIBRESPOT_FORMAT="S16"
LIBRESPOT_INITIAL_VOLUME="100"
LIBRESPOT_VOLUME_CTRL="fixed"
LIBRESPOT_VOLUME_NORMALISATION="no"
```

This keeps Spotify Connect at 320 kbps, avoids librespot loudness
normalization, avoids digital volume attenuation, and sends audio directly to
the USB DAC through ALSA where possible.

If direct hardware output does not work with your DAC, change `ALSA_DEVICE` to
`plughw:CARD=...,DEV=0` in `config.local` and rerun setup. `plughw` is more
compatible but may allow ALSA conversion.

For fair comparisons against another source, match volume carefully. A louder
source almost always sounds better in quick A/B tests.

## Spotify API Setup

Raspotify playback does not need Spotify API credentials. The local Now Playing
UI does need them for metadata and controls.

Create a Spotify app:

1. Open the Spotify Developer Dashboard.
2. Create an app.
3. Add this redirect URI:

```text
http://localhost:8888/callback
```

4. Save the Client ID and Client Secret.

Generate the refresh token from your laptop through SSH port forwarding:

```bash
ssh -L 8888:localhost:8888 pi@YOUR_PI_IP
sudo /opt/spotify-now-playing/get_refresh_token.py
sudo systemctl restart spotify-now-playing.service
```

The helper requests these scopes:

```text
user-read-currently-playing
user-read-playback-state
user-modify-playback-state
```

The first two are needed for metadata. `user-modify-playback-state` is required
for touchscreen controls.

Secrets are written to:

```text
/etc/spotify-now-playing.env
```

The installer sets permissions to:

```text
600 root:root
```

Do not commit this file.

## Installed Files

```text
/opt/spotify-now-playing/
  app/
  get_refresh_token.py

/etc/spotify-now-playing.env
/etc/systemd/system/spotify-now-playing.service
/etc/raspotify/conf
/usr/local/bin/spotify-now-playing-kiosk
```

If kiosk mode is enabled on a Raspberry Pi labwc desktop, the installer adds:

```text
~/.config/labwc/autostart
```

If no desktop session is running and `INSTALL_MINIMAL_GUI_IF_MISSING=yes`, the
installer installs minimal labwc/Chromium packages and enables:

```text
spotify-kiosk.service
```

## Services

Check Spotify Connect:

```bash
systemctl status raspotify --no-pager -l
journalctl -u raspotify -b -f
sudo systemctl restart raspotify
```

Check the Now Playing UI:

```bash
systemctl status spotify-now-playing.service --no-pager -l
journalctl -u spotify-now-playing.service -b -f
curl http://127.0.0.1:3000/health
curl http://127.0.0.1:3000/api/current
sudo systemctl restart spotify-now-playing.service
```

Check kiosk mode:

```bash
pgrep -a chromium
systemctl status spotify-kiosk.service --no-pager -l
```

`spotify-kiosk.service` is only used when the installer had to create a minimal
GUI kiosk service. On Raspberry Pi OS Desktop/labwc, Chromium is normally
started from the user's labwc autostart file.

## Reboot Test

```bash
sudo reboot
```

After reboot:

- Spotify should show the Connect device named by `DEVICE_NAME`.
- Audio should play through the configured USB DAC.
- The local UI should be reachable at `http://localhost:3000`.
- The HDMI/touch display should open Chromium in kiosk mode.

## Troubleshooting

### USB DAC Not Detected

Run:

```bash
lsusb
aplay -l
aplay -L
cat /proc/asound/cards
```

Confirm that the DAC appears as a USB Audio device. If it appears with a stable
card ID, put it in `config.local`:

```bash
ALSA_DEVICE="hw:CARD=S3,DEV=0"
```

Then rerun:

```bash
sudo ./scripts/setup.sh ./config.local
```

### Spotify Connect Device Not Visible

Check Raspotify:

```bash
systemctl status raspotify --no-pager -l
journalctl -u raspotify -b -n 100 --no-pager
```

Make sure the Pi and your Spotify phone/desktop client are on the same network.

### Metadata Works But Controls Do Not

Regenerate the refresh token. Controls require:

```text
user-modify-playback-state
```

Run:

```bash
ssh -L 8888:localhost:8888 pi@YOUR_PI_IP
sudo /opt/spotify-now-playing/get_refresh_token.py
sudo systemctl restart spotify-now-playing.service
```

### Chromium Shows a Keyring Prompt

The kiosk launcher uses:

```text
--password-store=basic
--no-first-run
```

If a stale dialog is already on screen, cancel it once or restart the kiosk:

```bash
pkill -f 'chromium.*localhost:3000'
/usr/local/bin/spotify-now-playing-kiosk
```

### Screen Blanking

The installer tries:

```bash
raspi-config nonint do_blanking 1
```

For labwc sessions it also runs `xset` and `wlopm` from autostart where
available.

## Updating

Pull the latest repository and rerun setup:

```bash
git pull
sudo ./scripts/setup.sh ./config.local
```

The installer is intended to be idempotent. It backs up the first existing
Raspotify config to:

```text
/etc/raspotify/conf.before-spotify-streamer
```

## Security Notes

- The web UI binds to `127.0.0.1` by default.
- Spotify secrets live in `/etc/spotify-now-playing.env`.
- The env file is not part of the repository.
- The web UI is not an audio playback path.
- Avoid exposing port `3000` to the LAN unless you understand the implications.

## License

MIT
