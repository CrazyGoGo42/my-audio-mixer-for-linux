# VoiceMeeter panels + renameable channels

**Asked (2026-10-23):** "Just recreate this" — VoiceMeeter's Intellipan *Color
Panel* (X/Y pad: Lo↔Hi, brightness, fx echo), *Audibility* (Comp. + Gate knobs)
and the 3-knob *Equalizer* (Treble / Mid / Bass); plus "make Desktop, Discord,
Music and Browser renameable, for other people who might route differently".
Order and details were left to us.

## Decisions (ours)

- **Like VoiceMeeter:** the Color Panel and Comp/Gate sit on the **Mic** strip
  (VoiceMeeter's hardware-input strips); channels get the 3-band EQ (its virtual
  strips). Per-channel dynamics aren't possible here anyway: PipeWire 1.0.5's
  filter-chain has no LV2 (not linked) and its LADSPA loader fails.
- **All DSP is PipeWire builtins** (no plugins, no extra process). Verified in a
  standalone spike (`tests/spike/mic-spike.sh`): exact passthrough at neutral,
  gate/compressor/echo behave as computed, no NaN.
- **Mic chain** (Mic_In becomes a filter-chain; node names unchanged, so the
  daemon's wiring and the Mic strip's volume/mute stay as they are):
  `x → level detector (x², 20 Hz lowpass, log10) → gate + compressor gain (dB
  maths in linear/clamp blocks, summed, exp10) × x → tilt Lo/Hi shelves →
  brightness shelf → dry + 3 delay taps (echo)`.
  - Gate G 0–10 (0 = off): threshold −66 + 3.6·G dBFS, 1:3 downward expander,
    at most −80 dB.
  - Comp C 0–10 (0 = off): threshold −12 − 2.8·C dBFS, ratio 1 + 0.3·C, makeup
    0.7 × the reduction at −18 dBFS speech.
  - Color X −1…1 (Lo…Hi): low shelf 250 Hz −5·X dB, high shelf 2.5 kHz +5·X dB.
  - Color Y 0…1: brightness shelf 6 kHz up to +7 dB over the lower half; echo
    (taps every 0.22 s: 0.55 / 0.30 / 0.17 × amount) over the upper half.
  - Controls are capped at ±10 by PipeWire, hence levels in dB/10 (log10 of power).
- **Mid band:** builtin bq_peaking at 1 kHz, Q 0.7, ±12 dB, between Bass and Treble.
- **Rename:** only the label changes (key, sink, hotkeys, routes stay). Edited by
  right-clicking a channel's name (same gesture as hotkeys). Labels: 1–20
  characters, no `#`, unique against other channels' names and keys and the
  built-in strips (Mic, EasyEffects, All Audio, mic/fx/all). Other apps see the
  new device name after the next audio-engine restart (the toast offers one).
- Applying the new mic chain and Mid band needs one PipeWire restart
  (`audio-routes-apply --restart-pipewire`).

## Tasks

1. Rename: `config.rename_channel`, `audio-mixer rename`, controller + right-click
   popover, live retitle, daemon popup re-reads labels, hotkey names re-applied.
2. Mid band: state/CLI/status/render/live set, staggered Treble/Mid/Bass knobs.
3. Mic engine: `mixer.json` "mic_fx" {color_x, color_y, comp, gate}, render,
   live set, `audio-mixer mic color|comp|gate`, daemon apply.
4. Mic UI: Color Panel pad widget + Comp/Gate knobs on the Mic strip.
5. Sizes (Xvfb test), README, screenshots, install live (PipeWire restart), merge.
