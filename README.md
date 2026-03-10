# Audio Mixer for Linux

A lightweight VoiceMeeter Potato alternative for Linux. Control individual app volumes with keyboard shortcuts — separate channels for games, Discord, music, and browsers.

![PipeWire](https://img.shields.io/badge/PipeWire-required-blue)
![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%2B-orange)
![GNOME](https://img.shields.io/badge/GNOME-required-green)

## The Problem

On Windows, VoiceMeeter Potato lets you split audio into virtual cables and control each one independently. Linux has no built-in equivalent — you get one volume slider for everything.

## The Solution

This project creates **4 independent audio channels** using PipeWire virtual sinks, each controllable via numpad shortcuts with a visual OSD overlay.

### Channels & Keybindings

| Channel | What goes here                        | Mute          | Vol Down    | Vol Up      |
| ------- | ------------------------------------- | ------------- | ----------- | ----------- |
| Desktop | Games, system sounds, everything else | `Ctrl+Num1`   | `Ctrl+Num4` | `Ctrl+Num7` |
| Discord | Discord voice/audio                   | `Ctrl+Num2`   | `Ctrl+Num5` | `Ctrl+Num8` |
| Music   | YouTube Music, Spotify                | `Ctrl+Num3`   | `Ctrl+Num6` | `Ctrl+Num9` |
| Browser | Chrome, Firefox, Brave, etc.          | `Ctrl+NumDel` | `Ctrl+Num+` | `Ctrl+Num-` |

### OSD Overlay

Every keypress shows a minimal overlay with the channel name and volume percentage. It auto-detects your primary monitor (multi-monitor supported) and follows your GNOME light/dark theme.

## Requirements

- **Ubuntu 22.04+** (or any distro with PipeWire + GNOME on X11)
- **PipeWire + WirePlumber** (default audio server since Ubuntu 22.10)
- **GNOME desktop** (for keyboard shortcuts — sinks and OSD work on any DE)
- **Python 3 + GTK3** (pre-installed on Ubuntu)
- **A numpad** on your keyboard

The installer checks all requirements and installs any missing dependencies (`pavucontrol`, `xdotool`).

## Install

```bash
git clone https://github.com/CrazyGoGo42/my-audio-mixer-for-linux.git
cd audio-mixer-linux
chmod +x install.sh
./install.sh
```

The installer will:

1. Check your system (PipeWire, WirePlumber, Python, GTK)
2. Install missing dependencies (`pavucontrol`, `xdotool`)
3. Create 3 virtual audio sinks (Discord, Music, Browser)
4. Set up 12 keyboard shortcuts
5. Start the OSD overlay daemon (auto-starts on login)

## First-Time App Routing

After install, you need to tell PipeWire which apps go to which channel. **This only needs to be done once per app** — PipeWire remembers the assignment permanently.

1. Open the apps you want to route (Discord, Chrome, Spotify, etc.)
2. **Play some audio** in each app (PipeWire only sees apps that are producing sound)
3. Run:

```bash
audio-route-apps
```

Example output:

```
Routing apps to virtual sinks...

  ✓ Routed Discord → Discord_Audio (2 ports)
  ✓ Routed YouTube Music → Music_Audio (2 ports)
  ✓ Routed Google Chrome → Browser_Audio (2 ports)

Done! PipeWire will remember these assignments for future sessions.
```

Alternatively, use `pavucontrol` (PulseAudio Volume Control) to manually assign apps in its Playback tab.

## Works With EasyEffects

If you use EasyEffects for audio processing (EQ, compression, etc.), this works alongside it. The audio chain is:

```
App → Virtual Sink (volume control here) → EasyEffects → Hardware Output
```

## Uninstall

Removes everything the installer created (scripts, config, shortcuts, OSD daemon):

```bash
./uninstall.sh
```

## How It Works

| Component               | What it does                                                             |
| ----------------------- | ------------------------------------------------------------------------ |
| `virtual-sinks.conf`    | PipeWire config that creates 3 virtual audio sinks on boot               |
| `audio-channel-control` | Bash script (~20ms per call) that adjusts volume/mute via `pactl`        |
| `audio-osd`             | Persistent Python/GTK3 daemon that shows a volume overlay via named pipe |
| `audio-route-apps`      | Uses `pw-link` to wire apps to their virtual sinks                       |
| GNOME shortcuts         | 12 custom keybindings that call `audio-channel-control`                  |

### Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Discord    │     │   Spotify    │     │    Chrome    │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│Discord_Audio │     │ Music_Audio  │     │Browser_Audio │
│  (virtual)   │     │  (virtual)   │     │  (virtual)   │
│ Ctrl+Num2/5/8│     │ Ctrl+Num3/6/9│     │Ctrl+Del/+/- │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └────────────────────┼────────────────────┘
                            ▼
                  ┌──────────────────┐
                  │ Hardware Output  │
                  │  (Desktop ch.)   │
                  │  Ctrl+Num1/4/7   │
                  └──────────────────┘
```

## Files Installed

```
~/.local/bin/audio-osd                                    # OSD overlay daemon
~/.local/bin/audio-channel-control                        # Volume/mute control
~/.local/bin/audio-route-apps                             # App → sink routing
~/.config/pipewire/pipewire.conf.d/virtual-sinks.conf     # Virtual sink definitions
~/.config/autostart/audio-osd.desktop                     # OSD autostart on login
+ 12 GNOME custom keyboard shortcuts
```

## Customization

**Change volume step size** — edit `STEP` in `~/.local/bin/audio-channel-control`:

```bash
STEP="1%"   # default — 1% per keypress
STEP="5%"   # coarser control
```

**Change OSD position** — edit `TOP_MARGIN` in `~/.local/bin/audio-osd` (default: 48px from top).

**Add more channels** — add a new loopback module in `virtual-sinks.conf`, a new case in `audio-channel-control`, and a new keybinding.

## Troubleshooting

**No sound from an app after routing:**
Run `audio-route-apps` again while the app is playing audio, or use `pavucontrol` to check/change its output.

**OSD not showing:**
Check if the daemon is running: `cat /tmp/audio-osd.pid && echo "Running"`. Restart it with: `audio-osd &`

**Keybindings not working:**
Verify in Settings → Keyboard → Custom Shortcuts. Make sure NumLock is on.

**Virtual sinks disappeared after reboot:**
Check that `~/.config/pipewire/pipewire.conf.d/virtual-sinks.conf` exists, then restart PipeWire: `systemctl --user restart pipewire pipewire-pulse wireplumber`

## License

MIT
