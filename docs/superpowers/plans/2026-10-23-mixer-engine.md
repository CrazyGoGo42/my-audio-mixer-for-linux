# Mixer Engine Implementation Plan (part 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the audio graph so every channel has its own Bass/Treble, an FX on/off switch and A1–A4 output slots; EasyEffects becomes a strip with its own outputs; the mic always reaches EasyEffects from a real microphone; All Audio keeps carrying every channel. All of it is controllable from a new `audio-mixer` command and kept wired by the daemon, and none of those changes needs a PipeWire restart.

**Architecture:** PipeWire creates a fixed set of nodes at startup: one filter-chain per channel (sink + Bass/Treble + output), `EE_Return` (EasyEffects' output), `Mic_In` (the mic EasyEffects listens to) and `All_Audio`. Their outputs are created with `node.autoconnect = false`, so WirePlumber never links or relinks them. The daemon is the patchbay. It reads the wanted routing from `~/.config/audio-mixer/mixer.json`, compares it with the live graph (`pw-dump`), and adds or removes links with `pw-link`. Toggling FX, picking outputs or switching mics only changes links; Bass/Treble only changes filter parameters (`pw-cli set-param`). Neither needs a restart, and WirePlumber's relinking never runs on our nodes, which is what caused the stuck-channel bug.

**Tech Stack:** Python 3.12 stdlib only (tests: `unittest`), PipeWire 1.0.5 CLI tools (`pw-dump`, `pw-link`, `pw-cli`, `pactl`), bash installer.

**Spec:** `docs/superpowers/specs/2026-10-23-mixer-window-design.md`

**Parts:** this plan is the engine. Part 2 (hotkeys you set by right-clicking) and part 3 (the GTK window) get their own plans once this one has landed. Both consume the `audio-mixer` CLI and the `audiomixer` package defined here.

## Global Constraints

- Ubuntu 24.04, GNOME/X11, PipeWire 1.0.5, WirePlumber 0.4.17, Python 3.12, EasyEffects 8.3.0 Flatpak (`com.github.wwmm.easyeffects`). No new apt or pip dependencies.
- Plug and play: everything the user sets lives in `~/.config/audio-mixer/` (covered by `audio-mixer-backup`), and `install.sh` rebuilds the full setup from it on a fresh system. `uninstall.sh` undoes it.
- The channel list comes only from `~/.config/audio-mixer/channels.conf` (key `default` = the catch-all). Never hardcode channel names.
- **Never restart WirePlumber alone.** A full PipeWire restart only ever happens through `audio-routes-apply`'s sequence (quit EasyEffects, restart all three services, wait 8 s, relaunch EasyEffects, verify).
- Every filter-chain or loopback in `pipewire.conf.d` carries `flags = [ nofail ]` (a failing mandatory module takes all of PipeWire down), and each `*.props` block stays on one line (PipeWire 1.0.x parser quirk). Don't use LADSPA plugins; they don't load on this PipeWire. Use `type = builtin` filters.
- Nothing may *write* a volume unless the user asked for that change. No defaults of 100% are applied on startup or reconnect.
- Never link anything into one of our own sinks from our own outputs (no loops), and never feed `Mic_In` from a monitor of an output.
- Output slots: `A1`–`A4`. Slot values: a device node name, `"@default"` (follows GNOME's default output) or `null` (unset). Fresh/migrated state: `A1 = "@default"`, every channel `fx: true, outputs: ["A1"], bass: 0, treble: 0`, `fx_outputs: ["A1"]`, `mic: "@auto"` — which sounds exactly like today.
- Bass = `bq_lowshelf` at 100 Hz, Treble = `bq_highshelf` at 8000 Hz, both Q 0.7, gain clamped to −12…+12 dB.
- Mic auto-pick: a USB microphone if one is present, else the first other hardware input; never a monitor, never a virtual source.
- Channel ports map by name (FL→FL, FR→FR). A mono source (`MONO`) feeds both FL and FR. Extra device channels (RL, RR, …) are left unlinked, as today.
- Tests run with `python3 -m unittest discover -s tests -v` from the repo root; they must not touch the live audio graph.
- The spec says the Mic strip's slider and mute act on "the real microphone" so that muted means nothing reaches the effects and the mute survives a mic switch. This plan meets that through `Mic_In`, the one stable node every real mic feeds. Its volume and mute (used by part 3) gate everything going into EasyEffects, and they stay put when the daemon switches which mic feeds it.

## Review Focus

1. **EasyEffects crashes or restarts** (`easyeffects_sink` and `EE_Return` disappear and come back): FX channels must go silent, never fall back to raw hardware at a different level, and must be relinked within a few seconds of EasyEffects returning. → Task 4 test `test_fx_channel_without_ee_sink_gets_no_links`, Task 8 live check.
2. **Headset plugged or unplugged while a slot is `@default`:** the links follow the new default device. A device-bound slot whose device is gone plays nothing. → Task 4 tests `test_default_slot_follows_default_sink`, `test_missing_device_slot_is_silent`.
3. **The default sink becomes one of our own nodes** (e.g. all hardware gone and WirePlumber picks a channel sink): no link may be made into our own nodes. → Task 4 test `test_default_sink_pointing_at_our_node_links_nothing`.
4. **A mono or unusual mic** (`MONO` port, or a stereo mic): `Mic_In` gets sound on both channels. → Task 4 test `test_mono_mic_feeds_both_channels`.
5. **A hand-edited or corrupt `mixer.json`**, or a channel added to `channels.conf` later: load falls back to defaults per missing field, never crashes the daemon, and never overwrites the file just because it read it. → Task 2 tests `test_corrupt_state_loads_defaults`, `test_new_channel_gets_default_state`.

---

### Task 1: Spike — prove the graph mechanisms on this machine

Throwaway check. If any assertion fails, **stop and report** before continuing: the architecture depends on all of them. It runs in its own short-lived `pipewire -c` process (like the 2026-10-23 EQ test), so the system config isn't touched.

**Files:**
- Create: `tests/spike/engine-spike.conf`, `tests/spike/engine-spike.sh` (kept in the repo as a diagnostic)

- [ ] **Step 1: Write `tests/spike/engine-spike.conf`.** It's a standalone PipeWire client config (same module list as the 2026-10-23 EQ test: rt with `ifexists nofail`, protocol-native, client-node, adapter) holding one filter-chain: capture `{ node.name = "spike_ch" media.class = "Audio/Sink" audio.position = [ FL FR ] }`, graph `bass` (`bq_lowshelf`, Freq 100, Q 0.7, Gain 0) → `treble` (`bq_highshelf`, Freq 8000, Q 0.7, Gain 0) linked `bass:Out` → `treble:In`, playback `{ node.name = "spike_ch_out" node.passive = true node.autoconnect = false }`. Add one loopback whose capture is `{ node.name = "spike_mix_in" node.autoconnect = false audio.position = [ FL FR ] }` and whose playback is `{ node.name = "spike_mix" media.class = "Audio/Source" audio.position = [ FL FR ] }`.

- [ ] **Step 2: Write `tests/spike/engine-spike.sh`.** It starts `pipewire -c` with that config in the background, waits 2 s, prints `PASS`/`FAIL` for each check below, kills the process and confirms that no `spike_` node remains:
  1. `spike_ch_out` has ports `output_FL` and `output_FR` while nothing has linked it (proves autoconnect=false still exposes ports).
  2. It has **zero links** after 3 s (WirePlumber left it alone).
  3. `pw-link spike_ch_out:output_FL easyeffects_sink:playback_FL` and the same into `spike_mix_in:input_FL` both succeed. One output then has two links (fan-out).
  4. The links still exist 2 s after `pw-link` exits (linger).
  5. `pw-cli set-param <spike_ch id> Props '{ params = [ "bass:Gain" 6.0 ] }'` and then `pw-dump` shows `bass:Gain` = 6.0 on `spike_ch`.
  6. `spike_mix` is listed by `pactl list sources short`.

- [ ] **Step 3: Run it**

Run: `bash tests/spike/engine-spike.sh`
Expected: six `PASS` lines, then `cleanup ok`.

- [ ] **Step 4: Commit** (first commit the pending work from 2026-10-22/23, then the spike)

```bash
git add .gitignore README.md install.sh uninstall.sh bin/ config/ docs/superpowers/specs/
git commit -m "Shared channel list, backups, 4 channels + All Audio, safer PipeWire restarts"
git add tests/spike/
git commit -m "Add engine spike: autoconnect=false fan-out, linger, live EQ params"
```

---

### Task 2: `audiomixer` package — channels and mixer state

**Files:**
- Create: `lib/audiomixer/__init__.py` (empty), `lib/audiomixer/config.py`, `tests/__init__.py`, `tests/test_config.py`
- Modify: `bin/audio-router-daemon`, `bin/audio-route-apps`, `bin/audio-routes-apply` (replace their private `load_channels()` with the package), `install.sh` (copy `lib/audiomixer` to `~/.local/lib/audio-mixer/audiomixer`), `uninstall.sh` (remove `~/.local/lib/audio-mixer`)

**Interfaces:**
- Produces (in `audiomixer.config`):
  - Constants: `MIXER_DIR`, `CHANNELS_FILE`, `STATE_FILE` (`~/.config/audio-mixer/mixer.json`), `SLOTS = ("A1", "A2", "A3", "A4")`, `DEFAULT_OUTPUT = "@default"`, `AUTO_MIC = "@auto"`, `EE_SINK = "easyeffects_sink"`, `EE_SOURCE = "easyeffects_source"`, `EE_RETURN = "EE_Return"`, `MIC_IN = "Mic_In"`, `ALL_AUDIO = "All_Audio"`, `EQ_LIMIT_DB = 12.0`
  - `@dataclass(frozen=True) class Channel: key: str; sink: str; label: str; hotkeys: tuple[str, str, str]` (mute, down, up; `"-"` = none)
  - `load_channels(path: str = CHANNELS_FILE) -> list[Channel]`, `catch_all(channels: list[Channel]) -> Channel` (raises `ValueError` if there's no `default` key)
  - `@dataclass class ChannelState: fx: bool = True; outputs: list[str] = ["A1"]; bass: float = 0.0; treble: float = 0.0` (use `field(default_factory=...)`)
  - `@dataclass class MixerState: slots: dict[str, str | None]; channels: dict[str, ChannelState]; fx_outputs: list[str]; mic: str`
  - `load_state(channels: list[Channel], path: str = STATE_FILE) -> MixerState`, `save_state(state: MixerState, path: str = STATE_FILE) -> None` (atomic: tmp + `os.replace`)
- Every script finds the package by trying `<script dir>/../lib`, then `~/.local/lib/audio-mixer`, before importing.

- [ ] **Step 1: Write the failing tests in `tests/test_config.py`** (use `tempfile` paths, never the real `~/.config`)

```python
def test_parses_channels_conf_with_multiword_label_and_comments(self):
    # line: "voice  Voice_Chat  -  KP_5  KP_8  Voice Chat  # note"
    ch = load_channels(p)[-1]
    self.assertEqual((ch.key, ch.sink, ch.label, ch.hotkeys), ("voice", "Voice_Chat", "Voice Chat", ("-", "KP_5", "KP_8")))

def test_catch_all_is_key_default(self):
    self.assertEqual(catch_all(load_channels(p)).sink, "Default_Audio")

def test_missing_state_file_gives_todays_sound(self):
    s = load_state(chs, missing_path)
    self.assertEqual(s.slots, {"A1": "@default", "A2": None, "A3": None, "A4": None})
    self.assertTrue(all(c.fx and c.outputs == ["A1"] and c.bass == 0 and c.treble == 0 for c in s.channels.values()))
    self.assertEqual((s.fx_outputs, s.mic), (["A1"], "@auto"))

def test_corrupt_state_loads_defaults(self):          # file contains "{not json"
    s = load_state(chs, p)
    self.assertEqual(s.fx_outputs, ["A1"])
    self.assertEqual(open(p).read(), "{not json")     # never rewritten by a load

def test_new_channel_gets_default_state(self):        # state file only knows "music"
    self.assertTrue(load_state(chs_with_new, p).channels["discord"].fx)

def test_eq_values_are_clamped_on_load(self):         # file says bass 40
    self.assertEqual(load_state(chs, p).channels["music"].bass, 12.0)

def test_unknown_slot_names_are_dropped_from_outputs(self):  # outputs ["A1", "B7"]
    self.assertEqual(load_state(chs, p).channels["music"].outputs, ["A1"])

def test_save_then_load_round_trips(self): ...
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python3 -m unittest tests.test_config -v`
Expected: FAIL / ImportError (`audiomixer` not found). Tests add `lib/` to `sys.path` and set `sys.dont_write_bytecode = True`.

- [ ] **Step 3: Implement `lib/audiomixer/config.py`** with the interface above. `load_channels` keeps today's parsing rules: strip `#…`, at least 6 columns, label = columns 6+.

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_config -v`
Expected: all PASS.

- [ ] **Step 5: Switch the three scripts to `audiomixer.config.load_channels`/`catch_all`, and add the lib copy to `install.sh` / the removal to `uninstall.sh`.** Verify that behaviour is unchanged:

Run: `HOME=$(mktemp -d) bash -c 'mkdir -p $HOME/.config/audio-mixer && cp config/channels.conf config/routes.json $HOME/.config/audio-mixer/ && python3 -B bin/audio-routes-apply --no-restart && cat $HOME/.config/pipewire/pipewire-pulse.conf.d/50-audio-mixer-routing.conf'`
Expected: the same pulse rules as `~/.config/pipewire/pipewire-pulse.conf.d/50-audio-mixer-routing.conf` today (byte-identical when given the user's routes.json).

- [ ] **Step 6: Commit**

```bash
git add lib/ tests/ bin/ install.sh uninstall.sh
git commit -m "Add audiomixer package: shared channel list and mixer state"
```

---

### Task 3: Live graph snapshot (`pw-dump` parser)

**Files:**
- Create: `lib/audiomixer/pwgraph.py`, `tests/test_pwgraph.py`, `tests/pwfake.py` (builds synthetic pw-dump lists for tests)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Port: node: str; name: str; direction: str; channel: str; monitor: bool` (`direction` is `"in"` or `"out"`; `channel` comes from `audio.channel`)
  - `@dataclass class Node: id: int; name: str; media_class: str; props: dict`
  - `@dataclass class Graph: nodes: dict[str, Node]; ports: dict[str, list[Port]]; links: set[tuple[str, str]]; default_sink: str | None; default_source: str | None` — links are `("node:port", "node:port")`, output first.
  - `parse_dump(dump: list[dict]) -> Graph`, `read_graph() -> Graph` (runs `pw-dump`, returns an empty Graph on failure)
  - `tests/pwfake.py`: `node(id, name, media_class, **props)`, `port(id, node_id, name, direction, channel, monitor=False)`, `link(out_node_id, out_port_id, in_node_id, in_port_id)`, `defaults(sink=None, source=None)`, which mirror the real shapes: Port `info.props` keys `port.name`, `port.direction`, `node.id`, `audio.channel`, `port.monitor`; Link `info` keys `output-node-id`, `output-port-id`, `input-node-id`, `input-port-id`; Metadata `props["metadata.name"] == "default"` with entries `{"key": "default.audio.sink", "value": {"name": …}}`.

- [ ] **Step 1: Write failing tests**

```python
def test_ports_grouped_by_node_name_with_channel_and_direction(self):
    g = parse_dump([node(47, "Music_Audio_out", "Stream/Output/Audio"), port(120, 47, "output_FL", "out", "FL")])
    self.assertEqual(g.ports["Music_Audio_out"], [Port("Music_Audio_out", "output_FL", "out", "FL", False)])

def test_links_resolved_to_port_names(self):
    self.assertIn(("Music_Audio_out:output_FL", "easyeffects_sink:playback_FL"), g.links)

def test_default_sink_and_source_from_metadata(self):
    self.assertEqual((g.default_sink, g.default_source), ("alsa_output.x", "easyeffects_source"))

def test_dangling_link_to_unknown_port_is_ignored(self): ...
def test_empty_or_garbage_dump_gives_empty_graph(self): ...
```

- [ ] **Step 2: Run it to make sure it fails** — `python3 -m unittest tests.test_pwgraph -v` → FAIL (module missing).
- [ ] **Step 3: Implement `lib/audiomixer/pwgraph.py`.**
- [ ] **Step 4: Run it** — all PASS. Also run `python3 -B -c "import sys; sys.path.insert(0,'lib'); from audiomixer.pwgraph import read_graph; g=read_graph(); print(len(g.nodes), g.default_sink)"` → a node count above 10 and `alsa_output.pci-0000_00_1f.3.analog-surround-40`.
- [ ] **Step 5: Commit** — `git commit -m "Add pw-dump graph parser"`

---

### Task 4: Desired routing (pure)

**Files:**
- Create: `lib/audiomixer/routing.py`, `tests/test_routing.py`

**Interfaces:**
- Consumes: `Channel`, `MixerState`, constants (Task 2); `Graph`, `Port` (Task 3)
- Produces:
  - `own_nodes(channels) -> set[str]`: every node name this project creates (`<sink>`, `<sink>_out`, `EE_Return`, `EE_Return_out`, `Mic_In`, `Mic_In_in`, `All_Audio`, `All_Audio_in`)
  - `managed_nodes(channels) -> set[str]`: the nodes whose links the daemon owns (`<sink>_out`, `EE_Return_out`, `Mic_In_in`, `All_Audio_in`)
  - `resolve_slot(value: str | None, graph: Graph, own: set[str]) -> str | None`: `@default` → `graph.default_sink`; a name → itself if present in `graph.nodes`; otherwise, or if the result is in `own`, `None`
  - `pick_mic(state: MixerState, graph: Graph) -> str | None`: `@auto` → a USB hardware input (`device.bus == "usb"` on the node, `media.class == "Audio/Source"`, `device.api == "alsa"` or `"bluez5"`), else the first such hardware input; a pinned name → itself if present. Never a monitor, `Audio/Source/Virtual`, or any of our own nodes.
  - `port_pairs(out_node: str, in_node: str, graph: Graph) -> list[tuple[str, str]]`: out ports (non-monitor) matched to in ports by channel; `MONO` out → every in port; unmatched in ports stay unlinked
  - `desired_links(channels, state, graph) -> set[tuple[str, str]]`:
    - each channel's `<sink>_out` → `All_Audio_in`, always
    - `fx: true` → `<sink>_out` → `easyeffects_sink` (if present, else nothing)
    - `fx: false` → `<sink>_out` → `resolve_slot(state.slots[s])` for each `s` in `outputs`
    - `EE_Return_out` → `resolve_slot(...)` for each slot in `state.fx_outputs`
    - `pick_mic(...)` → `Mic_In_in`

- [ ] **Step 1: Write failing tests** (graphs built with `tests/pwfake.py`)

```python
def test_todays_defaults_route_all_channels_through_ee_and_ee_to_default_device(self): ...
def test_fx_off_channel_goes_to_its_slots_not_ee(self): ...
def test_every_channel_feeds_all_audio_regardless_of_fx_and_slots(self): ...   # incl. outputs == []
def test_fx_channel_without_ee_sink_gets_no_links(self):                       # Review Focus 1
    self.assertFalse({l for l in desired_links(chs, st, g_no_ee) if l[0].startswith("Music_Audio_out") and not l[1].startswith("All_Audio_in")})
def test_default_slot_follows_default_sink(self): ...                          # Review Focus 2
def test_missing_device_slot_is_silent(self): ...                              # Review Focus 2
def test_default_sink_pointing_at_our_node_links_nothing(self):                # Review Focus 3
    self.assertIsNone(resolve_slot("@default", g_default_is_Default_Audio, own_nodes(chs)))
def test_mono_mic_feeds_both_channels(self):                                   # Review Focus 4
    self.assertEqual(port_pairs("usbmic", "Mic_In_in", g), [("usbmic:capture_MONO", "Mic_In_in:input_FL"), ("usbmic:capture_MONO", "Mic_In_in:input_FR")])
def test_auto_mic_prefers_usb_and_never_picks_a_monitor_or_ee_source(self): ...
def test_pinned_mic_absent_means_no_mic(self): ...
def test_four_channel_device_gets_front_pair_only(self): ...
```

- [ ] **Step 2: Run** — `python3 -m unittest tests.test_routing -v` → FAIL.
- [ ] **Step 3: Implement `lib/audiomixer/routing.py`.**
- [ ] **Step 4: Run** — all PASS.
- [ ] **Step 5: Commit** — `git commit -m "Compute desired mixer links from state and live graph"`

---

### Task 5: Reconcile — apply the difference with `pw-link`

**Files:**
- Create: `lib/audiomixer/reconcile.py`, `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `desired_links`, `managed_nodes` (Task 4), `read_graph` (Task 3), `load_channels`/`load_state` (Task 2)
- Produces:
  - `plan_changes(desired: set, graph: Graph, managed: set[str]) -> tuple[set, set]`: `(to_add, to_remove)`. Remove only actual links where the output node is in `managed`, or the input node is `Mic_In_in`/`All_Audio_in`, and that aren't desired. Never touch other links.
  - `apply_changes(to_add, to_remove) -> list[str]`: runs `pw-link <out> <in>` / `pw-link -d <out> <in>` and returns error lines (doesn't raise)
  - `reconcile_once() -> tuple[int, int]`: reads channels, state and graph, plans, applies, returns `(added, removed)`

- [ ] **Step 1: Write failing tests**

```python
def test_adds_missing_and_removes_stale_managed_links(self): ...
def test_never_removes_links_of_unmanaged_nodes(self):      # app -> Music_Audio, EE internal links
    self.assertFalse({l for l in to_remove if l[0].startswith(("Zen:", "ee_soe"))})
def test_removes_wireplumber_fallback_link_from_channel_out_to_hardware(self): ...
def test_noop_when_graph_matches(self):
    self.assertEqual(plan_changes(desired, g_matching, managed), (set(), set()))
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Reconcile mixer links with pw-link"`

---

### Task 6: Generate the new node set (`virtual-sinks.conf`)

**Files:**
- Create: `lib/audiomixer/render.py`, `tests/test_render.py`
- Modify: `bin/audio-routes-apply` (use `render.render_sinks` / `render.render_routes`, delete its private copies; `--restart-pipewire` and the 8 s sequence stay; the post-restart check becomes "`reconcile_once()` then every channel's `_out` has at least one link")

**Interfaces:**
- Produces: `render_sinks(channels: list[Channel], state: MixerState) -> str`, `render_routes(by_channel: dict[str, list[tuple[str, str]]], default_sink: str) -> str` (moved verbatim from `audio-routes-apply`'s `render()`)
- Node set (descriptions in quotes):
  - per channel, `libpipewire-module-filter-chain`, `flags = [ nofail ]`, `node.description = "<label> Audio"`, capture `{ node.name = "<sink>" media.class = "Audio/Sink" audio.position = [ FL FR ] priority.session = 1 }`, graph as in Task 1 with `Gain` = the state's bass/treble, playback `{ node.name = "<sink>_out" node.passive = true node.autoconnect = false }`
  - `EE_Return` ("EasyEffects"): loopback, capture Audio/Sink `EE_Return` with `priority.session = 1`, playback `EE_Return_out` with `node.passive = true node.autoconnect = false`
  - `Mic_In` ("Mixer Mic"): loopback, capture `Mic_In_in` with `node.autoconnect = false node.passive = true`, playback Audio/Source `Mic_In`
  - `All_Audio` ("All Audio"): loopback, capture `All_Audio_in` with `node.autoconnect = false node.passive = true`, playback Audio/Source `All_Audio`
  - `priority.session = 1` keeps WirePlumber from choosing our sinks as the default output while hardware exists (Review Focus 3)

- [ ] **Step 1: Write failing tests**

```python
def test_every_module_is_nofail(self):  self.assertEqual(out.count("flags = [ nofail ]"), len(chs) + 3)
def test_props_blocks_are_single_line(self):  # no line contains "props = {" without its closing "}"
def test_no_ladspa(self):  self.assertNotIn("ladspa", out)
def test_channel_outputs_and_internal_inputs_are_not_autoconnected(self): ...  # 4 x _out, EE_Return_out, Mic_In_in, All_Audio_in
def test_eq_gains_come_from_state(self):  # music bass 6.5 -> '"Gain" = 6.5' inside Music's bass node
def test_routes_render_matches_previous_output(self):  # compare to a golden string copied from today's file
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, then wire it into `audio-routes-apply`. **Step 4: Run** → PASS.
- [ ] **Step 5: Sandbox render.** `HOME=$(mktemp -d)` run of `audio-routes-apply --no-restart` as in Task 2 Step 5; read the generated `virtual-sinks.conf` and confirm the node set above. Don't apply it live yet (Task 9 does the cutover).
- [ ] **Step 6: Commit** — `git commit -m "Generate filter-chain channels, EE_Return, Mic_In and All_Audio"`

---

### Task 7: EasyEffects device settings

**Files:**
- Create: `lib/audiomixer/easyeffects.py`, `tests/test_easyeffects.py`
- Modify: `bin/audio-routes-apply` and `bin/audio-mixer-backup` (use the package's quit/launch helpers instead of their own copies)

**Interfaces:**
- Produces:
  - `RC_FILE = ~/.var/app/com.github.wwmm.easyeffects/config/easyeffects/db/easyeffectsrc`, `APP = "com.github.wwmm.easyeffects"`
  - `set_devices(rc_text: str, input_device: str | None, output_device: str | None) -> str`: in `[StreamInputs]` sets `useDefaultInputDevice=false` and `inputDevice=<input>`; in `[StreamOutputs]` sets `useDefaultOutputDevice=false` and `outputDevice=<output>`; `None` means set `useDefault…=true` and leave the device key alone. Creates missing sections/keys and keeps everything else byte-for-byte.
  - `is_running() -> bool` (`pgrep -f "easyeffects --service-mode"`), `quit() -> None` (`flatpak run APP -q`, timeout 10, then `pkill` fallback), `launch() -> None` (clear `EasyEffectsServer` / `easyeffects.lock` in `/run/user/<uid>/.flatpak/APP/tmp`, then start `--service-mode --hide-window` detached)
  - `point_at_mixer() -> bool`: if the rc already says `Mic_In` / `EE_Return` with `useDefault…=false`, return False. Otherwise quit if running, rewrite the rc, relaunch if it was running, return True.

- [ ] **Step 1: Write failing tests**

```python
def test_sets_both_devices_and_disables_follow_default(self):  # on the user's real rc text (copied into the test as a string)
def test_keeps_presets_and_plugin_order_untouched(self):      # [Presets], plugins= lines identical
def test_adds_missing_keys_and_sections(self): ...
def test_none_restores_follow_default(self): ...
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "EasyEffects: point input at Mic_In and output at EE_Return"`

---

### Task 8: Daemon becomes the patchbay

**Files:**
- Modify: `bin/audio-router-daemon`, `lib/audiomixer/reconcile.py` (add `apply_eq`), `tests/test_reconcile.py`
- Create: `tests/test_daemon_helpers.py` (the daemon gets `if __name__ == "__main__"`-safe helpers that the test loads with `importlib.machinery.SourceFileLoader`)

**Interfaces:**
- Consumes: `reconcile_once` (Task 5), `read_graph` (Task 3), `load_state`, `own_nodes`
- Produces:
  - in the daemon: `skip_stream(node_name: str, own: set[str]) -> bool`: the "which channel?" prompt never asks about our own nodes
  - in `audiomixer.reconcile` (shared with the CLI in Task 9): `apply_eq(graph: Graph, channels, state) -> None`: `pw-cli set-param <id of <sink>> Props '{ params = [ "bass:Gain" <b> "treble:Gain" <t> ] }'`. The daemon calls it when a channel node's id differs from the last applied id (a new PipeWire instance) and whenever `mixer.json`'s mtime changes.
  - Volume persistence extended: the existing `volumes.json` snapshot/restore also covers the `EE_Return` sink and the `Mic_In` / `All_Audio` sources (`pactl get-/set-source-volume`); same restore-before-save rules
  - `fix_chain()` removed; `chain_watch` calls `reconcile_once()` every `CHAIN_POLL_SECONDS` (3 s) and right after each `pactl subscribe` event about sinks, sources or sink-inputs

- [ ] **Step 1: Write failing tests** for `skip_stream` (all names from `own_nodes`, plus `EE_Return_out`) and for `apply_eq`'s command line (patch `subprocess.run` and assert the exact argv).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "Daemon: reconcile mixer links, re-apply EQ, persist new strip volumes"`

---

### Task 9: `audio-mixer` CLI + live cutover

**Files:**
- Create: `bin/audio-mixer`, `tests/test_cli.py`
- Modify: `install.sh` (install `audio-mixer`; create `mixer.json` with defaults if missing; call `easyeffects.point_at_mixer()` after the PipeWire step; `pactl set-default-source easyeffects_source`), `uninstall.sh` (`set_devices(rc, None, None)` with EasyEffects quit and relaunched; remove `audio-mixer`), `README.md` (FX, slots, Bass/Treble, mic, CLI)

**Interfaces:**
- Produces:
  - `audio-mixer status [--json]`, `fx <channel> on|off|toggle`, `out <channel|fx> <A1-A4> on|off|toggle`, `slot <A1-A4> <device|default|none>`, `eq <channel> bass|treble <dB>`, `mic auto|<source>`, `devices [--json]` (the hardware outputs and mics present)
  - `apply_command(argv: list[str], channels, state) -> MixerState` (pure; raises `ValueError` with a one-line message on bad input), then `save_state` + `reconcile_once()` + (for `eq`) `apply_eq`
  - `status_dict(channels, state, graph) -> dict` — **the window (part 3) consumes this exact JSON:** `{"slots": {"A1": {"value": "@default", "device": "<resolved name or null>", "description": "<node.description or null>"}, …}, "channels": [{"key", "label", "sink", "fx", "outputs", "bass", "treble"}], "fx_outputs": [...], "mic": {"value": "@auto", "device": "<picked or null>"}}`

- [ ] **Step 1: Write failing tests**

```python
def test_fx_toggle_flips_only_that_channel(self): ...
def test_out_on_fx_channel_is_remembered_for_when_fx_turns_off(self): ...
def test_slot_default_and_none(self): ...
def test_eq_is_clamped_to_12_db(self):  self.assertEqual(apply_command(["eq","music","bass","30"], chs, st).channels["music"].bass, 12.0)
def test_unknown_channel_or_slot_is_a_clear_error(self): ...
def test_status_json_shape(self): ...
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement `bin/audio-mixer`** and the installer/uninstaller/README changes. **Step 4: Run all tests** — `python3 -m unittest discover -s tests -v` → all PASS.

- [ ] **Step 5: Live cutover.** Tell the user that audio drops for about 15 s first, then run `./install.sh < /dev/null`.
Expected: `All 4 channels active`, no "Not connected" warning, and `audio-mixer status` showing today's defaults.

- [ ] **Step 6: Live verification** (each must pass; on any failure, roll back with `git stash; ./install.sh` and report)
  1. `pw-link -l`: each `<sink>_out` → `easyeffects_sink` and `All_Audio_in`; `EE_Return_out` → the current default output; no `_out` → hardware link.
  2. The sound is unchanged. Ask the user to confirm by ear.
  3. **Mic leak gone:** with music playing and the mic quiet, record 3 s from `easyeffects_source` with `pw-record`. The peak must be far below the music's (it's the mic, not the speakers), and `pw-link -l` shows `<real mic> → Mic_In_in` and nothing from a monitor.
  4. `audio-mixer fx browser off` then `fx browser on`: the links change within 1 s and Zen keeps playing with no gap the user can hear.
  5. `audio-mixer eq music bass 6`: `pw-dump` shows `bass:Gain` 6.0 on `Music_Audio`; `audio-mixer eq music bass 0` restores it.
  6. `flatpak run com.github.wwmm.easyeffects -q`: FX channels go silent and nothing reaches the hardware directly. After `easyeffects-watchdog` or a manual relaunch, the links are back within 5 s of `easyeffects_sink` reappearing.
  7. `audio-mixer slot A2 alsa_output.pci-0000_01_00.1.hdmi-stereo-extra1` and `out browser A2 on` (with FX off): links to HDMI appear; then undo both.
  8. Ask the user to plug in the headset: `EE_Return_out` follows to it (A1 = `@default`), and the auto mic switches to the Blue mic while staying muted if it was muted.

- [ ] **Step 7: Commit** — `git commit -m "audio-mixer CLI; cut over to the patchbay engine"`

---

## After this plan

- **Part 2 — hotkeys:** one hotkey file in `~/.config/audio-mixer/`; actions = strip mute, strip volume down/up, channel/FX A1–A4 toggles, mic mute; GNOME bindings rebuilt from it (as `install.sh` does today); an `audio-mixer hotkey …` CLI for the window.
- **Part 3 — the window:** GTK 4 + libadwaita; layout B wide / C narrow; strips (Mic, channels, EasyEffects, All Audio) with live meters, FX, Bass/Treble, A1–A4; "Playing now"; right-click hotkey capture; the popup suppressed while it runs. It builds only on `audio-mixer status --json`, the CLI and `audiomixer`.
