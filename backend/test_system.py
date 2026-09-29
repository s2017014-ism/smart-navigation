from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from .main import app, transit_dataset
from .transit import (
    available_transit_graph,
    build_transit_graph,
    load_transit_dataset,
)


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    health = response.json()
    assert health["graph_loaded"] is True
    assert health["transit_loaded"] is True
    assert health["bus_route_count"] >= 100


def test_night_bus_routes_are_limited_to_midnight_service_hours() -> None:
    route_graph = build_transit_graph(
        load_transit_dataset(
            Path(__file__).parent / "data" / "macau_bus_routes.json"
        )
    )

    for hour, minute, expected in (
        (0, 0, True),
        (5, 59, True),
        (6, 0, False),
        (12, 0, False),
        (23, 59, False),
    ):
        available = available_transit_graph(
            route_graph, datetime(2026, 9, 28, hour, minute)
        )
        has_night_bus = any(
            data["route_name"].startswith("N")
            for _, data in available.nodes(data=True)
        )
        assert has_night_bus is expected


def test_routes_ending_in_s_are_excluded() -> None:
    dataset = load_transit_dataset(
        Path(__file__).parent / "data" / "macau_bus_routes.json"
    )
    route_graph = build_transit_graph(dataset)

    assert route_graph.number_of_nodes() > 0
    assert all(
        not data["route_name"].upper().endswith("S")
        for _, data in route_graph.nodes(data=True)
    )


def test_route_and_intent() -> None:
    client = TestClient(app)
    route = client.post("/route/plan", json={"start_lat": 22.218, "start_lon": 113.550, "end_lat": 22.155, "end_lon": 113.570})
    assert route.status_code == 200
    assert route.json()["success"] is True
    intent = client.post("/ai/parse_intent", json={"text": "坐公車，最多步行2公里"})
    assert intent.json()["prefer_bus"] is True
    assert intent.json()["max_walk_km"] == 2.0


def test_bus_route_uses_attached_route_data() -> None:
    route = next(
        route
        for route in transit_dataset.routes
        if route["name"] == "1" and route["direction"] == "0"
    )
    origin = transit_dataset.stops[route["stops"][0]]
    destination = transit_dataset.stops[route["stops"][-1]]
    response = TestClient(app).post(
        "/route/plan",
        json={
            "start_lat": origin["lat"],
            "start_lon": origin["lon"],
            "end_lat": destination["lat"],
            "end_lon": destination["lon"],
            "prefer_bus": True,
        },
    )

    assert response.status_code == 200
    options = response.json()["options"]
    geojson = next(
        option
        for option in options
        if option["properties"]["option_label"] == "直達巴士 1"
    )
    assert geojson["properties"]["routes"] == ["1"]
    assert geojson["properties"]["bus_distance"] > 0
    assert all(
        not route.upper().endswith("S")
        for option in options
        for route in option["properties"]["routes"]
    )
    assert response.json()["geojson"] == options[0]
    bus_features = [
        feature
        for feature in geojson["features"]
        if feature["properties"]["mode"] == "bus"
    ]
    assert len(bus_features) == 1
    assert len(bus_features[0]["geometry"]["coordinates"]) > 2
    assert bus_features[0]["properties"]["boarding_stop"]["name"]
    assert bus_features[0]["properties"]["alighting_stop"]["name"]
    walk_features = [
        feature
        for feature in geojson["features"]
        if feature["properties"]["mode"] == "walk"
    ]
    assert all(feature["properties"]["instruction"] for feature in walk_features)
