# Mixer Hotkeys Implementation Plan (part 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The spec's Hotkeys section: one hotkey file, hotkeys for every strip's mute and volume (Mic, channels, EasyEffects, All Audio) and for A1–A4 on channels and the EasyEffects strip, set in the window by right-clicking a control and pressing a combination — plus the muted-mic-stays-muted guarantee across reboots.

**Architecture:** `~/.config/audio-mixer/hotkeys.json` (`{action: accelerator}`) is the single source of truth; on first use it's created from channels.conf's numpad columns (today's keys). `audiomixer.hotkeys` turns it into GNOME custom shortcuts (recognised as ours by their command), adding NumLock-off twins for keypad keys exactly as install.sh does today. Volume/mute actions run the fast bash `audio-channel-control` (extended to Mic, EasyEffects, All Audio); A1–A4 toggles run `audio-mixer out … toggle`. The window's right-click popover edits the file and re-applies; while it captures a combination, our GNOME shortcuts are suspended so the keypress reaches the window. The daemon persists mute state next to volumes.

**Tech Stack:** Python 3.12, GTK 4 / libadwaita, bash, gsettings, stdlib unittest.

**Spec:** `docs/superpowers/specs/2026-10-23-mixer-window-design.md` (Hotkeys, Mic sections).

## Global Constraints

- Everything in parts 1 and 3 still holds (lightweight: no polling added; nothing written to volumes unasked; window optional).
- Action ids: `<target>:<what>` with target = a channel key, `mic`, `fx` (EasyEffects strip) or `all`; what = `mute`, `down`, `up` (any target) or `A1`–`A4` (channels and `fx`).
- Accelerators are GTK/GNOME strings (`<Ctrl>KP_1`). A combination is accepted only with Ctrl, Alt or Super, or when it's an F-key, keypad key or media key — plain letters would break typing. One combination belongs to one action: setting it elsewhere moves it.
- Hotkeys never unmute the Mic by changing its level (same as the window). Mic mute toggles absolutely from the live state.
- Mute buttons in the window send an absolute mute (`1`/`0` from the button's new state), not a relative toggle.
- Shortcut commands: volume/mute → `~/.local/bin/audio-channel-control <target> <mute|up|down>`; slots → `~/.local/bin/audio-mixer out <target> <A1-A4> toggle`.
- Mute state (all volume targets) persists across reboot with the volumes; a strip that was muted comes back muted.

## Review Focus

1. **Migration from today's keys:** an existing install keeps exactly its 21 numpad shortcuts after upgrading. → Task 1 `test_first_load_migrates_channels_conf_keys`.
2. **Capturing a combination that's already one of our shortcuts:** the keypress must reach the window (shortcuts suspended), and cancelling restores them. → Task 3 `test_capture_suspends_and_restores_shortcuts`.
3. **The user's own GNOME shortcuts are never touched.** → Task 1 `test_apply_keeps_foreign_shortcuts`.
4. **A muted mic after reboot / PipeWire restart stays muted.** → Task 4 `test_mutes_restored_with_volumes`.
5. **A combination reused for another action** moves, never duplicates. → Task 1 `test_setting_a_used_combination_moves_it`.

---

### Task 1: `audiomixer.hotkeys` + `audio-mixer hotkeys` CLI + installer uses it

**Files:** Create `lib/audiomixer/hotkeys.py`, `tests/test_hotkeys.py`; modify `lib/audiomixer/commands.py` (no), `bin/audio-mixer` (subcommand), `install.sh` (replace the inline keybinding Python with `audio-mixer hotkeys apply`), `uninstall.sh` (use `hotkeys.remove_from_gnome`).

**Interfaces:**
- `HOTKEYS_FILE`, `actions(channels) -> list[tuple[str, str]]` (`(action, label)` in display order: Mic, channels, EasyEffects, All Audio; each target's mute/down/up, then A1–A4 for channels and fx)
- `load(channels, path=None) -> dict[str, str]` (missing file → from channels.conf numpad columns; unknown actions dropped)
- `save(keys, path=None)`, `assign(keys, action, accel) -> dict` (moves a used combination; `None` clears), `acceptable(accel) -> bool`
- `bindings(keys, bin_dir) -> list[tuple[str, str, str]]` (name, command, accel), incl. NumLock-off twins
- `apply_to_gnome(bindings, gsettings=...)`, `remove_from_gnome(gsettings=...)` — ours = command contains `audio-channel-control` or `audio-mixer out`
- CLI: `audio-mixer hotkeys list | apply | set <action> <accel> | clear <action>`

- [ ] Tests (fake gsettings in memory): `test_first_load_migrates_channels_conf_keys` (21 bindings, same names/commands/keys as install.sh produced), `test_apply_keeps_foreign_shortcuts`, `test_setting_a_used_combination_moves_it`, `test_acceptable_rejects_plain_letters`, `test_slot_and_strip_commands`.
- [ ] Commit `Hotkeys: one hotkey file, GNOME shortcuts built from it`

### Task 2: Every strip's volume/mute from a key

**Files:** Modify `bin/audio-channel-control` (targets `mic` → Mic_In source, `fx` → EE_Return sink, `all` → All_Audio source; sources use `set-source-*`; the Mic's up/down never unmute; OSD label "Mic", "EasyEffects", "All Audio"), `tests/test_channel_control.py` (fake pactl on PATH).

- [ ] Tests: `test_mic_up_never_unmutes`, `test_fx_and_all_use_their_nodes`, `test_unknown_target_does_nothing`.
- [ ] Commit `Hotkeys: Mic, EasyEffects and All Audio volume/mute`

### Task 3: Right-click a control to set its hotkey

**Files:** Create `lib/audiomixer/ui/hotkeys.py` (popover); modify `strip.py` (right-click on mute → `<target>:mute`, on the fader → down/up pair, on A1–A4 toggles → `<target>:A<n>`), `controller.py` (`hotkeys`, `set_hotkey(action, accel)`, `suspend_hotkeys()`, `resume_hotkeys()`), tests.

- Popover: one row per action ("Volume down  Ctrl+KP 4  [Change] [Clear]"); Change → "Press a key combination… (Esc cancels)", captures via `Gtk.EventControllerKey` with our shortcuts suspended; unacceptable combinations show why; resume on finish/cancel/close.

- [ ] Tests: `test_right_click_targets` (each control maps to the right actions), `test_capture_suspends_and_restores_shortcuts`, `test_capture_saves_and_applies`, `test_escape_cancels`.
- [ ] Commit `Window: right-click a control to set its hotkey`

### Task 4: Mutes survive reboots; absolute mute buttons

**Files:** Modify `bin/audio-router-daemon` (snapshot/restore mute with volume: `volumes.json` gets `"_mute": {node: bool}`; legacy int-only files still load), `lib/audiomixer/ui/strip.py` + `controller.py` (`set_mute(name, kind, on)`), tests.

- [ ] Tests: `test_mutes_restored_with_volumes`, `test_old_volume_files_still_load`, `test_mute_button_sends_absolute_state`.
- [ ] Commit `Mutes survive reboots; mute buttons set an absolute state`

### Task 5: Install, docs, live check

- [ ] `./install.sh` (hotkeys.json migrated, 21 shortcuts unchanged), set one new hotkey from the window, press it (via `audio-channel-control`), clear it; README hotkey section; full suite.
- [ ] Commit `Hotkeys: install and docs`
