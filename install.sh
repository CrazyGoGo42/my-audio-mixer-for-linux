#!/bin/bash
set -e

# ============================================================================
# Audio Mixer for Linux — VoiceMeeter-like virtual audio channels for Ubuntu
# ============================================================================
#
# What this does:
#   - Creates 3 virtual audio sinks (Discord, Music, Browser)
#   - Your hardware output stays as the Desktop/Games channel
#   - Sets up Ctrl+Numpad hotkeys for per-channel mute/volume control
#   - Installs an OSD overlay that shows volume % when you press hotkeys
#   - Optionally routes running apps to their channels
#
# Channels & Keybindings:
#   CH1 Desktop  — Ctrl+Num1 (mute) | Ctrl+Num4 (vol-) | Ctrl+Num7 (vol+)
#   CH2 Discord  — Ctrl+Num2 (mute) | Ctrl+Num5 (vol-) | Ctrl+Num8 (vol+)
#   CH3 Music    — Ctrl+Num3 (mute) | Ctrl+Num6 (vol-) | Ctrl+Num9 (vol+)
#   CH4 Browser  — Ctrl+NumDel (mute) | Ctrl+Num+ (vol-) | Ctrl+Num- (vol+)
#
# Requirements: Ubuntu 22.04+ with PipeWire (default since 22.10)
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
PIPEWIRE_CONF_DIR="$HOME/.config/pipewire/pipewire.conf.d"
AUTOSTART_DIR="$HOME/.config/autostart"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

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

# Check Ubuntu / Debian-based
if ! command -v apt &>/dev/null; then
    fail "This installer requires apt (Ubuntu/Debian). Exiting."
    exit 1
fi

# Check PipeWire
if ! command -v pipewire &>/dev/null; then
    fail "PipeWire is not installed."
    echo "  Install it with: sudo apt install pipewire pipewire-pulse wireplumber"
    exit 1
fi
ok "PipeWire $(pipewire --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1)"

# Check WirePlumber
if ! command -v wireplumber &>/dev/null; then
    fail "WirePlumber is not installed."
    echo "  Install it with: sudo apt install wireplumber"
    exit 1
fi
ok "WirePlumber $(wireplumber --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' | head -1)"

# Check pactl
if ! command -v pactl &>/dev/null; then
    warn "pactl not found. Installing pipewire-pulse..."
    sudo apt install -y pipewire-pulse
fi
ok "pactl available"

# Check GNOME (for keybindings)
if [ "$XDG_CURRENT_DESKTOP" != "ubuntu:GNOME" ] && [ "$XDG_CURRENT_DESKTOP" != "GNOME" ]; then
    warn "Desktop is '$XDG_CURRENT_DESKTOP' — keybindings are GNOME-only."
    warn "Virtual sinks and OSD will still work, but you'll need to bind keys manually."
    SKIP_KEYBINDINGS=1
fi

# Check Python3 + GTK3 for OSD
if ! python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null; then
    warn "Python3 GTK3 bindings not found. Installing..."
    sudo apt install -y python3-gi gir1.2-gtk-3.0
fi
ok "Python3 + GTK3"

# Detect hardware audio sink
HW_SINK=$(pactl list sinks short 2>/dev/null | grep -v -E "easyeffects|hdmi|bluez|Discord_Audio|Music_Audio|Browser_Audio" | grep "alsa_output" | awk '{print $2}' | head -1)
if [ -z "$HW_SINK" ]; then
    warn "Could not auto-detect hardware audio sink."
    warn "Desktop channel will try to detect at runtime."
else
    ok "Hardware sink: $HW_SINK"
fi

echo ""

# ---------- Install dependencies ----------

info "Checking optional dependencies..."

DEPS_TO_INSTALL=""
command -v pavucontrol &>/dev/null || DEPS_TO_INSTALL="$DEPS_TO_INSTALL pavucontrol"
command -v xdotool &>/dev/null || DEPS_TO_INSTALL="$DEPS_TO_INSTALL xdotool"

if [ -n "$DEPS_TO_INSTALL" ]; then
    info "Installing:$DEPS_TO_INSTALL"
    sudo apt install -y $DEPS_TO_INSTALL
    ok "Dependencies installed"
