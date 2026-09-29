from datetime import datetime
from pathlib import Path

import networkx as nx
from fastapi.testclient import TestClient

from . import graph_builder
from . import main as navigation_api
from .main import RouteRequest, app, transit_dataset
from .router import path_coordinates
from .transit import (
    available_transit_graph,
    build_transit_graph,
    load_transit_dataset,
)


def test_load_graph_uses_graphml_without_osmnx(tmp_path: Path, monkeypatch) -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("start", x=113.5, y=22.2)
    graph.add_node("end", x=113.6, y=22.3)
    graph.add_edge(
        "start",
        "end",
        length=100,
        geometry="LINESTRING (113.5 22.2, 113.55 22.25, 113.6 22.3)",
    )
    graph_path = tmp_path / "network.graphml"
    nx.write_graphml(graph, graph_path)
    monkeypatch.setattr(graph_builder, "ox", None)

    loaded_graph = graph_builder.load_graph(graph_path)

    assert loaded_graph.number_of_nodes() == 2
    assert loaded_graph.number_of_edges() == 1
    assert loaded_graph.nodes["start"]["x"] == 113.5
    assert path_coordinates(loaded_graph, ["start", "end"]) == [
        [113.5, 22.2],
        [113.55, 22.25],
        [113.6, 22.3],
    ]


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    health = response.json()
    assert health["graph_loaded"] is True
    assert health["road_network_loaded"] is True
    assert health["transit_loaded"] is True
    assert health["bus_route_count"] >= 100
    assert health["place_count"] >= 400


def test_places_have_evidence_based_scores_for_all_purposes() -> None:
    client = TestClient(app)
    vectors = set()
    for purpose in ("culture", "food", "architecture", "history"):
        response = client.get("/places", params={"purpose": purpose, "limit": 1})
        assert response.status_code == 200
        assert response.json()["total"] > 0
        place = response.json()["places"][0]
        assert place["scores"][purpose] > 0
        assert set(place["scores"]) == {
            "culture",
            "food",
            "architecture",
            "history",
        }
        vectors.add(tuple(place["scores"][category] for category in (
            "culture",
            "food",
            "architecture",
            "history",
        )))
        assert response.json()["metadata"]["attribution"]
    assert len(vectors) > 1


def test_tour_plan_respects_selected_purpose_count_and_time_budget() -> None:
    response = TestClient(app).post(
        "/tour/plan",
        json={
            "start_lat": 22.192,
            "start_lon": 113.539,
            "duration_minutes": 180,
            "place_count": 3,
            "purposes": ["food"],
        },
    )

    if navigation_api.graph.graph.get("is_fallback"):
        assert response.status_code == 503
        return

    assert response.status_code == 200
    result = response.json()
    assert 1 <= len(result["places"]) <= 3
    assert result["summary"]["used_minutes"] <= 180
    assert result["summary"]["planned_places"] == len(result["places"])
    assert len(result["geojson"]["features"]) == len(result["places"])
    assert all(place["scores"]["food"] > 0 for place in result["places"])
    assert [place["sequence"] for place in result["places"]] == [1, 2, 3][
        : len(result["places"])
    ]


def test_tour_plan_rejects_duplicate_purposes() -> None:
    response = TestClient(app).post(
        "/tour/plan",
        json={
            "start_lat": 22.192,
            "start_lon": 113.539,
            "duration_minutes": 120,
            "place_count": 2,
            "purposes": ["history", "history"],
        },
    )

    assert response.status_code == 422


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
    if navigation_api.graph.graph.get("is_fallback"):
        assert route.status_code == 503
        assert "測試路網" in route.json()["detail"]
    else:
        assert route.status_code == 200
        assert route.json()["success"] is True
        assert route.json()["geojson"]["properties"]["total_distance"] > 0
        coordinates = route.json()["geojson"]["features"][0]["geometry"][
            "coordinates"
        ]
        assert len(coordinates) > 2
        assert coordinates[0] == [113.550, 22.218]
        assert coordinates[-1] == [113.570, 22.155]
    intent = client.post("/ai/parse_intent", json={"text": "坐公車，最多步行2公里"})
    assert intent.json()["prefer_bus"] is True
    assert intent.json()["max_walk_km"] == 2.0


def test_route_between_points_snapped_to_same_node_has_nonzero_distance(
    monkeypatch,
) -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("road", x=113.539, y=22.192)
    monkeypatch.setattr(navigation_api, "graph", graph)
    monkeypatch.setattr(navigation_api, "nearest_node", lambda _lat, _lon: "road")

    route = navigation_api.geojson_route(
        RouteRequest(
            start_lat=22.192,
            start_lon=113.539,
            end_lat=22.1921,
            end_lon=113.5391,
        )
    )

    assert route["properties"]["total_distance"] > 0
    assert route["properties"]["total_time"] > 0
    assert route["features"][0]["geometry"]["coordinates"] == [
        [113.539, 22.192],
        [113.5391, 22.1921],
    ]


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

    if navigation_api.graph.graph.get("is_fallback"):
        assert response.status_code == 503
        return

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
