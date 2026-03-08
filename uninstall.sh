#!/bin/bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }

echo ""
echo "============================================"
echo "  Audio Mixer for Linux — Uninstaller"
echo "============================================"
echo ""

# Stop OSD daemon
info "Stopping OSD daemon..."
if [ -f /tmp/audio-osd.pid ]; then
    kill "$(cat /tmp/audio-osd.pid)" 2>/dev/null || true
    rm -f /tmp/audio-osd.pid /tmp/audio-osd.fifo
fi
rm -f /tmp/audio-mixer-hw-sink
ok "OSD stopped"

# Remove scripts
info "Removing scripts..."
rm -f "$HOME/.local/bin/audio-osd"
rm -f "$HOME/.local/bin/audio-channel-control"
rm -f "$HOME/.local/bin/audio-route-apps"
ok "Scripts removed"

# Remove PipeWire config
info "Removing virtual sinks config..."
rm -f "$HOME/.config/pipewire/pipewire.conf.d/virtual-sinks.conf"
ok "PipeWire config removed"

# Remove autostart
info "Removing autostart entry..."
rm -f "$HOME/.config/autostart/audio-osd.desktop"
ok "Autostart removed"

# Remove GNOME keybindings
info "Removing keyboard shortcuts..."
GPATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
GSCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"

EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)
if [ "$EXISTING" != "@as []" ]; then
    CLEANED=$(echo "$EXISTING" | sed "s|'${GPATH}/custom10[0-9]/'[, ]*||g;s|'${GPATH}/custom11[0-1]/'[, ]*||g;s|, *\]|]|g;s|\[, *|[|g")
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$CLEANED" 2>/dev/null || true
fi

for i in $(seq 100 111); do
    gsettings reset "${GSCHEMA}:${GPATH}/custom${i}/" name 2>/dev/null || true
    gsettings reset "${GSCHEMA}:${GPATH}/custom${i}/" command 2>/dev/null || true
    gsettings reset "${GSCHEMA}:${GPATH}/custom${i}/" binding 2>/dev/null || true
done
ok "Keybindings removed"

# Restart PipeWire
info "Restarting PipeWire..."
systemctl --user restart pipewire pipewire-pulse wireplumber
ok "PipeWire restarted (virtual sinks removed)"

echo ""
echo "============================================"
echo -e "  ${GREEN}Uninstall complete!${NC}"
echo "============================================"
echo ""
