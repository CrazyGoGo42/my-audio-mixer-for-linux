#!/bin/bash
set -e

# ============================================================================
# Audio Mixer for Linux — VoiceMeeter-style virtual audio channels for Ubuntu
# ============================================================================
#
# Five independent channels (Games, Discord, Music, Browser, Default), each a
# PipeWire virtual sink with its own volume. Apps are routed to the right
# channel *declaratively* by pipewire-pulse — every stream is born on the
# correct sink, so nothing ever escapes to the hardware at full volume and a
# stopped/restarted player always comes back on its channel.
#
#   App → channel sink (volume) → EasyEffects → hardware
#
# Channels & keybindings (Ctrl + numpad):
#   Games    Ctrl+Num1 mute  | Ctrl+Num4 down  | Ctrl+Num7 up
#   Discord  Ctrl+Num2 mute  | Ctrl+Num5 down  | Ctrl+Num8 up
#   Music    Ctrl+Num3 mute  | Ctrl+Num6 down  | Ctrl+Num9 up
#   Browser  Ctrl+NumDel mute| Ctrl+Num+ down  | Ctrl+Num- up
#   Default  Ctrl+Num0 mute  | Ctrl+Num/ down  | Ctrl+Num* up
#
# Requirements: Ubuntu 22.04+ with PipeWire (default since 22.10).
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
PIPEWIRE_CONF_DIR="$HOME/.config/pipewire/pipewire.conf.d"
PULSE_CONF_DIR="$HOME/.config/pipewire/pipewire-pulse.conf.d"
MIXER_DIR="$HOME/.config/audio-mixer"
SYSTEMD_DIR="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; }

echo ""
echo "============================================"
echo "  Audio Mixer for Linux — Installer"
echo "============================================"
echo ""

# ---------- Pre-flight checks ----------
info "Checking system requirements..."

command -v apt &>/dev/null || { fail "Requires apt (Ubuntu/Debian)."; exit 1; }
command -v pipewire &>/dev/null || { fail "PipeWire not installed: sudo apt install pipewire pipewire-pulse wireplumber"; exit 1; }
ok "PipeWire $(pipewire --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1)"
command -v wireplumber &>/dev/null || { fail "WirePlumber not installed: sudo apt install wireplumber"; exit 1; }
ok "WirePlumber $(wireplumber --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1)"
command -v pactl &>/dev/null || { warn "Installing pipewire-pulse..."; sudo apt install -y pipewire-pulse; }
ok "pactl available"

if [ "$XDG_CURRENT_DESKTOP" != "ubuntu:GNOME" ] && [ "$XDG_CURRENT_DESKTOP" != "GNOME" ]; then
    warn "Desktop is '$XDG_CURRENT_DESKTOP' — keybindings are GNOME-only; sinks and routing still work."
    SKIP_KEYBINDINGS=1
fi
python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null || { warn "Installing GTK3..."; sudo apt install -y python3-gi gir1.2-gtk-3.0; }
ok "Python3 + GTK3"

# ---------- Dependencies ----------
DEPS=""
command -v zenity &>/dev/null    || DEPS="$DEPS zenity"
command -v pavucontrol &>/dev/null || DEPS="$DEPS pavucontrol"
command -v xrandr &>/dev/null    || DEPS="$DEPS x11-xserver-utils"
if [ -n "$DEPS" ]; then info "Installing:$DEPS"; sudo apt install -y $DEPS; ok "Dependencies installed"; else ok "All dependencies present"; fi
echo ""

# ---------- Remove stale autostart from older installs ----------
# Older versions started the daemons from BOTH systemd AND XDG autostart, which
# launched two routers that fought each other. We standardise on systemd only.
rm -f "$AUTOSTART_DIR/audio-osd.desktop" "$AUTOSTART_DIR/audio-router-daemon.desktop" 2>/dev/null
rm -f "$HOME/.config/wireplumber/main.lua.d/90-audio-mixer-routing.lua" 2>/dev/null

# ---------- Install scripts ----------
info "Installing scripts to $BIN_DIR..."
mkdir -p "$BIN_DIR"
for f in audio-osd audio-channel-control audio-route-apps audio-router-daemon audio-routes-apply; do
    cp "$SCRIPT_DIR/bin/$f" "$BIN_DIR/$f"
    chmod +x "$BIN_DIR/$f"
done
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    [ -f "$HOME/.bashrc" ] && echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    warn "Added ~/.local/bin to PATH in ~/.bashrc — run: source ~/.bashrc"
fi
ok "Scripts installed"

# ---------- Routes database ----------
info "Installing routing database..."
mkdir -p "$MIXER_DIR"
if [ -f "$MIXER_DIR/routes.json" ]; then
    ok "Keeping existing routes.json (your saved channels)"
else
    cp "$SCRIPT_DIR/config/routes.json" "$MIXER_DIR/routes.json"
    ok "Default routes.json installed"
