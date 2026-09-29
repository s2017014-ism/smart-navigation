from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

import networkx as nx

from .router import haversine_m, path_coordinates


CATEGORIES = ("culture", "food", "architecture", "history")
CATEGORY_LABELS = {
    "culture": "文化",
    "food": "美食",
    "architecture": "建築",
    "history": "歷史",
}

_TOURISM_CULTURE = {
    "museum": 96,
    "gallery": 90,
    "arts_centre": 90,
    "theatre": 86,
    "attraction": 82,
    "artwork": 78,
    "zoo": 72,
    "aquarium": 72,
    "cinema": 58,
}
_AMENITY_CULTURE = {
    "arts_centre": 94,
    "place_of_worship": 75,
    "library": 68,
    "theatre": 86,
    "community_centre": 54,
    "social_centre": 50,
    "fountain": 45,
    "cinema": 58,
    "planetarium": 78,
}
_HISTORIC_SCORE = {
    "archaeological_site": 100,
    "castle": 98,
    "fort": 98,
    "ruins": 96,
    "monument": 94,
    "memorial": 90,
    "city_gate": 88,
    "church": 84,
    "building": 78,
    "wayside_shrine": 72,
    "yes": 70,
}
_FOOD_SCORE = {
    "restaurant": 94,
    "cafe": 82,
    "food_court": 78,
    "fast_food": 62,
    "beverages": 76,
    "yes": 48,
}


