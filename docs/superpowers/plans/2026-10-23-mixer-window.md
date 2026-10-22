# Mixer Window Implementation Plan (part 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The window from the spec: GTK 4 + libadwaita, layout B when wide (strips + "Playing now"), layout C when narrow, live two-way with the hotkeys, FX / Bass-Treble / A1–A4 / slot and mic pickers, app routing with a "new" marker, the zenity popup suppressed while it runs, starting at login.

**Architecture:** The window is a thin view over code that already exists or is split out here into the `audiomixer` package. `commands` (moved out of `bin/audio-mixer`) changes routing state. `apps` (moved out of the daemon) remembers app→channel routes. `live` turns `pactl -f json` output into a snapshot of volumes, mutes and sounding apps. `meters` runs one low-rate `parec` per meter. `bin/audio-mixer-window` builds widgets from that model, refreshes on `pactl subscribe` events (debounced) and on `mixer.json` changes, and writes only on user action. The daemon keeps every job it has today; it only skips the zenity prompt while the window owns its D-Bus name.

**Tech Stack:** Python 3.12, PyGObject with GTK 4.14 + libadwaita 1.5 (installed), `pactl -f json`, `parec`, stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-23-mixer-window-design.md` (part 1 = `docs/superpowers/plans/2026-10-23-mixer-engine.md`, merged).

## Global Constraints

- Everything in part 1's Global Constraints still holds (no new pip deps, nothing written to volumes unasked, never restart WirePlumber alone, plug and play via install.sh, state only in `~/.config/audio-mixer/`).
- The window is optional: hotkeys, routing, OSD, daemon, backups work with it closed or crashed.
- Volume % everywhere = pactl's percentage (cubic), 0–100, same as the hotkeys and OSD. Moving a slider unmutes that strip.
- No cached volumes: the window never writes a value it didn't just get from the user's hand.
- Strip meters show the level after the strip's slider: `peak(monitor) × (volume%/100)³` for sinks (monitors are pre-volume); sources (Mic_In, All_Audio) are metered directly.
- Meters run only while the window is visible and not minimized; every `parec` dies with the window.
- Application id / D-Bus name: `io.github.crazygogo42.AudioMixer` (single instance; the daemon checks this name).
- Wide ↔ compact: libadwaita breakpoint `max-width: 720sp`.
- Remembered: window size (`~/.config/audio-mixer/window.json`). GTK 4 has no window-positioning API, so position is left to GNOME (ruling).
- Bass/Treble: −12…+12 dB sliders (GTK has no dial widget; small sliders stand in for the mockup's knobs — ruling).
- Our own streams (`<sink>_out`, `EE_Return_out`, anything in `own_nodes`) and the daemon's `IGNORE_APPS` never appear in "Playing now".

## Review Focus

1. **Dragging a slider while events stream in** (hotkeys, pactl echo of our own writes): the slider never jumps back or writes a stale value. → Task 4 test `test_refresh_does_not_touch_a_slider_being_dragged`.
2. **PipeWire restarts or channels missing while the window is open:** no crash; strips show "—" and recover when nodes return. → Task 2 test `test_missing_node_is_reported_absent`, Task 4 live check.
3. **App streams appearing/vanishing, duplicates (Zen ×3), clicking a row whose stream just vanished:** rows update; a click on a gone stream is a no-op, not a crash. → Task 2 test `test_same_app_streams_are_one_row`, Task 6 test `test_move_of_vanished_stream_still_saves_route`.
4. **Meter processes outliving the window** (close, minimize, crash): none left. → Task 3 test `test_reader_stop_kills_process`, Task 7 live check.
5. **Wide and compact views drifting apart:** both always show the same values. → Task 7 test `test_compact_and_wide_show_same_volume`.

---

### Task 1: Split shared logic into the package; daemon skips the prompt while the window runs

**Files:**
- Create: `lib/audiomixer/commands.py` (move `apply_command`, `status_dict`, `devices_list` and the write path of `main` from `bin/audio-mixer`), `lib/audiomixer/apps.py`, `tests/test_apps.py`
- Modify: `bin/audio-mixer` (thin wrapper), `tests/test_cli.py` (import from `audiomixer.commands`), `bin/audio-router-daemon` (use `audiomixer.apps`; `should_prompt`), `tests/test_daemon_helpers.py`

**Interfaces:**
- `audiomixer.commands`: `apply_command(argv, channels, state) -> MixerState`, `status_dict(channels, state, graph) -> dict`, `devices_list(channels, graph) -> list[dict]`, `run(argv: list[str]) -> None` (locked update + reconcile + EQ; raises `ValueError` on bad input)
- `audiomixer.apps`: `ROUTES_FILE`, `IGNORE_APPS` (moved from the daemon), `load_routes(path=ROUTES_FILE) -> dict`, `save_routes(data, path=ROUTES_FILE)`, `identity(props: dict) -> tuple[str, str] | None` (binary preferred, then `application.name`, then `node.name`, as `identity_key` today), `is_known(routes, props) -> bool`, `remember(props: dict, sink: str, path=ROUTES_FILE) -> None` (writes the route, mapping the catch-all sink like any other), `route_now(index: int, sink: str) -> None` (`pactl move-sink-input` + `audio-routes-apply --no-restart`)
- Daemon: `WINDOW_ID = "io.github.crazygogo42.AudioMixer"`, `window_running() -> bool` (D-Bus `NameHasOwner` via `gdbus`), `should_prompt(window_is_running: bool) -> bool`

- [ ] Tests: moved CLI tests pass unchanged against `audiomixer.commands`; `test_apps.py`: `test_identity_prefers_binary_then_app_then_node`, `test_remember_writes_route_and_keeps_other_entries`, `test_is_known_counts_ignore_list`; daemon: `test_no_prompt_while_window_runs`.
- [ ] RED → implement → GREEN; whole suite green; daemon behaviour unchanged when the window isn't running.
- [ ] Commit `Move CLI commands and app routes into the package; no popup while the window runs`

### Task 2: Live snapshot (`audiomixer.live`)

**Files:** Create `lib/audiomixer/live.py`, `tests/test_live.py`

**Interfaces:**
- `@dataclass StripLive: name: str; kind: str ("sink"|"source"); present: bool; volume: int (0–150); muted: bool`
- `@dataclass AppRow: key: tuple[str, str] (identity); name: str; indexes: list[int]; sink: str; known: bool`
- `@dataclass Snapshot: strips: dict[str, StripLive]; apps: list[AppRow]`
- `strip_targets(channels) -> list[tuple[str, str]]`: Mic_In (source), each channel sink, EE_Return (sink), All_Audio (source) — display order
- `build_snapshot(sinks: list, sources: list, inputs: list, channels, routes) -> Snapshot` (pure, from `pactl -f json` lists); `read_snapshot(channels) -> Snapshot`
- Volume = first channel's `value_percent` as int; apps = sink-inputs on one of our channel sinks, minus own nodes / IGNORE_APPS, grouped by identity (sorted by name)

- [ ] Tests: `test_volume_and_mute_from_pactl_json`, `test_missing_node_is_reported_absent`, `test_own_streams_and_ignored_apps_are_not_listed`, `test_same_app_streams_are_one_row`, `test_unknown_app_is_marked_new`, `test_apps_on_ee_or_hardware_are_not_listed` (only our channel sinks).
- [ ] RED → GREEN; commit `Add live snapshot of strips and sounding apps`

### Task 3: Meters (`audiomixer.meters`)

**Files:** Create `lib/audiomixer/meters.py`, `tests/test_meters.py`

**Interfaces:**
- `peak(chunk: bytes) -> float` (s16le → 0.0–1.0), `post_fader(peak: float, volume_pct: int) -> float` (`peak × (pct/100)³`, clamped 0–1)
- `class MeterReader(threading.Thread)`: `MeterReader(args: list[str], on_level: Callable[[float], None])` where args are the parec source args (`["--device=X.monitor"]` or `["--monitor-stream=N"]`); runs `parec --raw --format=s16le --rate=8000 --channels=2 --latency-msec=50 <args>`, reads 800-byte chunks, calls `on_level(peak)`; `stop()` kills the process and joins.
- `meter_args(name, kind) -> list[str]`: sinks → `--device=<name>.monitor`, sources → `--device=<name>`

- [ ] Tests: `test_peak_of_known_samples` (bytes of [0, 16384, -32768] → 1.0), `test_silence_is_zero`, `test_post_fader_is_cubic` (`post_fader(1.0, 50) == 0.125`), `test_reader_stop_kills_process` (fake `parec` on PATH that streams forever; after `stop()` its pid is gone).
- [ ] RED → GREEN; commit `Add level meters`

### Task 4: Window skeleton — strips with live volume/mute (wide layout)

**Files:** Create `bin/audio-mixer-window`, `lib/audiomixer/ui/__init__.py`, `lib/audiomixer/ui/strip.py`, `lib/audiomixer/ui/controller.py`, `tests/test_ui.py` (skipped without a display)

**Interfaces:**
- `Controller(channels)`: holds the latest `Snapshot` + `status_dict`; `refresh()` (reads both, notifies views), `set_volume(name, kind, pct)` (`pactl set-<kind>-volume <name> <pct>%` + unmute), `toggle_mute(name, kind)`, `subscribe(view)`; event thread on `pactl subscribe` → `GLib.timeout_add(80, refresh)` debounce; `mixer.json` mtime checked every 1 s.
- `StripWidget(controller, name, kind, label)`: vertical `Gtk.Scale` (0–100, inverted), `Gtk.LevelBar` (vertical, inverted), % label, Mute `Gtk.ToggleButton`; `update(strip_live)`; while the user drags (`Gtk.GestureClick` pressed/released on the scale) updates from refresh are ignored for that scale.
- `MixerWindow(Adw.ApplicationWindow)`: header bar + strips row (Mic | channels | EasyEffects | All Audio, separators); env `AUDIO_MIXER_SNAPSHOT=<png>` renders the window to a PNG after the first refresh and quits (for screenshots/tests).

- [ ] Tests: `test_window_builds_one_strip_per_target`, `test_refresh_does_not_touch_a_slider_being_dragged`, `test_strip_shows_dash_when_absent`.
- [ ] Live: open the window, snapshot PNG, look at it; `audio-channel-control music up` then `down` → slider follows within 1 s; drag-equivalent `controller.set_volume` → `pactl` shows it; restore.
- [ ] Commit `Mixer window: strips with live volume and mute`

### Task 5: FX, Bass/Treble, A1–A4, slot and mic pickers

**Files:** Modify `lib/audiomixer/ui/strip.py`, `controller.py`, `bin/audio-mixer-window`; tests in `tests/test_ui.py`

- Channel strips: FX `Gtk.ToggleButton`; Bass/Treble small horizontal `Gtk.Scale`s (−12…+12, step 0.5, applied on release / debounced 150 ms → `commands.run(["eq", key, "bass", v])`); A1–A4 toggles when FX off, "→ EasyEffects" label when FX on.
- EasyEffects strip: A1–A4 toggles (`out fx …`), shows the preset name (`[Presets] lastLoadedOutputPreset` from the EasyEffects rc; hidden if unreadable).
- Slots bar under the header: four `Gtk.MenuButton`s "A1 · <description or Default output/none>", popover = "Default output", each `devices_list` output, "None" → `commands.run(["slot", …])`.
- Mic strip title = `Gtk.MenuButton`: "Auto (<picked>)", each mic → `commands.run(["mic", …])`.
- Every change goes through `commands.run` (locked, reconciled); the view updates from the next refresh, not optimistically.

- [ ] Tests: `test_fx_off_shows_slot_toggles`, `test_fx_on_shows_ee_label`, `test_slot_menu_lists_default_devices_and_none`.
- [ ] Live: FX toggle, A2 = HDMI for Browser, EQ ±, mic menu shows the built-in mic; undo all.
- [ ] Commit `Mixer window: FX, Bass/Treble, outputs and mic`

### Task 6: "Playing now"

**Files:** Create `lib/audiomixer/ui/apps.py`; modify controller/window; tests

- `Gtk.ListBox` rows: name + "new" pill (unknown app) + horizontal `Gtk.LevelBar` (per-app meter on the first stream) + linked toggle group, one button per channel (label), the current one active.
- Click → `apps.remember(props, sink)` then `apps.route_now(i, sink)` for every index in the row; if the stream vanished, the route is still saved (no crash).

- [ ] Tests: `test_rows_follow_snapshot`, `test_new_app_has_marker`, `test_move_of_vanished_stream_still_saves_route` (controller with fake pactl failing the move).
- [ ] Live: Zen row shows Browser active; click Browser (no-op) only — no real move.
- [ ] Commit `Mixer window: Playing now app list`

### Task 7: Compact layout, meter lifecycle, size memory

**Files:** Create `lib/audiomixer/ui/compact.py`; modify window/controller; tests

- `Adw.Breakpoint("max-width: 720sp")` sets a `Gtk.Stack` to the compact page: rows (label, horizontal scale, %, mute) + small app names under each channel.
- Meters: one `MeterReader` per visible strip + per app row's first stream; started when the window is mapped and not minimized (`Gdk.Toplevel` state), stopped on minimize/close; meter levels go to the UI via `GLib.idle_add` at most ~15 Hz.
- Size saved to `window.json` on close; restored on start.

- [ ] Tests: `test_compact_and_wide_show_same_volume`, `test_size_round_trips`.
- [ ] Live: narrow → compact snapshot PNG; minimize → `pgrep -c parec` = 0; close → 0.
- [ ] Commit `Mixer window: compact layout, meters, remembered size`

### Task 8: Install, launcher, autostart, docs, final checks

**Files:** Modify `install.sh` (deps `gir1.2-gtk-4.0 gir1.2-adw-1` if `gi.require_version('Adw','1')` fails; copy `audio-mixer-window`; `~/.local/share/applications/audio-mixer.desktop`; `~/.config/autostart/audio-mixer-window.desktop` with `X-GNOME-Autostart-enabled=true`), `uninstall.sh`, `README.md`

- [ ] Run the whole suite; `./install.sh`; launch from the launcher entry; screenshots wide + compact; the zenity popup doesn't appear while the window runs (daemon log/behaviour) and does when it's closed.
- [ ] Commit `Install the mixer window with launcher and autostart`
