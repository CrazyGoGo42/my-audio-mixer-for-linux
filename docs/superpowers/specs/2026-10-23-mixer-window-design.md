# Mixer window — design

Date: 2026-10-23. Status: approved by the user 2026-10-23 ("rock that thing").

## Intent

This project is the user's VoiceMeeter replacement on Linux. The routing engine
already exists and works: four isolated channels (Desktop, Discord, Music,
Browser), an All Audio input, declarative app routing, numpad hotkeys with an
OSD, persistent volumes, and a daily backup. What's missing is the part of
VoiceMeeter the user lived in: **a window that's always open on the second
screen, showing every channel, every app making sound, and where each one goes —
and that moves when the hotkeys move things.**

In the user's words: on Windows they "usually kept that open"; "the macros were
really important"; "seeing the changes on the app was also really good". Channels
must stay isolated ("everything is isolated"); the all-in-one channel is its own
fifth thing. Output devices: "YES! PLEASE! let me choose between options! … Let me
add like the 4 or so devices. Like it is for voicemeeter." Hotkeys: set by
right-clicking a button and pressing a key combination — "please dont create a
huge list of options to choose from like voicemeeter does that xD That is sooo 2002".
The mic goes through EasyEffects "to … have a fun time". Effects: "I love the fact
that I can choose bass on both games and music … is there a way that we can choose
which apps to route through easy effects … make it so that entire channels can get
routed through or all route on default? … per channel eq?"

## What the user decided

- **Layout B when wide** (mockups: `.superpowers/brainstorm/*/content/layout-v2.html`
  and, for effects, `effects.html`): a row of strips —
  **Mic | Desktop · Discord · Music · Browser | EasyEffects | All Audio** —
  each with a vertical slider, live level meter, mute button and % readout.
  Below it, **"Playing now"**: one row per app currently making sound, with its
  own live level and one button per channel; the app's current channel is
  highlighted.
