# Audio Mixer for Linux

A lightweight VoiceMeeter-style mixer for Linux. Split your audio into separate
channels — Desktop (the catch-all, games included), Discord, Music and Browser —
each with its own volume and numpad hotkeys, all processed through EasyEffects.
A fifth, **All Audio**, carries every channel mixed together for recording or
streaming.

[![PipeWire](https://img.shields.io/badge/PipeWire-required-blue)](https://pipewire.org/)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%2B-orange)](https://ubuntu.com/)
[![GNOME](https://img.shields.io/badge/GNOME-required-green)](https://www.gnome.org/)

## The Problem

On Windows, VoiceMeeter lets you split audio into virtual cables and control
each independently. Linux gives you one volume slider for everything.

## The Solution

One **virtual sink** (PipeWire loopback device) per channel. Apps are
routed to the right sink **declaratively** — pipewire-pulse places each stream
on its channel the moment it's created. There's no daemon chasing streams after
the fact, so:

- A player you **stop and restart always comes back on its own channel.**
- Nothing ever lands on the raw hardware output at full volume. Unrecognised
  apps go to the **Desktop** channel instead.

| Channel | What goes here                             | Mute          | Vol Down    | Vol Up      |
| ------- | ------------------------------------------ | ------------- | ----------- | ----------- |
| Desktop | Games, wine/proton, everything else        | `Ctrl+Num1`   | `Ctrl+Num4` | `Ctrl+Num7` |
| Discord | Discord voice/audio                        | `Ctrl+Num2`   | `Ctrl+Num5` | `Ctrl+Num8` |
| Music   | YouTube Music, Spotify, Plexamp            | `Ctrl+Num3`   | `Ctrl+Num6` | `Ctrl+Num9` |
| Browser | Chrome, Firefox, Brave, etc.               | `Ctrl+NumDel` | `Ctrl+Num+` | `Ctrl+Num-` |

Each keypress shows a minimal OSD overlay on your primary monitor that follows
your GNOME light/dark theme.

### All Audio (the all-in-one channel)

**All Audio** shows up in apps as an *input*, like a microphone. Pick it in
OBS, a screen recorder or a voice app and it gets every channel mixed together,
exactly at the levels and mutes you've set — the channels themselves stay
separate. It's taken before EasyEffects (so your speaker EQ isn't baked into a
stream) and doesn't include your mic. Don't use it as your Discord mic: it
contains the Discord channel, so people would hear themselves.

### Effects, outputs and your mic

Like VoiceMeeter's strips and A1/A2 buttons, controlled with `audio-mixer`
(the mixer window, coming next, uses the same settings):

- **FX per channel** — on: the channel goes through your EasyEffects preset;
  off: it plays dry. All on by default, which sounds exactly like before.
- **EasyEffects is a strip of its own** with its own volume (pavucontrol:
  "EasyEffects") and outputs. FX-on channels play wherever it plays.
- **Outputs A1–A4** — each slot is a device you pick, or "default output"
  (follows your headset when you plug it in). FX-off channels choose their own.
- **Bass / Treble per channel**, ±12 dB, independent of FX.
- **Mic** — EasyEffects listens to the "Mixer Mic", which only ever gets a
  real microphone (your USB headset mic when it's plugged in, else the built-in
  one), and apps' default mic is EasyEffects' processed output. Your speakers
  can't end up in your mic.

```bash
audio-mixer status                 # what goes where
audio-mixer devices                # outputs and mics you can pick
audio-mixer fx browser off         # Browser plays dry
audio-mixer slot A2 alsa_output.usb-…   # A2 = the headset
audio-mixer out browser A2 on      # Browser also plays on A2
audio-mixer out fx A2 on           # EasyEffects strip also plays on A2
audio-mixer eq music bass 6        # +6 dB bass on Music
audio-mixer mic auto               # or a device name from `devices`
```

Settings live in `~/.config/audio-mixer/mixer.json` (backed up daily).

## How routing works

```
routes.json  ──(audio-routes-apply)──►  pipewire-pulse rules  ──►  every app born on the right sink
```

- **Known apps** (browsers, Discord, Spotify, YouTube Music, …) are matched by
  name and pinned to their channel — see `~/.config/audio-mixer/routes.json`.
- **Unknown apps** start on **Desktop**. A small popup
  asks which channel they should use; your answer is saved and applied from then
  on. No re-asking, and **no notifications.**

To route apps by hand at any time:

```bash
audio-route-apps        # move everything currently playing onto its channel now
audio-routes-apply      # recompile rules after editing routes.json
pavucontrol             # GUI: drag a stream to any sink in the Playback tab
```

## Works with EasyEffects

Every channel feeds EasyEffects, which then drives your hardware:

```
App → Channel sink (volume) → easyeffects_sink → EasyEffects → Speakers/Headset
```

EasyEffects is a Flatpak that starts after PipeWire, so the background daemon
keeps the channel→EasyEffects links wired (and re-wires them if EasyEffects
restarts). Your EasyEffects presets and settings are left untouched.

## Requirements

- **Ubuntu 22.04+** (or any distro with PipeWire + WirePlumber)
- **GNOME on X11** for the keybindings and OSD (sinks/routing work anywhere)
- **Python 3 + GTK3** (pre-installed on Ubuntu)
- A **numpad**

The installer pulls in anything missing (`zenity`, `pavucontrol`, `xrandr`,
`rsync`, and EasyEffects from Flathub).

## Install

```bash
git clone https://github.com/CrazyGoGo42/my-audio-mixer-for-linux.git
cd my-audio-mixer-for-linux
./install.sh
```

The installer sets up EasyEffects if it's missing, creates the channel sinks,
compiles the routing rules, registers the background services (via systemd user
units), sets up the keybindings, and takes a first backup. It's safe to rerun.

## Backup & reinstalling Ubuntu

Everything a fresh install would lose is backed up **daily** (and on every
install) by `audio-mixer-backup`:

- your channels, learned app routes and channel volumes (`~/.config/audio-mixer`)
- your EasyEffects settings and presets
- each sound card's profile (e.g. the headset's "Analog Stereo Duplex" mic mode)

The backup goes to `audio-mixer-backup/` inside your **Nextcloud** sync folder
when there is one (so it survives the reinstall), otherwise `~/audio-mixer-backup`.
`audio-mixer-backup --where` prints the folder; `audio-mixer-backup DIR` backs up
to a folder of your choice and remembers it.

After reinstalling Ubuntu:

1. Install the Nextcloud client and let it sync (or copy the backup folder back).
2. `git clone` this repo and run `./install.sh` — it finds the backup and offers
   to restore it. Or point it at one: `./install.sh --restore /path/to/backup`.

## Uninstall

```bash
./uninstall.sh
```

Removes the scripts, configs, services, and keybindings. EasyEffects settings
and your backup folder are left alone.

## How It Works

| Component               | What it does                                                              |
| ----------------------- | ------------------------------------------------------------------------ |
| `channels.conf`         | The channel list: sink names, labels, hotkeys. Everything reads it       |
| `routes.json`           | Your app → channel map (editable; the popup also writes to it)           |
| `audio-routes-apply`    | Builds the channel sinks + pipewire-pulse routing rules from the two above |
| `audio-channel-control` | Adjusts per-channel volume/mute (the hotkeys call this)                  |
| `audio-osd`             | Persistent GTK overlay showing the channel + volume on each keypress     |
| `audio-mixer`           | FX, output slots, Bass/Treble and mic (writes `mixer.json`)              |
| `audio-router-daemon`   | Prompts for unknown apps; the patchbay that links everything as `mixer.json` says; restores volumes at login. No notifs. |
| `audio-route-apps`      | One-shot: move currently-playing apps onto their channel                 |
| `easyeffects-watchdog`  | Restarts EasyEffects if it dies or hangs                                 |
| `audio-mixer-backup`    | Daily backup / restore of your settings (see above)                      |

### Architecture

```
  Discord        Spotify        Chrome      games, (new app?)
     │              │              │                │
     ▼              ▼              ▼                ▼
 Discord_Audio  Music_Audio   Browser_Audio    Default_Audio   ← volume + Bass/Treble
     │              │              │                │            (Desktop)
     ├── FX on ──► easyeffects_sink → EasyEffects → EE_Return ──► its A1–A4
     ├── FX off ─► the channel's own A1–A4 (speakers, headset, HDMI…)
     └── always ─► All Audio (input for OBS / recorders)

  real mic ──► Mixer Mic ──► EasyEffects (input effects) ──► apps' default mic
```

## Customization

- **Channels** — add, remove or rename channels and their hotkeys in
  `~/.config/audio-mixer/channels.conf`, then run `audio-routes-apply` (restarts
  PipeWire) and rerun `./install.sh` to rebind the hotkeys.
- **Volume step** — edit `STEP` in `~/.local/bin/audio-channel-control` (default `1`).
- **OSD position** — edit `TOP_MARGIN` in `~/.local/bin/audio-osd`.
- **Routing** — edit `~/.config/audio-mixer/routes.json`, then run `audio-routes-apply`.

## Troubleshooting

**An app went to the wrong channel:** edit `~/.config/audio-mixer/routes.json`
(match by `application.process.binary` or `application.name`) and run
`audio-routes-apply`. Find an app's identifiers with
`pactl list sink-inputs | grep -E 'application.(name|process.binary)'`.

**No sound after plugging in a headset:** the chain follows your default output
via EasyEffects; give it a second, or check `pavucontrol` → Output Devices.

**Sinks missing after reboot, or a channel is silent:** run
`audio-routes-apply --restart-pipewire`. It restarts PipeWire safely (EasyEffects
quit and relaunched, volumes restored before anything plays) and tells you if
something still isn't wired. Avoid restarting WirePlumber on its own — on this
PipeWire version that disconnects everything.

**All sound hardware gone after a reboot** (`pactl list cards short` is empty,
only the virtual channels remain): the kernel booted without its sound drivers.
Run `sudo apt install linux-modules-extra-$(uname -r)` and reboot.

**Check the services:** `systemctl --user status audio-router-daemon audio-osd easyeffects-watchdog`.

## License

MIT
