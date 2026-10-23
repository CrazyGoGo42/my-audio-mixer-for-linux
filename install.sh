#!/bin/bash
set -e

# ============================================================================
# Audio Mixer for Linux — VoiceMeeter-style virtual audio channels for Ubuntu
# ============================================================================
#
# Independent channels (Desktop, Discord, Music, Browser — see
# config/channels.conf), each a PipeWire virtual sink with its own volume, plus
# an "All Audio" input carrying every channel mixed together. Apps
# are routed to the right channel *declaratively* by pipewire-pulse — every
# stream is born on the correct sink, so nothing ever escapes to the hardware at
# full volume and a stopped/restarted player always comes back on its channel.
#
#   App → channel sink (volume) → EasyEffects → hardware
#
# Usage: ./install.sh                 install / update (offers to restore a backup)
#        ./install.sh --restore DIR   restore the backup in DIR as part of the install
#
# Safe to rerun: your channels, routes and volumes are kept.
#
# Requirements: Ubuntu 22.04+ with PipeWire (default since 22.10).
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/lib/audio-mixer"
MIXER_DIR="$HOME/.config/audio-mixer"
SYSTEMD_DIR="$HOME/.config/systemd/user"
AUTOSTART_DIR="$HOME/.config/autostart"
EE_APP=com.github.wwmm.easyeffects
SCRIPTS="audio-osd audio-channel-control audio-route-apps audio-router-daemon audio-routes-apply easyeffects-watchdog audio-mixer-backup audio-mixer audio-mixer-window"

RESTORE_DIR=""
case "$1" in
    --restore) RESTORE_DIR="${2:?usage: ./install.sh --restore DIR}" ;;
    "") ;;
    *) echo "Usage: ./install.sh [--restore DIR]"; exit 1 ;;
esac

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

# A kernel update that skipped linux-modules-extra boots with no sound drivers.
# Everything below still installs, but there'd be no speakers to hear it on.
if ! grep -q '^ *[0-9]' /proc/asound/cards 2>/dev/null; then
    warn "No sound cards found. If you just updated the kernel, run:"
    warn "  sudo apt install linux-modules-extra-$(uname -r)  (then reboot)"
fi

if [ "$XDG_CURRENT_DESKTOP" != "ubuntu:GNOME" ] && [ "$XDG_CURRENT_DESKTOP" != "GNOME" ]; then
    warn "Desktop is '$XDG_CURRENT_DESKTOP' — keybindings are GNOME-only; sinks and routing still work."
    SKIP_KEYBINDINGS=1
fi
python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null || { warn "Installing GTK3..."; sudo apt install -y python3-gi gir1.2-gtk-3.0; }
# The mixer window is GTK 4 + libadwaita.
python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')" 2>/dev/null \
    || { warn "Installing GTK4 + libadwaita..."; sudo apt install -y gir1.2-gtk-4.0 gir1.2-adw-1; }
ok "Python3 + GTK3"

# ---------- Dependencies ----------
DEPS=""
command -v zenity &>/dev/null    || DEPS="$DEPS zenity"
command -v pavucontrol &>/dev/null || DEPS="$DEPS pavucontrol"
command -v xrandr &>/dev/null    || DEPS="$DEPS x11-xserver-utils"
command -v rsync &>/dev/null     || DEPS="$DEPS rsync"
if [ -n "$DEPS" ]; then info "Installing:$DEPS"; sudo apt install -y $DEPS; ok "Dependencies installed"; else ok "All dependencies present"; fi

# ---------- EasyEffects ----------
if flatpak info "$EE_APP" &>/dev/null || command -v easyeffects &>/dev/null; then
    ok "EasyEffects present"
else
    info "Installing EasyEffects (Flatpak from Flathub)..."
    command -v flatpak &>/dev/null || sudo apt install -y flatpak
    sudo flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
    sudo flatpak install -y --noninteractive flathub "$EE_APP"
    ok "EasyEffects installed"
fi
echo ""

# ---------- Remove stale autostart from older installs ----------
# Older versions started the daemons from BOTH systemd AND XDG autostart, which
# launched two routers that fought each other. We standardise on systemd only.
rm -f "$AUTOSTART_DIR/audio-osd.desktop" "$AUTOSTART_DIR/audio-router-daemon.desktop" 2>/dev/null
rm -f "$HOME/.config/wireplumber/main.lua.d/90-audio-mixer-routing.lua" 2>/dev/null

# ---------- Install scripts ----------
info "Installing scripts to $BIN_DIR..."
mkdir -p "$BIN_DIR"
for f in $SCRIPTS; do
    cp "$SCRIPT_DIR/bin/$f" "$BIN_DIR/$f"
    chmod +x "$BIN_DIR/$f"
