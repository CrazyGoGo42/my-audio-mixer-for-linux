"""
Make the live graph match the wanted routing: add missing links, remove stale
ones — but only links that touch a node the mixer manages. Links made by apps,
WirePlumber (for app streams) or EasyEffects (inside its own chain) are never
touched.
"""

import subprocess

from .config import EQ_BANDS, load_channels, load_state
from .pwgraph import read_graph
from .routing import desired_links, managed_nodes


def plan_changes(desired, graph, managed):
    """(links to add, links to remove)."""
    def ours(link):
        return link[0].split(":", 1)[0] in managed or link[1].split(":", 1)[0] in managed

    to_add = set(desired) - graph.links
    to_remove = {link for link in graph.links if ours(link) and link not in desired}
    return to_add, to_remove


def apply_changes(to_add, to_remove):
    """Run pw-link for each change; return error lines instead of raising."""
    errors = []
    for args in [["-d", *link] for link in sorted(to_remove)] + [list(link) for link in sorted(to_add)]:
        try:
            r = subprocess.run(["pw-link", *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(f"pw-link {' '.join(args)}: {e}")
            continue
        if r.returncode != 0:
            errors.append(f"pw-link {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return errors


def eq_params(cs):
    """The pw-cli Props for a channel's EQ filters."""
    gains = " ".join(f'"{band}:Gain" {float(getattr(cs, band))}' for band in EQ_BANDS)
    return f"{{ params = [ {gains} ] }}"


def apply_eq(graph, channels, state):
    """Set each channel's live Bass/Mid/Treble (filter-chain controls on its sink)."""
    for ch in channels:
        node = graph.nodes.get(ch.sink)
        cs = state.channels.get(ch.key)
        if node is None or cs is None:
            continue
        params = eq_params(cs)
        try:
            subprocess.run(["pw-cli", "set-param", str(node.id), "Props", params],
                           capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def reconcile_once(graph=None):
    """Bring the live graph in line with mixer.json. Returns (added, removed).
    Pass a fresh `graph` to save reading it again."""
    channels = load_channels()
    graph = graph if graph is not None else read_graph()
    to_add, to_remove = plan_changes(desired_links(channels, load_state(channels), graph),
                                     graph, managed_nodes(channels))
    apply_changes(to_add, to_remove)
    return len(to_add), len(to_remove)
