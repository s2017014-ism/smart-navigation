from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import networkx as nx

from .router import haversine_m, path_coordinates, path_length_m, walking_edge_cost

WALK_SPEED_MPS = 5 / 3.6
BUS_SPEED_MPS = 25 / 3.6
BUS_WAIT_SECONDS = 300
STOP_SNAP_LIMIT_M = 250
MACAU_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Macau")


def is_night_bus_active(now: datetime) -> bool:
    local_time = now.astimezone(MACAU_TIMEZONE).time() if now.tzinfo else now.time()
    return time(0, 0) <= local_time < time(6, 0)


def available_transit_graph(
    transit_graph: nx.DiGraph, now: datetime
) -> nx.DiGraph:
    if is_night_bus_active(now):
        return transit_graph
    available_nodes = [
        node
        for node, data in transit_graph.nodes(data=True)
        if not str(data["route_name"]).upper().startswith("N")
    ]
    return transit_graph.subgraph(available_nodes).copy()


@dataclass
class TransitDataset:
    stops: dict[str, dict[str, Any]]
    routes: list[dict[str, Any]]


def load_transit_dataset(path: Path) -> TransitDataset:
    payload = json.loads(path.read_text(encoding="utf-8"))
    stops = payload["stops"]
    routes = payload["routes"]
    if not isinstance(stops, dict) or not isinstance(routes, list):
        raise ValueError(f"Invalid transit dataset structure in {path}")

    for code, stop in stops.items():
        lat, lon = float(stop["lat"]), float(stop["lon"])
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError(f"Invalid coordinates for transit stop {code}")
    for route in routes:
        if not route.get("name") or not route.get("direction") or not isinstance(route.get("stops"), list):
            raise ValueError(f"Invalid route entry in {path}")
    return TransitDataset(stops=stops, routes=routes)


def build_transit_graph(dataset: TransitDataset) -> nx.DiGraph:
    transit_graph = nx.DiGraph()
    stop_events: dict[str, list[tuple[int, int]]] = {}

    for route_index, route in enumerate(dataset.routes):
        if str(route["name"]).upper().endswith("S"):
            continue
        mapped_events = [
            (sequence_index, code)
            for sequence_index, code in enumerate(route["stops"])
            if code in dataset.stops
        ]
        for sequence_index, code in mapped_events:
            state = (route_index, sequence_index)
            transit_graph.add_node(
                state,
                stop_code=code,
                route_name=route["name"],
                direction=route["direction"],
            )
            stop_events.setdefault(code, []).append(state)

        for (left_index, left_code), (right_index, right_code) in zip(mapped_events, mapped_events[1:]):
            if left_code == right_code:
                continue
            left = dataset.stops[left_code]
            right = dataset.stops[right_code]
            distance = haversine_m((left["lat"], left["lon"]), (right["lat"], right["lon"])) * 1.3
            transit_graph.add_edge(
                (route_index, left_index),
                (route_index, right_index),
                mode="bus",
                cost=distance / BUS_SPEED_MPS,
                distance_m=distance,
                from_stop=left_code,
                to_stop=right_code,
                route_name=route["name"],
                direction=route["direction"],
                skipped_stops=route["stops"][left_index + 1:right_index],
            )

    for code, events in stop_events.items():
        for left in events:
            for right in events:
                if left == right:
                    continue
                left_route = transit_graph.nodes[left]
                right_route = transit_graph.nodes[right]
                if (left_route["route_name"], left_route["direction"]) == (
                    right_route["route_name"],
                    right_route["direction"],
                ):
                    continue
                transit_graph.add_edge(
                    left,
                    right,
                    mode="transfer",
                    cost=BUS_WAIT_SECONDS,
                    stop_code=code,
                )
    return transit_graph


def _append_coordinates(
    target: list[list[float]],
    coordinates: list[list[float]],
) -> None:
    for coordinate in coordinates:
        if not target or target[-1] != coordinate:
            target.append(coordinate)


