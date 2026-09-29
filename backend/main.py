from __future__ import annotations

import os
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import networkx as nx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .graph_builder import load_graph
from .places import (
    CATEGORY_LABELS,
    load_places,
    plan_tour,
    public_place,
)
from .router import haversine_m, path_coordinates, shortest_route
from .transit import (
    MACAU_TIMEZONE,
    available_transit_graph,
    build_transit_graph,
    load_transit_dataset,
    plan_transit_routes,
)

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = Path(os.getenv("GRAPH_PATH", ROOT / "data" / "macau_network.graphml"))
TRANSIT_PATH = Path(os.getenv("TRANSIT_PATH", Path(__file__).resolve().parent / "data" / "macau_bus_routes.json"))
PLACES_PATH = Path(os.getenv("PLACES_PATH", Path(__file__).resolve().parent / "data" / "macau_places.json"))
app = FastAPI(title="Macau Adaptive Navigation API", version="2.0.0")
graph: nx.MultiDiGraph = load_graph(GRAPH_PATH)
ROAD_NETWORK_UNAVAILABLE = (
    "目前只載入測試路網，無法規劃真實道路。"
    "請確認 data/macau_network.graphml 存在並重新啟動後端。"
)
transit_dataset = load_transit_dataset(TRANSIT_PATH)
transit_graph = build_transit_graph(transit_dataset)
place_metadata, place_dataset = load_places(PLACES_PATH)
graph_node_ids = list(graph.nodes)
NODE_GRID_DEGREES = 0.002
graph_node_grid: dict[tuple[int, int], list[Any]] = defaultdict(list)
for node in graph_node_ids:
    data = graph.nodes[node]
    cell = (
        math.floor(float(data["y"]) / NODE_GRID_DEGREES),
        math.floor(float(data["x"]) / NODE_GRID_DEGREES),
    )
    graph_node_grid[cell].append(node)


class RouteRequest(BaseModel):
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    end_lat: float = Field(..., ge=-90, le=90)
    end_lon: float = Field(..., ge=-180, le=180)
    weight: str = "length"
    avoid_stairs: bool = False
    max_slope: float | None = Field(None, ge=0, le=100)
    max_walk_km: float | None = Field(None, ge=0)
    prefer_bus: bool = False
    wheelchair: bool = False
    preferences: dict[str, Any] = Field(default_factory=dict)


class IntentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class TourRequest(BaseModel):
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    duration_minutes: int = Field(..., ge=30, le=720)
    place_count: int = Field(..., ge=1, le=10)
    purposes: list[Literal["culture", "food", "architecture", "history"]] = Field(
        ..., min_length=1, max_length=4
    )


class UpdateRequest(RouteRequest):
    current_lat: float | None = Field(None, ge=-90, le=90)
    current_lon: float | None = Field(None, ge=-180, le=180)
    weather_alert: str | None = None


def nearest_node(lat: float, lon: float) -> Any:
    cell_y = math.floor(lat / NODE_GRID_DEGREES)
    cell_x = math.floor(lon / NODE_GRID_DEGREES)
    candidates: list[Any] = []
    for radius in range(100):
        if radius == 0:
            cells = [(cell_y, cell_x)]
        else:
            cells = [
                (cell_y + dy, cell_x + dx)
                for dy in range(-radius, radius + 1)
                for dx in range(-radius, radius + 1)
                if abs(dx) == radius or abs(dy) == radius
            ]
        for cell in cells:
            candidates.extend(graph_node_grid.get(cell, ()))
        if not candidates:
            continue

        nearest = min(
            candidates,
            key=lambda node: haversine_m(
                (lat, lon),
                (float(graph.nodes[node]["y"]), float(graph.nodes[node]["x"])),
            ),
        )
        distance = haversine_m(
            (lat, lon),
            (float(graph.nodes[nearest]["y"]), float(graph.nodes[nearest]["x"])),
        )
        y_gap = min(
            lat - (cell_y - radius) * NODE_GRID_DEGREES,
            (cell_y + radius + 1) * NODE_GRID_DEGREES - lat,
        ) * 111_195
        x_gap = min(
            lon - (cell_x - radius) * NODE_GRID_DEGREES,
            (cell_x + radius + 1) * NODE_GRID_DEGREES - lon,
        ) * 111_195 * math.cos(math.radians(lat))
        if distance <= min(y_gap, x_gap):
            return nearest
    raise RuntimeError("Could not find a road node near the requested coordinate")


