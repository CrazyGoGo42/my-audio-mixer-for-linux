#!/bin/bash
set -e

GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }

MIXER_DIR="$HOME/.config/audio-mixer"
SCRIPTS="audio-osd audio-channel-control audio-route-apps audio-router-daemon audio-routes-apply easyeffects-watchdog audio-mixer-backup"
UNITS="audio-osd.service audio-router-daemon.service easyeffects-watchdog.service audio-mixer-backup.service audio-mixer-backup.timer"

# Our channel sinks, read now — the channel list may be deleted below.
SINKS=$(awk '{ sub(/#.*/, "") } NF >= 6 { print $2 }' "$MIXER_DIR/channels.conf" 2>/dev/null || true)
[ -z "$SINKS" ] && SINKS="Games_Audio Discord_Audio Music_Audio Browser_Audio Default_Audio"
BACKUP_DIR=$("$HOME/.local/bin/audio-mixer-backup" --where 2>/dev/null || true)

echo ""
echo "============================================"
echo "  Audio Mixer for Linux — Uninstaller"
echo "============================================"
echo ""

# ---------- Stop & remove services ----------
info "Stopping background services..."
systemctl --user disable --now $UNITS >/dev/null 2>&1 || true
for u in $UNITS; do rm -f "$HOME/.config/systemd/user/$u"; done
systemctl --user daemon-reload 2>/dev/null || true
# Legacy XDG autostart from older installs
rm -f "$HOME/.config/autostart/audio-osd.desktop"
rm -f "$HOME/.config/autostart/audio-router-daemon.desktop"
# Kill any stragglers
pkill -f "$HOME/.local/bin/audio-router-daemon" 2>/dev/null || true
pkill -f "$HOME/.local/bin/audio-osd" 2>/dev/null || true
rm -f /tmp/audio-osd.pid /tmp/audio-osd.fifo /tmp/audio-router-daemon.pid /tmp/audio-mixer-volumes
ok "Services stopped and removed"

# ---------- Remove scripts ----------
info "Removing scripts..."
for f in $SCRIPTS; do
    rm -f "$HOME/.local/bin/$f"
done
# Legacy artifacts from older versions
rm -f "$HOME/.local/bin/setup-audio-keybindings.sh"
rm -rf "$HOME/.local/state/audio-router"
ok "Scripts removed"

# ---------- Remove configs ----------
info "Removing PipeWire configs..."
rm -f "$HOME/.config/pipewire/pipewire.conf.d/virtual-sinks.conf"
rm -f "$HOME/.config/pipewire/pipewire-pulse.conf.d/50-audio-mixer-routing.conf"
# Legacy WirePlumber routing from older installs
rm -f "$HOME/.config/wireplumber/main.lua.d/90-audio-mixer-routing.lua" 2>/dev/null || true
ok "PipeWire configs removed"

# ---------- Routes database ----------
read -r -p "Remove your channels, saved routes and volumes (~/.config/audio-mixer)? [y/N] " ans || ans=""
if [[ "$ans" =~ ^[Yy]$ ]]; then
    rm -rf "$MIXER_DIR"
    ok "Routes database removed"
else
    ok "Kept routes database"
fi

# ---------- Clean WirePlumber saved stream targets ----------
WP_STATE="$HOME/.local/state/wireplumber/restore-stream"
if [ -f "$WP_STATE" ]; then
    info "Cleaning WirePlumber saved routes to our sinks..."
    for s in $SINKS; do
        sed -i "/target=${s}\$/d" "$WP_STATE" 2>/dev/null || true
    done
    ok "WirePlumber routes cleaned"
fi

# ---------- GNOME keybindings ----------
info "Removing keyboard shortcuts..."
python3 - <<'PY' || true
import re, subprocess
KEYS = "org.gnome.settings-daemon.plugins.media-keys"
SCHEMA = KEYS + ".custom-keybinding"

def gs(*args):
    return subprocess.run(["gsettings", *args], capture_output=True, text=True).stdout.strip()

kept = []
for path in re.findall(r"'([^']*)'", gs("get", KEYS, "custom-keybindings")):
    if "audio-channel-control" in gs("get", f"{SCHEMA}:{path}", "command"):
        for k in ("name", "command", "binding"):
            gs("reset", f"{SCHEMA}:{path}", k)
    else:
        kept.append(path)
gs("set", KEYS, "custom-keybindings", "[" + ", ".join(f"'{p}'" for p in kept) + "]")
PY
ok "Keybindings removed"

# ---------- Restart PipeWire ----------
info "Restarting PipeWire..."
systemctl --user restart pipewire pipewire-pulse wireplumber
ok "PipeWire restarted (virtual sinks removed)"

echo ""
echo "============================================"
echo -e "  ${GREEN}Uninstall complete!${NC}"
echo "============================================"
echo ""
echo "  Note: EasyEffects settings were left untouched."
[ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ] && echo "  Your backup in $BACKUP_DIR was kept."
echo ""
