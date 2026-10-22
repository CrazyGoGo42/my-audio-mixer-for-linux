#!/bin/bash
# Engine spike: runs engine-spike.conf as a short-lived standalone PipeWire
# client and checks, against the live PipeWire, the six things the mixer engine
# relies on. Prints PASS/FAIL per check, then removes everything it created.
#
# Usage: bash tests/spike/engine-spike.sh

HERE="$(cd "$(dirname "$0")" && pwd)"
FAILS=0
check() {  # check <description> <command...>
    local what=$1; shift
    if "$@" >/dev/null 2>&1; then echo "PASS  $what"; else echo "FAIL  $what"; FAILS=$((FAILS + 1)); fi
}
links_from() {  # number of links leaving node $1
    pw-link -l | awk -v n="$1:" 'index($0, n) == 1 { inside = 1; next } /^[^ ]/ { inside = 0 } inside && /\|->/ { c++ } END { print c + 0 }'
}
node_id() {
    pw-dump | python3 -c "import json,sys; print(next(o['id'] for o in json.load(sys.stdin) if ((o.get('info') or {}).get('props') or {}).get('node.name') == sys.argv[1]))" "$1"
}
bass_gain() {
    pw-dump | python3 -c "
import json, sys
for o in json.load(sys.stdin):
    if ((o.get('info') or {}).get('props') or {}).get('node.name') == 'spike_ch':
        for p in (o['info'].get('params') or {}).get('Props') or []:
            ps = p.get('params') or []
            for k, v in zip(ps[::2], ps[1::2]):
                if k == 'bass:Gain': print(v)"
}

pipewire -c "$HERE/engine-spike.conf" >/dev/null 2>&1 &
PW=$!
trap 'kill $PW 2>/dev/null; wait $PW 2>/dev/null' EXIT
sleep 2

check "1. unlinked output still exposes output_FL/output_FR" \
    bash -c 'pw-link -o | grep -qx "spike_ch_out:output_FL" && pw-link -o | grep -qx "spike_ch_out:output_FR"'
sleep 3
check "2. WirePlumber left it unlinked (autoconnect=false)" test "$(links_from spike_ch_out)" -eq 0
check "3. one output fans out to two inputs" \
    bash -c 'pw-link spike_ch_out:output_FL easyeffects_sink:playback_FL && pw-link spike_ch_out:output_FL spike_mix_in:input_FL'
sleep 2
check "4. links outlive pw-link (linger)" test "$(links_from spike_ch_out)" -eq 2
pw-cli set-param "$(node_id spike_ch)" Props '{ params = [ "bass:Gain" 6.0 ] }' >/dev/null 2>&1
sleep 0.5
check "5. bass:Gain is live-adjustable (now 6.0)" bash -c "[ \"\$(printf '%.1f' '$(bass_gain)')\" = 6.0 ]"
check "6. the loopback source is visible to apps" bash -c 'pactl list sources short | grep -q "spike_mix"'

kill $PW 2>/dev/null; wait $PW 2>/dev/null; trap - EXIT
sleep 1
if pw-cli ls Node 2>/dev/null | grep -q spike_; then echo "cleanup FAILED: spike nodes left behind"; FAILS=$((FAILS + 1)); else echo "cleanup ok"; fi
exit $FAILS