fi

# Migrate routes learned by the old reactive daemon, if any (skip junk keys).
OLD_DB="$HOME/.local/state/audio-router/routing.json"
if [ -f "$OLD_DB" ]; then
    MIGRATED=$(python3 - "$OLD_DB" "$MIXER_DIR/routes.json" <<'PY'
import json, sys
old_path, new_path = sys.argv[1], sys.argv[2]
valid = {"Games_Audio", "Discord_Audio", "Music_Audio", "Browser_Audio", "Default_Audio"}
try:
    old = json.load(open(old_path))
    new = json.load(open(new_path))
except Exception:
    print(0); sys.exit()
new.setdefault("binary", {}); new.setdefault("app", {})
n = 0
for key, sink in old.items():
    if sink not in valid or "(deleted)" in key:
        continue
    if key in new["binary"] or key in new["app"]:
        continue
    new["binary"][key] = sink
    n += 1
if n:
    json.dump(new, open(new_path, "w"), indent=2)
print(n)
PY
)
    [ "${MIGRATED:-0}" -gt 0 ] && ok "Migrated $MIGRATED saved app route(s) from the old daemon"
fi

# ---------- Virtual sinks ----------
info "Configuring 5 virtual sinks..."
mkdir -p "$PIPEWIRE_CONF_DIR"

# Pick the downstream node every channel feeds into: EasyEffects if present,
# otherwise the first non-HDMI hardware output.
if pactl list sinks short 2>/dev/null | grep -q easyeffects_sink; then
    DOWNSTREAM="easyeffects_sink"
    ok "EasyEffects detected — channels will route through it"
else
    DOWNSTREAM="$(pactl list sinks short 2>/dev/null | awk '$2 ~ /^alsa_output/ && $2 !~ /hdmi/ {print $2; exit}')"
    [ -z "$DOWNSTREAM" ] && DOWNSTREAM="@DEFAULT_SINK@"
    info "EasyEffects not found — channels route to $DOWNSTREAM"
fi
sed "s/__DOWNSTREAM__/${DOWNSTREAM}/g" "$SCRIPT_DIR/config/virtual-sinks.conf" > "$PIPEWIRE_CONF_DIR/virtual-sinks.conf"
ok "Virtual sinks configured (downstream: $DOWNSTREAM)"

# ---------- Restart PipeWire to load the sinks ----------
info "Restarting PipeWire..."
systemctl --user restart pipewire pipewire-pulse wireplumber
sleep 2
SINK_COUNT=$(pactl list sinks short 2>/dev/null | grep -cE "Games_Audio|Discord_Audio|Music_Audio|Browser_Audio|Default_Audio")
[ "$SINK_COUNT" -eq 5 ] && ok "All 5 virtual sinks active" || warn "Expected 5 sinks, found $SINK_COUNT (check: pactl list sinks short)"

# ---------- Compile routing rules ----------
info "Compiling app→channel routing rules..."
mkdir -p "$PULSE_CONF_DIR"
"$BIN_DIR/audio-routes-apply"   # writes the pulse config and restarts pipewire-pulse
sleep 1
ok "Routing rules applied"

# ---------- systemd user services (single autostart source) ----------
info "Setting up background services..."
mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/audio-osd.service" << EOF
[Unit]
Description=Audio Mixer OSD Overlay
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=$BIN_DIR/audio-osd
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_DIR/audio-router-daemon.service" << EOF
[Unit]
Description=Audio Mixer Router Daemon
After=pipewire.service pipewire-pulse.service wireplumber.service
Wants=pipewire-pulse.service

[Service]
ExecStart=$BIN_DIR/audio-router-daemon
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable audio-osd.service audio-router-daemon.service >/dev/null 2>&1
systemctl --user restart audio-osd.service audio-router-daemon.service
ok "Services enabled and started (auto-start on login)"