def _bus_path_coordinates(
    graph: nx.MultiDiGraph, nodes: list[Any]
) -> list[list[float]]:
    coordinates: list[list[float]] = []
    for start, end in zip(nodes, nodes[1:]):
        if graph.has_edge(start, end):
            segment = path_coordinates(graph, [start, end])
        else:
            segment = list(reversed(path_coordinates(graph, [end, start])))
        _append_coordinates(coordinates, segment)
    return coordinates


def _bus_path_length_m(graph: nx.MultiDiGraph, nodes: list[Any]) -> float:
    distance = 0.0
    for start, end in zip(nodes, nodes[1:]):
        edges = graph.get_edge_data(start, end) or graph.get_edge_data(end, start) or {}
        edge = min(edges.values(), key=lambda item: float(item.get("length", 1)))
        distance += float(edge.get("length", 1))
    return distance


def _point(lat: float, lon: float) -> list[float]:
    return [float(lon), float(lat)]


def _walk_feature(
    graph: nx.MultiDiGraph,
    origin: tuple[float, float],
    destination: tuple[float, float],
    nodes: list[Any],
    distance: float,
    instruction: str,
) -> dict[str, Any]:
    coordinates = [_point(*origin)]
    _append_coordinates(coordinates, path_coordinates(graph, nodes))
    _append_coordinates(coordinates, [_point(*destination)])
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "mode": "walk",
            "distance": distance,
            "instruction": instruction,
        },
    }


def _bus_feature(
    graph: nx.MultiDiGraph,
    dataset: TransitDataset,
    stop_graph_nodes: dict[str, Any],
    bus_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    coordinates: list[list[float]] = []
    distance = 0.0
    stop_codes: list[str] = []
    for edge in bus_edges:
        start = dataset.stops[edge["from_stop"]]
        end = dataset.stops[edge["to_stop"]]
        start_node = stop_graph_nodes[edge["from_stop"]]
        end_node = stop_graph_nodes[edge["to_stop"]]
        try:
            road_nodes = nx.shortest_path(
                graph, start_node, end_node, weight="length"
            )
        except nx.NetworkXNoPath:
            road_nodes = nx.shortest_path(
                graph.to_undirected(as_view=True),
                start_node,
                end_node,
                weight="length",
            )
        segment = [_point(start["lat"], start["lon"])]
        _append_coordinates(segment, _bus_path_coordinates(graph, road_nodes))
        _append_coordinates(segment, [_point(end["lat"], end["lon"])])
        _append_coordinates(coordinates, segment)
        distance += (
            _bus_path_length_m(graph, road_nodes)
            + haversine_m((start["lat"], start["lon"]), (
                float(graph.nodes[start_node]["y"]), float(graph.nodes[start_node]["x"])
            ))
            + haversine_m((end["lat"], end["lon"]), (
                float(graph.nodes[end_node]["y"]), float(graph.nodes[end_node]["x"])
            ))
        )
        if not stop_codes:
            stop_codes.append(edge["from_stop"])
        stop_codes.append(edge["to_stop"])

    first = bus_edges[0]
    boarding = dataset.stops[first["from_stop"]]
    alighting = dataset.stops[bus_edges[-1]["to_stop"]]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "mode": "bus",
            "route_name": first["route_name"],
            "direction": first["direction"],
            "stops": stop_codes,
            "boarding_stop": {
                "code": first["from_stop"],
                "name": boarding["name"],
            },
            "alighting_stop": {
                "code": bus_edges[-1]["to_stop"],
                "name": alighting["name"],
            },
            "distance": distance,
        },
    }


