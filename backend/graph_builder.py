from __future__ import annotations

from pathlib import Path

import networkx as nx

try:
    import osmnx as ox
except ImportError:  # pragma: no cover - optional for offline fallback
    ox = None


def build_fallback_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    points = {
        "north": (22.218, 113.550),
        "center": (22.192, 113.539),
        "south": (22.155, 113.570),
        "west": (22.188, 113.535),
        "east": (22.188, 113.548),
    }
    for node, (lat, lon) in points.items():
        graph.add_node(node, y=lat, x=lon)
    links = [
        ("north", "center"), ("center", "south"), ("center", "west"),
        ("center", "east"), ("west", "south"), ("east", "south"),
    ]
    for left, right in links:
        a = points[left]
        b = points[right]
        length = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 * 111_000
        graph.add_edge(left, right, length=length, slope=2, highway="residential")
        graph.add_edge(right, left, length=length, slope=2, highway="residential")
    return graph


def load_graph(path: Path) -> nx.MultiDiGraph:
    if path.exists():
        if ox is not None:
            return ox.load_graphml(path)
        return nx.read_graphml(path, force_multigraph=True)
    return build_fallback_graph()


def download_macau_network(output: Path) -> nx.MultiDiGraph:
    if ox is None:
        raise RuntimeError("OSMnx is required to download a real road network")
    output.parent.mkdir(parents=True, exist_ok=True)
    graph = ox.graph_from_place("Macau", network_type="walk")
    ox.save_graphml(graph, filepath=output)
    return graph