stop_graph_nodes = {
    code: nearest_node(float(stop["lat"]), float(stop["lon"]))
    for code, stop in transit_dataset.stops.items()
}


def geojson_route(request: RouteRequest) -> dict[str, Any]:
    if graph.graph.get("is_fallback"):
        raise HTTPException(
            status_code=503,
            detail=ROAD_NETWORK_UNAVAILABLE,
        )
    if request.prefer_bus:
        routes = plan_transit_routes(
            graph,
            available_transit_graph(transit_graph, datetime.now(MACAU_TIMEZONE)),
            transit_dataset,
            stop_graph_nodes,
            (request.start_lat, request.start_lon),
            (request.end_lat, request.end_lon),
            nearest_node,
            request.preferences | {
                "avoid_stairs": request.avoid_stairs,
                "max_slope": request.max_slope,
                "max_walk_km": request.max_walk_km,
                "wheelchair": request.wheelchair,
            },
        )
        if not routes:
            detail = (
                "找不到符合步行距離限制的巴士路線"
                if request.max_walk_km is not None
                else "找不到可用巴士路線"
            )
            raise HTTPException(
                status_code=422 if request.max_walk_km is not None else 404,
                detail=detail,
            )
        primary = routes[0].copy()
        primary["options"] = routes
        return primary

    origin = nearest_node(request.start_lat, request.start_lon)
    destination = nearest_node(request.end_lat, request.end_lon)
    preferences = request.preferences | {
        "avoid_stairs": request.avoid_stairs,
        "max_slope": request.max_slope,
        "max_walk_km": request.max_walk_km,
        "prefer_bus": request.prefer_bus,
        "wheelchair": request.wheelchair,
    }
    result = shortest_route(graph, origin, destination, preferences)
    origin_data = graph.nodes[origin]
    destination_data = graph.nodes[destination]
    origin_coordinate = (float(origin_data["y"]), float(origin_data["x"]))
    destination_coordinate = (
        float(destination_data["y"]),
        float(destination_data["x"]),
    )
    access_distance = haversine_m(
        (request.start_lat, request.start_lon), origin_coordinate
    )
    egress_distance = haversine_m(
        destination_coordinate, (request.end_lat, request.end_lon)
    )
    total_distance = result.distance + access_distance + egress_distance
    if request.max_walk_km is not None and total_distance > request.max_walk_km * 1000 and not request.prefer_bus:
        raise HTTPException(status_code=422, detail="路線超過最大步行距離")
    coordinates = [[request.start_lon, request.start_lat]]
    for coordinate in path_coordinates(graph, result.nodes):
        if coordinate != coordinates[-1]:
            coordinates.append(coordinate)
    destination_coordinate = [request.end_lon, request.end_lat]
    if destination_coordinate != coordinates[-1]:
        coordinates.append(destination_coordinate)
    if total_distance <= 0 or len(coordinates) < 2:
        raise HTTPException(status_code=422, detail="起點與終點相同，無法規劃路線")
    total_time = total_distance / (25 / 3.6 if request.prefer_bus else 5 / 3.6)
    properties = {
        "total_distance": total_distance,
        "total_time": total_time,
        "walk_distance": total_distance if not request.prefer_bus else 0,
        "bus_distance": total_distance if request.prefer_bus else 0,
        "access_distance": access_distance + egress_distance,
        "num_transfers": 0,
        "weather_alert": None,
        "weight": request.weight,
        "node_count": len(result.nodes),
    }
    return {
        "type": "FeatureCollection",
        "properties": properties,
        "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": coordinates}, "properties": properties}],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "graph_loaded": graph is not None,
        "road_network_loaded": not graph.graph.get("is_fallback", False),
        "node_count": graph.number_of_nodes(),
        "transit_loaded": bool(transit_graph.number_of_edges()),
        "bus_stop_count": len(transit_dataset.stops),
        "bus_route_count": len(transit_dataset.routes),
        "place_count": len(place_dataset),
    }


