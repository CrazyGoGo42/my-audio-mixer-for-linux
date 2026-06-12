# Audio Mixer for Linux

A lightweight VoiceMeeter-style mixer for Linux. Split your audio into separate
channels — Games, Discord, Music, Browser, and a Default catch-all — each with
its own volume and numpad hotkeys, all processed through EasyEffects.

[![PipeWire](https://img.shields.io/badge/PipeWire-required-blue)](https://pipewire.org/)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%2B-orange)](https://ubuntu.com/)
[![GNOME](https://img.shields.io/badge/GNOME-required-green)](https://www.gnome.org/)

## The Problem

On Windows, VoiceMeeter lets you split audio into virtual cables and control
each independently. Linux gives you one volume slider for everything.

## The Solution

Five **virtual sinks** (PipeWire loopback devices), one per channel. Apps are
routed to the right sink **declaratively** — pipewire-pulse places each stream
on its channel the moment it's created. There's no daemon chasing streams after
the fact, so:

- A player you **stop and restart always comes back on its own channel.**
- Nothing ever lands on the raw hardware output at full volume. Unrecognised
  apps go to the attenuated **Default** channel instead.

| Channel | What goes here                        | Mute          | Vol Down    | Vol Up      |
| ------- | ------------------------------------- | ------------- | ----------- | ----------- |
| Games   | Games, wine/proton                    | `Ctrl+Num1`   | `Ctrl+Num4` | `Ctrl+Num7` |
| Discord | Discord voice/audio                   | `Ctrl+Num2`   | `Ctrl+Num5` | `Ctrl+Num8` |
| Music   | YouTube Music, Spotify, Plexamp       | `Ctrl+Num3`   | `Ctrl+Num6` | `Ctrl+Num9` |
| Browser | Chrome, Firefox, Brave, etc.          | `Ctrl+NumDel` | `Ctrl+Num+` | `Ctrl+Num-` |
| Default | Everything else (asks where it goes)  | `Ctrl+Num0`   | `Ctrl+Num/` | `Ctrl+Num*` |

Each keypress shows a minimal OSD overlay on your primary monitor that follows
your GNOME light/dark theme.

## How routing works

```
routes.json  ──(audio-routes-apply)──►  pipewire-pulse rules  ──►  every app born on the right sink
```

- **Known apps** (browsers, Discord, Spotify, YouTube Music, …) are matched by
  name and pinned to their channel — see `~/.config/audio-mixer/routes.json`.
- **Unknown apps** start on **Default** (safe and attenuated). A small popup
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

The installer pulls in anything missing (`zenity`, `pavucontrol`, `xrandr`).

## Install

```bash
git clone https://github.com/CrazyGoGo42/my-audio-mixer-for-linux.git
cd my-audio-mixer-for-linux
./install.sh
```

The installer creates the 5 sinks, compiles the routing rules, registers the
background services (via systemd user units), sets up the keybindings, and
migrates any routes you'd taught an earlier version.

## Uninstall

```bash
./uninstall.sh
```

Removes the scripts, configs, services, and keybindings. EasyEffects settings
are left alone.

## How It Works

| Component               | What it does                                                              |
| ----------------------- | ------------------------------------------------------------------------ |
| `virtual-sinks.conf`    | Creates the 5 virtual channel sinks on boot                              |
| `routes.json`           | Your app → channel map (editable; the popup also writes to it)           |
| `audio-routes-apply`    | Compiles `routes.json` into pipewire-pulse routing rules                 |
| `audio-channel-control` | Adjusts per-channel volume/mute (the hotkeys call this)                  |
| `audio-osd`             | Persistent GTK overlay showing the channel + volume on each keypress     |
| `audio-router-daemon`   | Prompts for unknown apps; keeps the EasyEffects chain wired. No notifs.  |
| `audio-route-apps`      | One-shot: move currently-playing apps onto their channel                 |

### Architecture

```
  Discord        Spotify        Chrome         (new app?)
     │              │              │                │
     ▼              ▼              ▼                ▼
 Discord_Audio  Music_Audio   Browser_Audio    Default_Audio   ← per-channel volume
     └──────────────┴──────────────┴────────────────┘
                            ▼
                     easyeffects_sink → EasyEffects → Speakers / Headset
```

## Customization

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

**Sinks missing after reboot:** confirm
`~/.config/pipewire/pipewire.conf.d/virtual-sinks.conf` exists, then
`systemctl --user restart pipewire pipewire-pulse wireplumber`.

**Check the services:** `systemctl --user status audio-router-daemon audio-osd`.

## License

MIT