- **Layout C when narrow:** the same window, made small, folds into compact rows
  (one horizontal slider per strip, the channel's app names listed under it) to
  sit in a corner.
- **Lives open on the second screen** all session.
- **Hotkeys stay central** and the window reflects every change they make, live.
- **Output devices like VoiceMeeter's A1/A2/…:** up to 4 output slots, each set to
  a device the user picks; every channel strip has one toggle per slot choosing
  where that channel plays.
- **Hotkeys are set from the window:** right-click a control → it shows the
  current key combination → press a new combination to change it. No big menu
  of actions.
- **Mic through EasyEffects:** apps get the EasyEffects-processed mic
  ("Easy Effects Source"), so effects apply everywhere.
- **Effects per channel:** each channel has an **FX** toggle — on = through
  EasyEffects, off = dry. All on by default (today's sound). Apps get effects
  through their channel.
- **EasyEffects is its own strip** with its own volume, mute, meter and A1–A4
  toggles: FX-on channels play wherever it plays.
- **Per-channel Bass and Treble** knobs on every channel, independent of FX.
- The "Playing now" app list stays under the strips ("the rest of the applist
  that produces sound under this will stay").
- Four channels + Mic + All Audio. Games play on Desktop.

## Behaviour

### Live, two-way

- Any volume or mute change — hotkey, pavucontrol, GNOME Settings, or the window
  itself — appears in the window within a fraction of a second. A slider drag
  sets the same value the hotkeys set, on the same scale: the % shown must equal
  the % in the OSD and in `pactl get-sink-volume` (pactl's percentage, which is
  cubic, not linear).
- **No cached volumes.** Always read live values; never write back a remembered
  value (that exact bug existed in the hotkey script).

### Playing now

- Lists every app stream on any channel (pulse sink-inputs on one of our channel
  sinks), excluding our own plumbing: the `*_Audio_out` loopbacks, the All Audio
  loopback, any new loopbacks this design adds, and the daemon's ignore list
  (`IGNORE_APPS` in `bin/audio-router-daemon`). Rows appear and disappear as apps
  start and stop.
- **Moving an app:** clicking a channel button moves the live stream immediately
  (`pactl move-sink-input`) **and remembers it**, exactly like answering the
  routing popup: write `routes.json` using the daemon's identity rules
  (`identity_key()` — `application.process.binary` preferred, else
  `application.name`), then `audio-routes-apply --no-restart`. Reuse that logic.
- **New apps** (no route yet) appear on Desktop with a "new" marker.

### Output slots (A1–A4)

- Up to **4 output slots**. Each is bound to one output device, chosen by
  clicking the slot's name and picking from the real outputs present (speakers,
  headset, HDMI, …). A slot can also be set to **"Default output"**, which
  follows GNOME's default device — i.e. today's behaviour, where plugging in the
  headset moves sound to it.
- Every channel strip with FX **off**, and the EasyEffects strip, has an A1…A4
  toggle row and can play on any combination of slots, including none. A channel
  with FX **on** shows "→ EasyEffects" instead of its own toggles: it plays where
  the EasyEffects strip plays. Turning FX off brings back that channel's own
  A1–A4 choice (remembered).
- **Fresh install / migration default:** one slot, A1 = "Default output", every
  channel FX on, EasyEffects on A1 — which sounds exactly like today.
- If a slot's device is unplugged, that slot shows as disconnected and audio sent
  only there is silent until it comes back. No surprise fallback for
  device-bound slots (the "Default output" option is the follow-the-plug choice).
- **All Audio stays "every channel at its level"**, independent of which slots the
  channels are on and of FX (a channel on no slot still appears in All Audio). It
  includes each channel's own Bass/Treble but not EasyEffects. Mic stays out of
  All Audio.
- Slot assignments, slot devices, FX toggles and Bass/Treble settings are saved
  and survive reboots and reinstalls (see constraints).

### Effects

- **FX toggle per channel** (Desktop, Discord, Music, Browser): on = the channel
  feeds EasyEffects' sink (`easyeffects_sink`, as every channel does today); off =
  it bypasses EasyEffects and plays on its own A1–A4 choice. Default: all on.
- **EasyEffects strip:** the output of EasyEffects (the user's current output
  preset) as a strip with volume, mute, meter and A1–A4. Its preset is chosen in
  EasyEffects itself; the strip may show the preset's name.
- **Bass and Treble per channel:** two knobs on every channel strip, centred =
  flat, working whether FX is on or off, independent per channel, applied live
  without audio gaps. Range and corner frequencies are the builder's call
  (something like ±12 dB shelves).
- Apps have no FX switch of their own; moving an app to a channel decides its
  effects.
- Toggling FX or moving the EasyEffects strip's slots must not need a PipeWire
  restart and must not jump the level (no burst of louder dry/wet audio).

### Mic

- Apps' default input is the EasyEffects mic (`easyeffects_source`), with the
  user's input effects.
- **What feeds EasyEffects' mic chain must always be a real microphone, never a
  monitor of an output.** Today it's fed by the speaker monitor
  (`alsa_output.pci-0000_00_1f.3.analog-surround-40` monitor — seen 2026-10-23
  with the headset unplugged), so apps would hear the speakers instead of the
  user. Making this impossible is part of this work.
- The Mic strip's name opens a picker of real microphones. Default (my call):
  the Blue headset mic when it's plugged in, otherwise the built-in input; it
  switches by itself on plug/unplug unless the user has pinned one.
- The Mic slider and mute act on the real microphone (so muted means nothing
  reaches the effects). **Mute must stay muted across a mic switch** (no hot mic
  after plugging the headset in).

### Hotkeys

- Right-click any of these to see and change its hotkey: a strip's **mute**,
  a strip's **slider** (two keys: volume down / up), a channel's **A1–A4
  toggles**, the Mic mute, All Audio mute. The popover shows the current
  combination; pressing a new combination replaces it; there's a way to clear it.
  Nothing else in that popover.
- The existing Ctrl+numpad bindings are the starting values and keep working.
  Changing a hotkey in the window takes effect immediately, system-wide (GNOME
  custom shortcuts, as `install.sh` sets them up today, recognised by their
  command), and works with the window closed.
- Hotkey presses keep showing the OSD, and the window mirrors the change.
- One source of truth for hotkeys, stored in `~/.config/audio-mixer/` (so it's
  backed up), which `install.sh` applies on a fresh system. Today that's the
  hotkey columns of `channels.conf`; the builder may move hotkeys to their own
  file since the new actions don't fit those columns.

### Window

- **Resize:** switching between B and C is automatic, by window width.
- Remembers its size and position. Follows the GNOME light/dark setting.
- While the window runs, the zenity "which channel?" popup is not shown — the
  window is where new apps get routed. When the window isn't running, the popup
  works as today.

## Constraints

- Machine: Ubuntu 24.04, GNOME on X11, PipeWire 1.0.5, WirePlumber 0.4.17,
  Python 3.12. GTK 3, GTK 4 and libadwaita introspection are all installed.
  EasyEffects 8.3.0 (Flatpak): settings in
  `~/.var/app/com.github.wwmm.easyeffects/config/easyeffects/db/easyeffectsrc`
  (`[StreamInputs] inputDevice`, `[StreamOutputs] outputDevice`), it keeps
  recent changes in memory until it quits, and it refuses to start after an
  unclean exit until its stale lock files are removed.
- **Plug and play:** installed and autostarted by `install.sh`, removed by
  `uninstall.sh`, no dependencies beyond apt packages. All new user state (slots,
  hotkeys, mic choice, window geometry) lives in `~/.config/audio-mixer/` so
  `audio-mixer-backup` covers it, and `install.sh` must rebuild everything from
  it on a fresh system.
- **Channel list comes from `channels.conf`** (key `default` = the catch-all;
  label shown on screen). Nothing hardcodes channel or device names. The All
  Audio node is `All_Audio` (see `bin/audio-routes-apply`).
- **The window is optional.** Routing, hotkeys (including new ones), output
  slots, mic routing, OSD, volume persistence and backups must keep working with
  the window closed or crashed. Any routing the window sets up must be either
  declarative (PipeWire config written by `audio-routes-apply`) or maintained by
  the daemon — not something that disappears when the window quits.
- **Startup display race:** anything launched at login must cope with DISPLAY not
  being in the systemd user environment yet (see `wait_for_display()` in
  `bin/audio-osd`). Single instance only.
- **PipeWire restarts are expensive here.** Never restart WirePlumber on its own
  (it drops every link and relinks nothing on this stack). A full PipeWire
  restart must go through `audio-routes-apply`'s sequence (quit EasyEffects,
  restart, wait 8 s, relaunch, verify). Prefer designs where changing a slot's
  device or a channel's slots does **not** need a PipeWire restart.
- **Per-channel EQ is possible with PipeWire's built-in filter-chain filters**
  (`type = builtin`, e.g. `bq_lowshelf` / `bq_highshelf`). Verified 2026-10-23: a
  filter-chain with a `bq_lowshelf` node ran as a standalone `pipewire -c <conf>`
  process and exposed live-adjustable controls (`bass:Freq`, `bass:Q`,
  `bass:Gain`) in its node Props. **LADSPA plugins do not load** in this PipeWire
  1.0.5 filter-chain — don't depend on them. If a filter-chain goes into
  `pipewire.conf.d`, it **must** carry `flags = [ nofail ]`: a failing mandatory
  module aborts PipeWire entirely (total audio outage, learned the hard way). Keep
  each `*.props` block on one line (PipeWire 1.0.x parser quirk).
- **Level meters:** active only while the window is visible; low CPU. Our pulse
  catch-all rule rewrites `target.object` for every pulse client by app name; a
  capture that names its device explicitly keeps it (verified), so pulse-based
  meters must always pass the device. Per-app meters can monitor one sink-input
  (`parec --monitor-stream=N`). Native PipeWire capture is fine too.

## Non-goals (v1)

- Editing EasyEffects presets or plugins inside the window — EasyEffects does
  that. The window's own EQ is only per-channel Bass/Treble.
- A second EasyEffects rack, or a per-app FX switch.
- Adding, removing or renaming channels from the window (edit `channels.conf`).
- Hotkeys for anything beyond the controls listed above; no action menus.
- Notifications of any kind (the user explicitly hates them).

## Anti-goals (failure even if it works)

- Anything jumping to full volume: the window starting up, reconnecting after a
  PipeWire restart, switching a slot's device, or showing a default 100% before
  real values load must never *write* a volume.
- Speaker or desktop sound leaking into the mic.
- A muted mic becoming live on its own.
- Fighting the hotkeys (stale values written back, sliders snapping back).
- The window becoming required for audio to work.
- A VoiceMeeter-style wall of options.

## My calls (the user can override)

- **Python + GTK 4 + libadwaita**, matching the project's Python and getting the
  wide/narrow switch from libadwaita's breakpoints.
- Clicking a channel for an app remembers the route (same as the popup).
- The popup is suppressed while the window runs.
- Sliders go 0–100%, like the hotkeys; moving a slider unmutes, like a hotkey
  up/down press.
- Strip meters show the level *after* the slider (what you hear from that
  channel). PipeWire sink monitors are pre-volume by default, so this needs care.
- The OSD keeps appearing on hotkey presses while the window is open.
- App-launcher entry + starts at login; closing quits (GNOME has no tray).
- Up to 4 output slots; "Default output" is a slot choice; fresh default = A1
  "Default output", every channel FX on, EasyEffects strip on A1.
- Per-channel EQ is just Bass + Treble (no wall of bands).
- All Audio includes each channel's Bass/Treble but not EasyEffects.
- (The user approved calls 2–6 of the first draft explicitly; the effects model
  replaced call 1 and was approved with the mockup.)
- Device-bound slots don't fall back when their device is unplugged.
- Mic default = headset mic when plugged, else built-in, auto-switching unless
  pinned; Mic slider/mute act on the real mic.

## Left to the builder

How output slots, FX bypass and the per-channel EQ are wired (per-slot mix
sinks, loopbacks, filter-chains, links), how EasyEffects' input and output
devices are kept pointed at the right places,
event plumbing (e.g. `pactl subscribe` vs native PipeWire), meter
implementation, how the daemon detects the window, the hotkey storage format,
visual polish, file layout, and tests.