else
    ok "All dependencies present"
fi

echo ""

# ---------- Install scripts ----------

info "Installing scripts to $BIN_DIR..."

mkdir -p "$BIN_DIR"

cp "$SCRIPT_DIR/bin/audio-osd"             "$BIN_DIR/audio-osd"
cp "$SCRIPT_DIR/bin/audio-channel-control"  "$BIN_DIR/audio-channel-control"
cp "$SCRIPT_DIR/bin/audio-route-apps"       "$BIN_DIR/audio-route-apps"

chmod +x "$BIN_DIR/audio-osd"
chmod +x "$BIN_DIR/audio-channel-control"
chmod +x "$BIN_DIR/audio-route-apps"

# Ensure ~/.local/bin is in PATH
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    warn "$BIN_DIR is not in PATH."
    if [ -f "$HOME/.bashrc" ]; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
        ok "Added to ~/.bashrc — restart your terminal or run: source ~/.bashrc"
    fi
fi

ok "Scripts installed"

# ---------- PipeWire virtual sinks ----------

info "Configuring PipeWire virtual sinks..."

mkdir -p "$PIPEWIRE_CONF_DIR"

cat > "$PIPEWIRE_CONF_DIR/virtual-sinks.conf" << 'SINKEOF'
# Virtual audio sinks — Audio Mixer for Linux
# Channel 1 (Desktop/Games) = hardware sink (auto-detected)
# Channel 2 = Discord
# Channel 3 = Music (YouTube Music, Spotify, etc.)
# Channel 4 = Browsers (Chrome, Firefox, Brave, etc.)

context.modules = [
    {   name = libpipewire-module-loopback
        args = {
            node.description = "Discord Audio"
            capture.props = {
                node.name       = "Discord_Audio"
                media.class     = "Audio/Sink"
                audio.position  = [ FL FR ]
            }
            playback.props = {
                node.name       = "Discord_Audio_out"
                node.passive    = true
            }
        }
    }
    {   name = libpipewire-module-loopback
        args = {
            node.description = "Music Audio"
            capture.props = {
                node.name       = "Music_Audio"
                media.class     = "Audio/Sink"
                audio.position  = [ FL FR ]
            }
            playback.props = {
                node.name       = "Music_Audio_out"
                node.passive    = true
            }
        }
    }
    {   name = libpipewire-module-loopback
        args = {
            node.description = "Browser Audio"
            capture.props = {
                node.name       = "Browser_Audio"
                media.class     = "Audio/Sink"
                audio.position  = [ FL FR ]
            }
            playback.props = {
                node.name       = "Browser_Audio_out"
                node.passive    = true
            }
        }
    }
]
SINKEOF

ok "Virtual sinks configured"

# ---------- Restart PipeWire ----------

info "Restarting PipeWire..."
systemctl --user restart pipewire pipewire-pulse wireplumber
sleep 1

# Verify sinks
SINK_COUNT=$(pactl list sinks short 2>/dev/null | grep -cE "Discord_Audio|Music_Audio|Browser_Audio")
if [ "$SINK_COUNT" -eq 3 ]; then
    ok "All 3 virtual sinks active"
else
    warn "Expected 3 virtual sinks, found $SINK_COUNT. Check: pactl list sinks short"
fi

# ---------- OSD autostart ----------

info "Setting up OSD autostart..."

mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/audio-osd.desktop" << AEOF
[Desktop Entry]
Type=Application
Name=Audio OSD Daemon
Exec=$BIN_DIR/audio-osd
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
AEOF

ok "OSD will auto-start on login"

# Start OSD now
nohup "$BIN_DIR/audio-osd" >/dev/null 2>&1 &
sleep 0.3
ok "OSD daemon started"

# ---------- GNOME keybindings ----------