def load_places(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    places = payload["places"]
    for place in places:
        place["scores"] = score_place(place)
        place["visit_minutes"] = estimated_visit_minutes(place)
    return payload["metadata"], places


def score_place(place: dict[str, Any]) -> dict[str, int]:
    tourism = str(place.get("tourism") or "").lower()
    amenity = str(place.get("amenity") or "").lower()
    historic = str(place.get("historic") or "").lower()
    heritage = str(place.get("heritage") or "").lower()

    culture = max(
        _TOURISM_CULTURE.get(tourism, 0),
        _AMENITY_CULTURE.get(amenity, 0),
    )
    history = max(
        100 if heritage and heritage not in {"no", "heritage"} else 0,
        _HISTORIC_SCORE.get(historic, 0),
        74 if tourism == "museum" else 0,
    )
    architecture = max(
        96 if historic in {"building", "castle", "fort", "ruins", "city_gate"} else 0,
        90 if heritage and heritage not in {"no", "heritage"} else 0,
        84 if historic in {"monument", "memorial"} else 0,
        72 if amenity == "place_of_worship" else 0,
        64 if tourism in {"museum", "gallery", "artwork"} else 0,
    )
    food = _FOOD_SCORE.get(amenity, 0)
    if food and place.get("cuisine"):
        food = min(100, food + 6)

    return {
        "culture": culture,
        "food": food,
        "architecture": architecture,
        "history": history,
    }


def estimated_visit_minutes(place: dict[str, Any]) -> int:
    tourism = str(place.get("tourism") or "").lower()
    amenity = str(place.get("amenity") or "").lower()
    historic = str(place.get("historic") or "").lower()
    if amenity in _FOOD_SCORE:
        return 45 if amenity in {"restaurant", "food_court"} else 30
    if tourism in {"museum", "zoo", "aquarium", "attraction"}:
        return 60
    if tourism in {"gallery", "arts_centre", "theatre"}:
        return 45
    if historic in {"fort", "castle", "ruins"}:
        return 40
    return 25


def purpose_score(place: dict[str, Any], purposes: list[str]) -> float:
    scores = place["scores"]
    return sum(scores[purpose] for purpose in purposes) / len(purposes)


def public_place(place: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": place["id"],
        "name": place.get("name_yue")
        or place.get("name")
        or place.get("name_en")
        or place.get("name_latin")
        or "未命名地點",
        "name_en": place.get("name_en") or place.get("name_latin"),
        "lat": place["lat"],
        "lon": place["lon"],
        "kind": place["kind"],
        "scores": place["scores"],
        "visit_minutes": place["visit_minutes"],
        "opening_hours": place.get("opening_hours"),
        "website": place.get("website"),
        "description": place.get("description"),
        "cuisine": place.get("cuisine"),
        "amenity": place.get("amenity"),
        "tourism": place.get("tourism"),
        "historic": place.get("historic"),
        "heritage": place.get("heritage"),
        "operator": place.get("operator"),
        "source_id": place["id"],
    }


def plan_tour(
    graph: nx.MultiDiGraph,
    places: list[dict[str, Any]],
    start: tuple[float, float],
    nearest_node: Callable[[float, float], Any],
    duration_minutes: int,
    place_count: int,
    purposes: list[str],
) -> dict[str, Any]:
    origin_node = nearest_node(*start)
    origin_snap = haversine_m(
        start,
        (float(graph.nodes[origin_node]["y"]), float(graph.nodes[origin_node]["x"])),
    )
    candidates = [
        place
        for place in places
        if purpose_score(place, purposes) > 0
    ]
    node_cache: dict[str, tuple[Any, float]] = {}
    for place in candidates:
        try:
            node = nearest_node(float(place["lat"]), float(place["lon"]))
        except RuntimeError:
            continue
        node_cache[place["id"]] = (
            node,
            haversine_m(
                (float(place["lat"]), float(place["lon"])),
                (float(graph.nodes[node]["y"]), float(graph.nodes[node]["x"])),
            ),
        )

    selected: list[dict[str, Any]] = []
    remaining = duration_minutes
    current_node = origin_node
    current_position = start
    current_snap = origin_snap
    used_ids: set[str] = set()
    features: list[dict[str, Any]] = []
    total_distance = 0.0
    total_travel = 0
    total_visit = 0

    for sequence in range(1, place_count + 1):
        lengths, paths = nx.single_source_dijkstra(
            graph, current_node, weight="length"
        )
        choices: list[tuple[float, float, int, str, dict[str, Any], list[Any], float]] = []
        for place in candidates:
            place_id = place["id"]
            if place_id in used_ids or place_id not in node_cache:
                continue
            destination_node, destination_snap = node_cache[place_id]
            if destination_node not in paths:
                continue
            route_nodes = paths[destination_node]
            route_distance = (
                current_snap
                + float(lengths[destination_node])
                + destination_snap
            )
            travel_minutes = math.ceil(route_distance / (5 / 3.6) / 60)
            visit_minutes = int(place["visit_minutes"])
            required_minutes = travel_minutes + visit_minutes
            if required_minutes > remaining:
                continue
            score = purpose_score(place, purposes)
            choices.append(
                (
                    -(score / max(required_minutes, 1)),
                    -score,
                    required_minutes,
                    str(place.get("name") or place.get("name_en") or place_id),
                    place,
                    route_nodes,
                    route_distance,
                )
            )
        if not choices:
            break

        _, negative_score, required_minutes, _, place, route_nodes, route_distance = min(
            choices, key=lambda choice: choice[:4]
        )
        travel_minutes = required_minutes - int(place["visit_minutes"])
        score = -negative_score
        name = (
            place.get("name_yue")
            or place.get("name")
            or place.get("name_en")
            or place.get("name_latin")
            or "未命名地點"
        )
        destination = (float(place["lat"]), float(place["lon"]))
        coordinates = [[float(current_position[1]), float(current_position[0])]]
        coordinates.extend(path_coordinates(graph, route_nodes))
        coordinates.append([destination[1], destination[0]])
        deduplicated: list[list[float]] = []
        for coordinate in coordinates:
            if not deduplicated or coordinate != deduplicated[-1]:
                deduplicated.append(coordinate)

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": deduplicated},
                "properties": {
                    "mode": "walk",
                    "sequence": sequence,
                    "to_place": place["id"],
                    "distance": route_distance,
                    "duration_minutes": travel_minutes,
                    "instruction": f"步行至 {name}",
                },
            }
        )
        selected_place = public_place(place)
        selected_place.update(
            {
                "sequence": sequence,
                "relevance_score": round(score),
                "matched_purposes": purposes,
                "travel_minutes": travel_minutes,
                "arrival_after_minutes": duration_minutes - remaining + travel_minutes,
            }
        )
        selected.append(selected_place)
        used_ids.add(place["id"])
        remaining -= required_minutes
        total_distance += route_distance
        total_travel += travel_minutes
        total_visit += int(place["visit_minutes"])
        current_node = node_cache[place["id"]][0]
        current_position = destination
        current_snap = node_cache[place["id"]][1]

    return {
        "places": selected,
        "features": features,
        "summary": {
            "duration_budget_minutes": duration_minutes,
            "travel_minutes": total_travel,
            "visit_minutes": total_visit,
            "used_minutes": total_travel + total_visit,
            "remaining_minutes": remaining,
            "requested_places": place_count,
            "planned_places": len(selected),
            "purposes": purposes,
            "total_walking_distance": total_distance,
        },
    }
