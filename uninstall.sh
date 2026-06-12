#!/bin/bash
set -e

GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $1"; }

echo ""
echo "============================================"
echo "  Audio Mixer for Linux — Uninstaller"
echo "============================================"
echo ""

# ---------- Stop & remove services ----------
info "Stopping background services..."
systemctl --user disable --now audio-osd.service audio-router-daemon.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/audio-osd.service"
rm -f "$HOME/.config/systemd/user/audio-router-daemon.service"
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
for f in audio-osd audio-channel-control audio-route-apps audio-router-daemon audio-routes-apply; do
    rm -f "$HOME/.local/bin/$f"
done
ok "Scripts removed"

# ---------- Remove configs ----------
info "Removing PipeWire configs..."
rm -f "$HOME/.config/pipewire/pipewire.conf.d/virtual-sinks.conf"
rm -f "$HOME/.config/pipewire/pipewire-pulse.conf.d/50-audio-mixer-routing.conf"
# Legacy WirePlumber routing from older installs
rm -f "$HOME/.config/wireplumber/main.lua.d/90-audio-mixer-routing.lua" 2>/dev/null || true
ok "PipeWire configs removed"

# ---------- Routes database ----------
read -r -p "Remove your saved routes (~/.config/audio-mixer)? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    rm -rf "$HOME/.config/audio-mixer"
    ok "Routes database removed"
else
    ok "Kept routes database"
fi

# ---------- Clean WirePlumber saved stream targets ----------
WP_STATE="$HOME/.local/state/wireplumber/restore-stream"
if [ -f "$WP_STATE" ]; then
    info "Cleaning WirePlumber saved routes to our sinks..."
    sed -i '/target=Games_Audio/d;/target=Discord_Audio/d;/target=Music_Audio/d;/target=Browser_Audio/d;/target=Default_Audio/d' "$WP_STATE" 2>/dev/null || true
    ok "WirePlumber routes cleaned"
fi

# ---------- GNOME keybindings ----------
info "Removing keyboard shortcuts..."
GPATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
GSCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)
if [ "$EXISTING" != "@as []" ]; then
    CLEANED=$(echo "$EXISTING" | sed "s|'${GPATH}/custom1[0-2][0-9]/'[, ]*||g;s|, *\]|]|g;s|\[, *|[|g")
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$CLEANED" 2>/dev/null || true
fi
for i in $(seq 100 124); do
    gsettings reset "${GSCHEMA}:${GPATH}/custom${i}/" name 2>/dev/null || true
    gsettings reset "${GSCHEMA}:${GPATH}/custom${i}/" command 2>/dev/null || true
    gsettings reset "${GSCHEMA}:${GPATH}/custom${i}/" binding 2>/dev/null || true
done
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
echo ""