def plan_transit_routes(
    graph: nx.MultiDiGraph,
    transit_graph: nx.DiGraph,
    dataset: TransitDataset,
    stop_graph_nodes: dict[str, Any],
    origin: tuple[float, float],
    destination: tuple[float, float],
    nearest_node: Callable[[float, float], Any],
    preferences: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    preferences = preferences or {}
    origin_node = nearest_node(*origin)
    destination_node = nearest_node(*destination)
    walk_weight = lambda u, v, data: walking_edge_cost(u, v, data, preferences)
    forward_lengths, forward_paths = nx.single_source_dijkstra(
        graph, origin_node, weight=walk_weight
    )
    reverse_graph = graph.reverse(copy=False)
    reverse_lengths, reverse_paths = nx.single_source_dijkstra(
        reverse_graph, destination_node, weight=walk_weight
    )
    origin_snap_distance = haversine_m(
        origin,
        (float(graph.nodes[origin_node]["y"]), float(graph.nodes[origin_node]["x"])),
    )
    destination_snap_distance = haversine_m(
        destination,
        (float(graph.nodes[destination_node]["y"]), float(graph.nodes[destination_node]["x"])),
    )
    max_walk_m = (
        float(preferences["max_walk_km"]) * 1000
        if preferences.get("max_walk_km") is not None
        else math.inf
    )

    access: dict[str, tuple[float, list[Any]]] = {}
    egress: dict[str, tuple[float, list[Any]]] = {}
    for code, stop in dataset.stops.items():
        road_node = stop_graph_nodes[code]
        stop_snap_distance = haversine_m(
            (stop["lat"], stop["lon"]),
            (float(graph.nodes[road_node]["y"]), float(graph.nodes[road_node]["x"])),
        )
        if stop_snap_distance > STOP_SNAP_LIMIT_M:
            continue
        if road_node in forward_paths:
            path = forward_paths[road_node]
            distance = (
                origin_snap_distance
                + path_length_m(graph, path)
                + stop_snap_distance
            )
            if distance <= max_walk_m:
                access[code] = (distance, path)
        if road_node in reverse_paths:
            reverse_path = reverse_paths[road_node]
            path = list(reversed(reverse_path))
            distance = (
                path_length_m(graph, path)
                + destination_snap_distance
                + stop_snap_distance
            )
            if distance <= max_walk_m:
                egress[code] = (distance, path)

    source, target = object(), object()
    search_graph = transit_graph.copy()
    search_graph.add_node(source)
    search_graph.add_node(target)
    for state, data in transit_graph.nodes(data=True):
        code = data["stop_code"]
        if code in access:
            distance, _ = access[code]
            search_graph.add_edge(
                source,
                state,
                mode="access",
                cost=distance / WALK_SPEED_MPS + BUS_WAIT_SECONDS,
                stop_code=code,
            )
        if code in egress:
            distance, _ = egress[code]
            search_graph.add_edge(
                state,
                target,
                mode="egress",
                cost=distance / WALK_SPEED_MPS,
                stop_code=code,
            )

    def build_result(selected_edges: list[dict[str, Any]]) -> dict[str, Any] | None:
        bus_edges = [edge for edge in selected_edges if edge["mode"] == "bus"]
        if not bus_edges:
            return None

        access_code = selected_edges[0]["stop_code"]
        egress_code = selected_edges[-1]["stop_code"]
        access_distance, access_path = access[access_code]
        egress_distance, egress_path = egress[egress_code]
        total_walk = access_distance + egress_distance
        if total_walk > max_walk_m:
            return None

        features: list[dict[str, Any]] = []
        if access_distance > 0:
            features.append(
                _walk_feature(
                    graph,
                    origin,
                    (dataset.stops[access_code]["lat"], dataset.stops[access_code]["lon"]),
                    access_path,
                    access_distance,
                    f"步行至 {dataset.stops[access_code]['name']}",
                )
            )

        current_bus_edges: list[dict[str, Any]] = []
        current_route: tuple[str, str] | None = None
        transfers = 0
        for edge in selected_edges:
            if edge["mode"] == "bus":
                route = (edge["route_name"], edge["direction"])
                if current_bus_edges and route != current_route:
                    features.append(
                        _bus_feature(graph, dataset, stop_graph_nodes, current_bus_edges)
                    )
                    current_bus_edges = []
                current_route = route
                current_bus_edges.append(edge)
            elif edge["mode"] == "transfer":
                transfers += 1
                if current_bus_edges:
                    features.append(
                        _bus_feature(graph, dataset, stop_graph_nodes, current_bus_edges)
                    )
                    current_bus_edges = []
                    current_route = None
        if current_bus_edges:
            features.append(_bus_feature(graph, dataset, stop_graph_nodes, current_bus_edges))
        if egress_distance > 0:
            features.append(
                _walk_feature(
                    graph,
                    (dataset.stops[egress_code]["lat"], dataset.stops[egress_code]["lon"]),
                    destination,
                    egress_path,
                    egress_distance,
                    f"從 {dataset.stops[egress_code]['name']} 步行至目的地",
                )
            )

        walk_duration = total_walk / WALK_SPEED_MPS
        bus_distance = sum(
            float(feature["properties"]["distance"])
            for feature in features
            if feature["properties"]["mode"] == "bus"
        )
        bus_duration = bus_distance / BUS_SPEED_MPS
        wait_duration = BUS_WAIT_SECONDS * (transfers + 1)
        properties = {
            "total_distance": total_walk + bus_distance,
            "total_time": walk_duration + bus_duration + wait_duration,
            "walk_distance": total_walk,
            "bus_distance": bus_distance,
            "num_transfers": transfers,
            "routes": list(dict.fromkeys(
                feature["properties"]["route_name"]
                for feature in features
                if feature["properties"]["mode"] == "bus"
            )),
            "node_count": sum(
                len(feature["geometry"]["coordinates"]) for feature in features
            ),
        }
        for feature in features:
            feature["properties"]["total_distance"] = properties["total_distance"]
        return {"type": "FeatureCollection", "properties": properties, "features": features}

    results: list[dict[str, Any]] = []
    route_keys = {
        (data["route_name"], data["direction"])
        for _, data in transit_graph.nodes(data=True)
    }
    for route_name, direction in sorted(route_keys):
        route_states = [
            state
            for state, data in transit_graph.nodes(data=True)
            if (data["route_name"], data["direction"]) == (route_name, direction)
        ]
        direct_graph = search_graph.subgraph([source, target, *route_states])
        try:
            direct_path = nx.shortest_path(
                direct_graph, source, target, weight="cost"
            )
        except nx.NetworkXNoPath:
            continue
        edges = [
            direct_graph.get_edge_data(left, right)
            for left, right in zip(direct_path, direct_path[1:])
        ]
        route = build_result(edges)
        if route is not None:
            route["properties"]["option_type"] = "direct"
            route["properties"]["option_label"] = f"直達巴士 {route_name}"
            results.append(route)

    layered_graph = nx.DiGraph()
    layered_source, layered_target = object(), object()
    for state, data in transit_graph.nodes(data=True):
        for transfer_state in (0, 1, 2):
            layered_graph.add_node((state, transfer_state), **data)
    for left, right, data in search_graph.edges(data=True):
        if left is source:
            layered_graph.add_edge(layered_source, (right, 0), **data)
        elif right is target:
            layered_graph.add_edge((left, 2), layered_target, **data)
        else:
            mode = data["mode"]
            for transfer_state in (0, 1, 2):
                if mode == "transfer":
                    if transfer_state == 0:
                        layered_graph.add_edge((left, 0), (right, 1), **data)
                elif mode == "bus":
                    next_state = 2 if transfer_state == 1 else transfer_state
                    layered_graph.add_edge(
                        (left, transfer_state), (right, next_state), **data
                    )
                else:
                    layered_graph.add_edge(
                        (left, transfer_state), (right, transfer_state), **data
                    )

    try:
        transfer_path = nx.shortest_path(
            layered_graph, layered_source, layered_target, weight="cost"
        )
    except nx.NetworkXNoPath:
        transfer_path = []
    if transfer_path:
        transfer_edges = [
            layered_graph.get_edge_data(left, right)
            for left, right in zip(transfer_path, transfer_path[1:])
        ]
        transfer_route = build_result(transfer_edges)
        if transfer_route is not None:
            transfer_route["properties"]["option_type"] = "transfer"
            transfer_route["properties"]["option_label"] = (
                "最快轉乘方案：" + " → ".join(transfer_route["properties"]["routes"])
            )
            results.append(transfer_route)

    results.sort(key=lambda route: route["properties"]["total_time"])
    return results