# ---------- GNOME keybindings ----------
if [ -z "$SKIP_KEYBINDINGS" ]; then
    info "Setting up keyboard shortcuts..."
    SCRIPT="$BIN_DIR/audio-channel-control"
    GPATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    GSCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)

    # NumLock ON keysyms (KP_1..KP_9, KP_0) + NumLock OFF equivalents.
    BINDINGS=(
        "CH1 Mute (Games)|${SCRIPT} games mute|<Ctrl>KP_1"
        "CH2 Mute (Discord)|${SCRIPT} discord mute|<Ctrl>KP_2"
        "CH3 Mute (Music)|${SCRIPT} music mute|<Ctrl>KP_3"
        "CH1 Vol Down (Games)|${SCRIPT} games down|<Ctrl>KP_4"
        "CH2 Vol Down (Discord)|${SCRIPT} discord down|<Ctrl>KP_5"
        "CH3 Vol Down (Music)|${SCRIPT} music down|<Ctrl>KP_6"
        "CH1 Vol Up (Games)|${SCRIPT} games up|<Ctrl>KP_7"
        "CH2 Vol Up (Discord)|${SCRIPT} discord up|<Ctrl>KP_8"
        "CH3 Vol Up (Music)|${SCRIPT} music up|<Ctrl>KP_9"
        "CH4 Mute (Browser)|${SCRIPT} browser mute|<Ctrl>KP_Delete"
        "CH4 Vol Down (Browser)|${SCRIPT} browser down|<Ctrl>KP_Add"
        "CH4 Vol Up (Browser)|${SCRIPT} browser up|<Ctrl>KP_Subtract"
        "CH5 Mute (Default)|${SCRIPT} default mute|<Ctrl>KP_0"
        "CH5 Vol Down (Default)|${SCRIPT} default down|<Ctrl>KP_Divide"
        "CH5 Vol Up (Default)|${SCRIPT} default up|<Ctrl>KP_Multiply"
        "CH1 Mute (Games) NL|${SCRIPT} games mute|<Ctrl>KP_End"
        "CH2 Mute (Discord) NL|${SCRIPT} discord mute|<Ctrl>KP_Down"
        "CH3 Mute (Music) NL|${SCRIPT} music mute|<Ctrl>KP_Next"
        "CH1 Vol Down (Games) NL|${SCRIPT} games down|<Ctrl>KP_Left"
        "CH2 Vol Down (Discord) NL|${SCRIPT} discord down|<Ctrl>KP_Begin"
        "CH3 Vol Down (Music) NL|${SCRIPT} music down|<Ctrl>KP_Right"
        "CH1 Vol Up (Games) NL|${SCRIPT} games up|<Ctrl>KP_Home"
        "CH2 Vol Up (Discord) NL|${SCRIPT} discord up|<Ctrl>KP_Up"
        "CH3 Vol Up (Music) NL|${SCRIPT} music up|<Ctrl>KP_Prior"
        "CH5 Mute (Default) NL|${SCRIPT} default mute|<Ctrl>KP_Insert"
    )

    # Build the final keybinding-paths array in Python: keep any of the user's
    # own custom shortcuts, drop our previous ones (custom100-124), add ours.
    COUNT=${#BINDINGS[@]}
    NEWLIST=$(python3 - "$EXISTING" "$GPATH" "$COUNT" <<'PY'
import sys, re
existing, gpath, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
ours = {f"{gpath}/custom{100+i}/" for i in range(count)}
found = re.findall(r"'([^']*)'", existing or "")
kept = [p for p in found if p not in ours and not re.search(r"/custom1[0-2][0-9]/$", p)]
allpaths = kept + [f"{gpath}/custom{100+i}/" for i in range(count)]
print("[" + ", ".join(f"'{p}'" for p in allpaths) + "]")
PY
)
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEWLIST"

    for i in "${!BINDINGS[@]}"; do
        NUM=$((100 + i))
        IFS='|' read -r NAME CMD BINDING <<< "${BINDINGS[$i]}"
        gsettings set "${GSCHEMA}:${GPATH}/custom${NUM}/" name "$NAME"
        gsettings set "${GSCHEMA}:${GPATH}/custom${NUM}/" command "$CMD"
        gsettings set "${GSCHEMA}:${GPATH}/custom${NUM}/" binding "$BINDING"
    done
    ok "${#BINDINGS[@]} keyboard shortcuts configured"

    echo ""
    echo "  ┌────────────┬───────────────┬───────────────┬───────────────┐"
    echo "  │  Channel   │     Mute      │   Vol Down    │    Vol Up     │"
    echo "  ├────────────┼───────────────┼───────────────┼───────────────┤"
    echo "  │ Games      │  Ctrl+Num1    │  Ctrl+Num4    │  Ctrl+Num7    │"
    echo "  │ Discord    │  Ctrl+Num2    │  Ctrl+Num5    │  Ctrl+Num8    │"
    echo "  │ Music      │  Ctrl+Num3    │  Ctrl+Num6    │  Ctrl+Num9    │"
    echo "  │ Browser    │  Ctrl+NumDel  │  Ctrl+Num+    │  Ctrl+Num-    │"
    echo "  │ Default    │  Ctrl+Num0    │  Ctrl+Num/    │  Ctrl+Num*    │"
    echo "  └────────────┴───────────────┴───────────────┴───────────────┘"
fi

echo ""
echo "============================================"
echo -e "  ${GREEN}Installation complete!${NC}"
echo "============================================"
echo ""
echo "  Known apps (Discord, Chrome, Spotify, YouTube Music...) route automatically."
echo "  A new app starts on the Default channel and a popup asks where it belongs."
echo "  Your choices are saved to ~/.config/audio-mixer/routes.json."
echo ""
echo "  Commands:  audio-route-apps     move playing apps onto their channel now"
echo "             audio-routes-apply   recompile rules after editing routes.json"
echo "             pavucontrol          GUI for manual tweaks"
echo ""