done
# The scripts' shared Python package.
mkdir -p "$LIB_DIR"
rm -rf "$LIB_DIR/audiomixer"
cp -r "$SCRIPT_DIR/lib/audiomixer" "$LIB_DIR/audiomixer"
find "$LIB_DIR/audiomixer" -name __pycache__ -prune -exec rm -rf {} +
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    [ -f "$HOME/.bashrc" ] && echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    warn "Added ~/.local/bin to PATH in ~/.bashrc — run: source ~/.bashrc"
fi
ok "Scripts installed"

# ---------- Restore a backup ----------
# Brings back your channels, learned routes, volumes, EasyEffects presets and
# headset profile — before anything below reads them.
if [ -n "$RESTORE_DIR" ]; then
    "$BIN_DIR/audio-mixer-backup" --restore "$RESTORE_DIR"
    ok "Backup restored"
else
    FOUND_DIR="$("$BIN_DIR/audio-mixer-backup" --where)"
    if [ -d "$FOUND_DIR/audio-mixer" ]; then
        # Fresh system: restore unless told not to. Existing setup: keep it unless asked.
        if [ -f "$MIXER_DIR/routes.json" ]; then CHOICES="y/N"; DEFAULT=n; else CHOICES="Y/n"; DEFAULT=y; fi
        read -r -p "Restore your backup from $FOUND_DIR (saved $(cat "$FOUND_DIR/LAST_BACKUP" 2>/dev/null || echo '?'))? [$CHOICES] " ans || ans=""
        if [[ "${ans:-$DEFAULT}" =~ ^[Yy] ]]; then
            "$BIN_DIR/audio-mixer-backup" --restore "$FOUND_DIR"
            ok "Backup restored"
        fi
    fi
fi

# ---------- Channel list + routes database ----------
info "Installing channel list and routing database..."
mkdir -p "$MIXER_DIR"
for f in channels.conf routes.json; do
    if [ -f "$MIXER_DIR/$f" ]; then
        ok "Keeping your existing $f"
    else
        cp "$SCRIPT_DIR/config/$f" "$MIXER_DIR/$f"
        ok "Default $f installed"
    fi
done
# Mixer settings (FX, output slots, Bass/Treble, mic). The defaults sound
# exactly like the setup before these existed: every channel through
# EasyEffects to the default output.
if [ ! -f "$MIXER_DIR/mixer.json" ]; then
    python3 - "$LIB_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from audiomixer.config import load_channels, load_state, save_state
save_state(load_state(load_channels()))
PY
    ok "Default mixer settings created"
fi
# Sink names of every channel, one per line.
channel_sinks() { awk '{ sub(/#.*/, "") } NF >= 6 { print $2 }' "$MIXER_DIR/channels.conf"; }