@app.get("/places")
async def list_places(
    purpose: Literal["culture", "food", "architecture", "history"] | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    places = place_dataset
    if purpose is not None:
        places = [place for place in places if place["scores"][purpose] > 0]
    return {
        "metadata": place_metadata,
        "score_labels": CATEGORY_LABELS,
        "total": len(places),
        "places": [public_place(place) for place in places[:limit]],
    }


@app.post("/tour/plan")
async def plan_tour_route(request: TourRequest) -> dict[str, Any]:
    if len(set(request.purposes)) != len(request.purposes):
        raise HTTPException(status_code=422, detail="旅遊目的不可重複")
    if graph.graph.get("is_fallback"):
        raise HTTPException(status_code=503, detail=ROAD_NETWORK_UNAVAILABLE)
    try:
        itinerary = plan_tour(
            graph,
            place_dataset,
            (request.start_lat, request.start_lon),
            nearest_node,
            request.duration_minutes,
            request.place_count,
            request.purposes,
        )
    except (nx.NetworkXNoPath, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail="起點附近找不到可步行的道路") from exc
    if not itinerary["places"]:
        raise HTTPException(
            status_code=422,
            detail="所選目的附近沒有可用地點，或旅遊時間不足以到達第一個地點",
        )
    return {
        "success": True,
        "metadata": place_metadata,
        "score_labels": CATEGORY_LABELS,
        "summary": itinerary["summary"],
        "places": itinerary["places"],
        "geojson": {
            "type": "FeatureCollection",
            "properties": itinerary["summary"],
            "features": itinerary["features"],
        },
    }


@app.post("/route/plan")
async def plan_route(request: RouteRequest) -> dict[str, Any]:
    try:
        geojson = geojson_route(request)
    except nx.NetworkXNoPath as exc:
        raise HTTPException(status_code=404, detail="找不到可行路徑") from exc
    options = geojson.pop("options", None)
    response = {"success": True, "geojson": geojson}
    if options is not None:
        response["options"] = options
    return response


@app.post("/route/update")
async def update_route(request: UpdateRequest) -> dict[str, Any]:
    result = geojson_route(request)
    options = result.pop("options", None)
    result["properties"]["weather_alert"] = request.weather_alert
    response = {
        "success": True,
        "rerouted": request.current_lat is not None,
        "geojson": result,
    }
    if options is not None:
        response["options"] = options
    return response


@app.post("/ai/parse_intent")
async def parse_intent(request: IntentRequest) -> dict[str, Any]:
    text = request.text.lower()
    tags = []
    for keyword, tag in (("地質", "geology"), ("歷史", "history"), ("美食", "food"), ("購物", "shopping"), ("自然", "nature")):
        if keyword in text:
            tags.append(tag)
    return {
        "tags": tags,
        "avoid_stairs": any(word in text for word in ("不要爬坡", "不想爬坡", "避開階梯", "無障礙")),
        "max_slope": 8 if "無障礙" in text else (10 if "坡" in text else None),
        "max_walk_km": float(next((value for value in __import__("re").findall(r"(\d+(?:\.\d+)?)\s*(?:公里|km)", text)), 0)) or None,
        "prefer_bus": any(word in text for word in ("公車", "巴士", "公交")),
        "wheelchair": "輪椅" in text or "无障碍" in text or "無障礙" in text,
        "poi_category": tags[0] if tags else None,
    }


@app.get("/geocode/search")
async def geocode_search(q: str = Query(..., min_length=2), limit: int = Query(5, ge=1, le=10)) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get("https://nominatim.openstreetmap.org/search", params={"q": f"{q}, Macau", "format": "json", "limit": limit}, headers={"User-Agent": "MacauNavigation/2.0"})
    response.raise_for_status()
    return response.json()


@app.get("/geocode/reverse")
async def geocode_reverse(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get("https://nominatim.openstreetmap.org/reverse", params={"lat": lat, "lon": lon, "format": "json"}, headers={"User-Agent": "MacauNavigation/2.0"})
    response.raise_for_status()
    return response.json()