if [ -z "$SKIP_KEYBINDINGS" ]; then
    info "Setting up keyboard shortcuts..."

    SCRIPT="$BIN_DIR/audio-channel-control"
    GPATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    GSCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"

    EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)

    BINDINGS=(
        "CH1 Mute (Desktop)|${SCRIPT} desktop mute|<Ctrl>KP_1"
        "CH2 Mute (Discord)|${SCRIPT} discord mute|<Ctrl>KP_2"
        "CH3 Mute (Music)|${SCRIPT} music mute|<Ctrl>KP_3"
        "CH1 Vol Down (Desktop)|${SCRIPT} desktop down|<Ctrl>KP_4"
        "CH2 Vol Down (Discord)|${SCRIPT} discord down|<Ctrl>KP_5"
        "CH3 Vol Down (Music)|${SCRIPT} music down|<Ctrl>KP_6"
        "CH1 Vol Up (Desktop)|${SCRIPT} desktop up|<Ctrl>KP_7"
        "CH2 Vol Up (Discord)|${SCRIPT} discord up|<Ctrl>KP_8"
        "CH3 Vol Up (Music)|${SCRIPT} music up|<Ctrl>KP_9"
        "CH4 Mute (Browser)|${SCRIPT} browser mute|<Ctrl>KP_Delete"
        "CH4 Vol Down (Browser)|${SCRIPT} browser down|<Ctrl>KP_Add"
        "CH4 Vol Up (Browser)|${SCRIPT} browser up|<Ctrl>KP_Subtract"
    )

    PATHS=""
    for i in "${!BINDINGS[@]}"; do
        NUM=$((100 + i))
        [ -n "$PATHS" ] && PATHS="${PATHS}, "
        PATHS="${PATHS}'${GPATH}/custom${NUM}/'"
    done

    if [ "$EXISTING" != "@as []" ]; then
        CLEANED=$(echo "$EXISTING" | sed "s|@as \[||;s|\]||;s|'${GPATH}/custom10[0-9]/'[, ]*||g;s|'${GPATH}/custom11[0-1]/'[, ]*||g;s|, *$||")
        if [ -n "$CLEANED" ] && [ "$CLEANED" != " " ]; then
            PATHS="${CLEANED}, ${PATHS}"
        fi
    fi

    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "[${PATHS}]"

    for i in "${!BINDINGS[@]}"; do
        NUM=$((100 + i))
        IFS='|' read -r NAME CMD BINDING <<< "${BINDINGS[$i]}"
        gsettings set "${GSCHEMA}:${GPATH}/custom${NUM}/" name "$NAME"
        gsettings set "${GSCHEMA}:${GPATH}/custom${NUM}/" command "$CMD"
        gsettings set "${GSCHEMA}:${GPATH}/custom${NUM}/" binding "$BINDING"
    done

    ok "12 keyboard shortcuts configured"

    echo ""
    echo "  ┌────────────┬───────────────┬───────────────┬───────────────┐"
    echo "  │  Channel   │     Mute      │   Vol Down    │    Vol Up     │"
    echo "  ├────────────┼───────────────┼───────────────┼───────────────┤"
    echo "  │ Desktop    │  Ctrl+Num1    │  Ctrl+Num4    │  Ctrl+Num7    │"
    echo "  │ Discord    │  Ctrl+Num2    │  Ctrl+Num5    │  Ctrl+Num8    │"
    echo "  │ Music      │  Ctrl+Num3    │  Ctrl+Num6    │  Ctrl+Num9    │"
    echo "  │ Browser    │  Ctrl+NumDel  │  Ctrl+Num+    │  Ctrl+Num-    │"
    echo "  └────────────┴───────────────┴───────────────┴───────────────┘"
fi

# ---------- Done ----------

echo ""
echo "============================================"
echo -e "  ${GREEN}Installation complete!${NC}"
echo "============================================"
echo ""
echo "  Next steps:"
echo "    1. Open the apps you want to route (Discord, Chrome, Spotify...)"
echo "    2. Play some audio in each app"
echo "    3. Run:  audio-route-apps"
echo "       (PipeWire remembers routing, so you only do this once per app)"
echo ""
echo "  Useful commands:"
echo "    audio-route-apps          — Route running apps to their channels"
echo "    pavucontrol               — GUI to manually assign app outputs"
echo "    pactl list sinks short    — List all audio sinks"
echo ""
