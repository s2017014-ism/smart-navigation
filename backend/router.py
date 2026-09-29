from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import networkx as nx


@dataclass
class RouteResult:
    nodes: list[Any]
    distance: float
    duration: float


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _edge_cost(edge: dict[str, Any], preferences: dict[str, Any]) -> float:
    highway = edge.get("highway", "")
    highways = highway if isinstance(highway, (list, tuple, set)) else (highway,)
    if preferences.get("avoid_stairs") and "steps" in highways:
        return math.inf

    slope = float(edge.get("slope", 0))
    max_slope = preferences.get("max_slope")
    if max_slope is not None and slope > float(max_slope):
        return math.inf
    if preferences.get("wheelchair") and slope > 8:
        return math.inf

    return float(edge.get("length", 1)) * (1 + slope / 100)


def walking_edge_cost(_u: Any, _v: Any, data: dict[str, Any], preferences: dict[str, Any]) -> float:
    if data and all(isinstance(edge, dict) for edge in data.values()):
        return min((_edge_cost(edge, preferences) for edge in data.values()), default=math.inf)
    return _edge_cost(data, preferences)


def path_length_m(graph: nx.MultiDiGraph, nodes: list[Any]) -> float:
    distance = 0.0
    for current, following in zip(nodes, nodes[1:]):
        edges = graph.get_edge_data(current, following) or {}
        edge = min(edges.values(), key=lambda item: float(item.get("length", 1)))
        distance += float(edge.get("length", 1))
    return distance


def path_coordinates(graph: nx.MultiDiGraph, nodes: list[Any]) -> list[list[float]]:
    if not nodes:
        return []

    def node_coordinate(node: Any) -> tuple[float, float]:
        data = graph.nodes[node]
        return float(data["x"]), float(data["y"])

    coordinates: list[tuple[float, float]] = [node_coordinate(nodes[0])]
    for current, following in zip(nodes, nodes[1:]):
        edges = graph.get_edge_data(current, following) or {}
        edge = min(edges.values(), key=lambda item: float(item.get("length", 1)))
        geometry = edge.get("geometry")
        if geometry is not None and hasattr(geometry, "coords"):
            segment = [(float(lon), float(lat)) for lon, lat in geometry.coords]
            if segment:
                start = node_coordinate(current)
                if math.dist(segment[0], start) > math.dist(segment[-1], start):
                    segment.reverse()
        else:
            segment = [node_coordinate(current), node_coordinate(following)]
        coordinates.extend(segment[1:])
        end = node_coordinate(following)
        if coordinates[-1] != end:
            coordinates.append(end)
    return [[lon, lat] for lon, lat in coordinates]


def shortest_route(
    graph: nx.MultiDiGraph,
    origin: Any,
    destination: Any,
    preferences: dict[str, Any] | None = None,
) -> RouteResult:
    preferences = preferences or {}

    cost = lambda u, v, data: walking_edge_cost(u, v, data, preferences)
    nodes = nx.shortest_path(graph, origin, destination, weight=cost)
    distance = path_length_m(graph, nodes)
    speed = 25 / 3.6 if preferences.get("prefer_bus") else 5 / 3.6
    return RouteResult(nodes=nodes, distance=distance, duration=distance / speed)