# Migrate routes learned by the old reactive daemon, if any (skip junk keys).
OLD_DB="$HOME/.local/state/audio-router/routing.json"
if [ -f "$OLD_DB" ]; then
    MIGRATED=$(python3 - "$OLD_DB" "$MIXER_DIR/routes.json" "$(channel_sinks)" <<'PY'
import json, sys
old_path, new_path = sys.argv[1], sys.argv[2]
valid = set(sys.argv[3].split())
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

# ---------- Virtual sinks + routing rules ----------
# audio-routes-apply builds both PipeWire configs from channels.conf and
# routes.json. Channels always feed EasyEffects' sink (by name, so it's right
# even before EasyEffects first starts), and it restarts PipeWire only if the
# channel config changed.
info "Building channels and routing rules..."
"$BIN_DIR/audio-routes-apply"
EXPECTED=$(channel_sinks | wc -l)
FOUND=0
for _ in $(seq 20); do
    FOUND=$(pactl list sinks short 2>/dev/null | awk '{ print $2 }' | grep -cxF -f <(channel_sinks) || true)
    [ "$FOUND" -eq "$EXPECTED" ] && break
    sleep 0.5
done
if [ "$FOUND" -eq "$EXPECTED" ]; then
    ok "All $EXPECTED channels active, routing rules applied"
else
    warn "Expected $EXPECTED channels, found $FOUND (check: pactl list sinks short)"
fi

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

cat > "$SYSTEMD_DIR/easyeffects-watchdog.service" << EOF
[Unit]
Description=EasyEffects Watchdog
After=pipewire.service wireplumber.service graphical-session.target

[Service]
ExecStart=$BIN_DIR/easyeffects-watchdog
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_DIR/audio-mixer-backup.service" << EOF
[Unit]
Description=Audio Mixer settings backup

[Service]
Type=oneshot
ExecStart=$BIN_DIR/audio-mixer-backup
EOF

cat > "$SYSTEMD_DIR/audio-mixer-backup.timer" << EOF
[Unit]
Description=Daily Audio Mixer settings backup

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable audio-osd.service audio-router-daemon.service easyeffects-watchdog.service audio-mixer-backup.timer >/dev/null 2>&1
systemctl --user restart audio-osd.service audio-router-daemon.service easyeffects-watchdog.service
systemctl --user start audio-mixer-backup.timer
ok "Services enabled and started (auto-start on login, daily backup)"

# ---------- Point EasyEffects at the mixer, then start it ----------
# EasyEffects listens to the Mixer Mic (only ever fed by a real microphone, so
# speakers can't leak into your mic) and plays into the EasyEffects strip.
# Pointed *before* it's started: on a fresh install it then starts with the
# right devices instead of being quit mid-start. A running one is stopped,
# waited for (it writes its settings back on exit) and relaunched.
if flatpak info "$EE_APP" &>/dev/null; then
    if python3 - "$LIB_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from audiomixer.easyeffects import point_at_mixer
sys.exit(0 if point_at_mixer() else 1)
PY
    then ok "EasyEffects now uses the Mixer Mic and the EasyEffects strip"
    else ok "EasyEffects already uses the Mixer Mic and the EasyEffects strip"
    fi
    # On a fresh install it has never run, so its sink doesn't exist yet. Clear
    # any stale single-instance lock first — it makes a new launch exit silently.
    if ! pgrep -f 'easyeffects --service-mode' >/dev/null; then
        LOCKDIR="/run/user/$(id -u)/.flatpak/$EE_APP/tmp"
        rm -f "$LOCKDIR/EasyEffectsServer" "$LOCKDIR/easyeffects.lock"
        setsid -f flatpak run "$EE_APP" --service-mode --hide-window >/dev/null 2>&1
        ok "EasyEffects started"
    fi
    # Apps' default mic = your real mic with your EasyEffects input effects.
    for _ in $(seq 20); do
        pactl set-default-source easyeffects_source 2>/dev/null && break
        sleep 0.5
    done
fi

# ---------- Mixer window: app launcher entry + start at login ----------
# XDG autostart (not systemd): it starts inside the graphical session, so the
# window always has a display. Single instance — launching again just raises it.
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR" "$AUTOSTART_DIR"
cat > "$APPS_DIR/audio-mixer.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Audio Mixer
Comment=Volume, effects and outputs for every channel; route playing apps
Exec=$BIN_DIR/audio-mixer-window
Icon=multimedia-volume-control
Categories=AudioVideo;Audio;Mixer;
Keywords=volume;mixer;voicemeeter;audio;
StartupNotify=true
EOF
grep -v '^StartupNotify' "$APPS_DIR/audio-mixer.desktop" > "$AUTOSTART_DIR/audio-mixer-window.desktop"
printf 'X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=5\n' >> "$AUTOSTART_DIR/audio-mixer-window.desktop"
ok "Mixer window in your app launcher (\"Audio Mixer\") and starting at login"

# ---------- GNOME keybindings ----------
# From ~/.config/audio-mixer/hotkeys.json (created from channels.conf's numpad
# keys on first run). Keeps any of your own custom shortcuts; replaces ours.
# Change them in the mixer window (right-click a control) or with
# `audio-mixer hotkeys set <action> <keys>`.
if [ -z "$SKIP_KEYBINDINGS" ]; then
    info "Setting up keyboard shortcuts..."
    ok "$("$BIN_DIR/audio-mixer" hotkeys apply)"
    echo ""
    "$BIN_DIR/audio-mixer" hotkeys list | awk '$2 != "-" { printf "  %-28s %s\n", substr($0, index($0, $3)), $2 }'
fi

# ---------- First backup ----------
"$BIN_DIR/audio-mixer-backup" >/dev/null && ok "Settings backed up to $("$BIN_DIR/audio-mixer-backup" --where)"

echo ""
echo "============================================"
echo -e "  ${GREEN}Installation complete!${NC}"
echo "============================================"
echo ""
echo "  Known apps (Discord, Chrome, Spotify, YouTube Music...) route automatically."
echo "  A new app starts on the Desktop channel and a popup asks where it belongs."
echo "  Your choices are saved to ~/.config/audio-mixer/routes.json."
echo "  Record or stream everything at once by picking the \"All Audio\" input."
echo ""
echo "  Your settings are backed up daily to the folder above. After reinstalling"
echo "  Ubuntu, let that folder sync, then run ./install.sh — it offers to restore."
echo ""
echo "  Commands:  audio-route-apps     move playing apps onto their channel now"
echo "             audio-routes-apply   apply changes to channels.conf / routes.json"
echo "             audio-mixer-backup   back up now (--restore to put one back)"
echo "             audio-mixer          FX, outputs A1-A4, Bass/Treble, mic (--help)"
echo "             audio-mixer-window   the mixer window (also in your app launcher)"
echo "             pavucontrol          GUI for manual tweaks"
echo ""
