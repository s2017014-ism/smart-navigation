# Smart Navigation

A Python (FastAPI) + Flutter adaptive travel navigation system for Macau with:
- Natural language intent parsing (Qwen3 API compatible)
- Multi-modal routing (walking + bus)
- Terrain & stairs avoidance
- Dynamic re-routing based on GPS deviation & weather

## Project Structure

```
├── backend/
│   ├── main.py              # FastAPI application with REST endpoints
│   ├── graph_builder.py     # OSMnx graph loading and offline fallback graph
│   ├── router.py            # Adaptive shortest-path routing
│   ├── transit.py           # Walking-to-bus and bus-transfer routing
│   ├── places.py            # Public-attribute scores and tour planning
│   ├── data/
│   │   └── macau_bus_routes.json # Bus stop sequences and matched coordinates
│   │   └── macau_places.json     # HOTOSM/OSM cultural and food places
│   ├── test_system.py       # Backend smoke tests
│   └── requirements.txt     # Backend dependencies
├── frontend/
│   ├── pubspec.yaml         # Flutter dependencies
│   └── lib/main.dart        # Flutter map, tour planner, and navigation UI
```

## Backend API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/places` | GET | Browse places and their four purpose scores |
| `/tour/plan` | POST | Select places and order a timed tour |
| `/route/plan` | POST | Plan route with preferences |
| `/ai/parse_intent` | POST | Parse natural language to structured params |
| `/route/update` | POST | Dynamic re-routing for GPS deviation/weather |
| `/geocode/search` | GET | Nominatim place search proxy |
| `/geocode/reverse` | GET | Nominatim reverse geocoding proxy |

Set `prefer_bus` to `true` on `/route/plan` to plan a walking + bus trip using the
bundled Macau route stop sequences. The response includes every feasible direct
bus route and the fastest transfer itinerary in an `options` array; `geojson`
remains the fastest option for clients that only use one itinerary. Each option
contains separate GeoJSON features (`properties.mode` is `bus` or `walk`), and
bus legs include the route number. The Flutter map draws bus legs in orange and
walking legs in blue, and lets users select an alternative. Routes whose names
end in `S` are excluded. N-prefix night bus routes are only considered from
00:00 through 05:59 Macau time; this restriction is not shown in the bus UI.
The map also shows each walking instruction and bus boarding/alighting stop, and
the app-bar control can collapse the route settings to make more room for the map.

The bundled transit data was prepared from the supplied DSAT route/stop files.
Stop coordinates are matched from OpenStreetMap bus-stop/platform features.
Thirteen stop codes currently have no coordinate match and are skipped as
intermediate boarding points. Transit times are estimates and do not use live
arrival schedules or vehicle positions. Map data attribution: © OpenStreetMap
contributors.

### Personalized place tours

The app's upper section lets users set a starting point, available total time,
requested place count, and one or more purposes (culture, food, architecture,
history). The lower section shows the resulting walking route on the map. The
planner chooses nearby places with the strongest combined purpose match while
keeping estimated travel plus visit time within the selected budget.

Each place displays a separate 0–100 match score for all four purposes. These
are transparent relevance scores derived from OpenStreetMap tags such as
`tourism`, `amenity`, `historic`, `heritage`, and `cuisine`; they are not
crowd-sourced ratings or claims of quality. A zero means the bundled source has
no matching tag. The cultural source is the supplied HOTOSM GeoPackage
(OpenStreetMap snapshot 2026-08-07); restaurant, cafe, and food-court records
were queried from the public Nominatim API on 2026-09-29. Opening-hours fields
are shown when present but are not guaranteed to be current or checked against
the travel time. Visit lengths and walking times are estimates, and the planner
does not use live traffic, business schedules, reviews, or opening status.

The exported places and derived attributes are distributed under ODbL 1.0.
Attribution: © OpenStreetMap contributors; cultural layer exported by HOTOSM.
Coverage is limited to the supplied Macao bounding box and depends on public
map data completeness.
The time budget includes estimated walking between selected stops and estimated
visit time at each stop; the itinerary ends at the last selected place and does
not include a return trip to the start.

`POST /tour/plan` accepts `start_lat`, `start_lon`, `duration_minutes` (30–720),
`place_count` (1–10), and a non-empty list of `purposes` (`culture`, `food`,
`architecture`, `history`). The response includes the ordered places with all
four scores, estimated travel/visit time, and a GeoJSON walking leg for each
stop.

The current deterministic score rules use the strongest matching OpenStreetMap
tag per category: culture recognizes museums (96), galleries (90), arts centres
(94), theatres (86), attractions (82), artwork (78), and worship places (75);
food recognizes restaurants (94), cafes (82), food courts (78), and fast food
(62), with up to 6 additional points when cuisine is tagged; architecture
recognizes historic buildings, forts, ruins, and gates (96), heritage entries
(90), monuments and memorials (84), and worship places (72); history recognizes
heritage entries (100) and historic ruins/forts/monuments (94–100), memorials
(90), and historic buildings (78). These are hand-defined tag-match weights,
not review sentiment or an AI-generated assessment.

### Route Plan Request
```json
{
  "start_lat": 22.192,
  "start_lon": 113.539,
  "end_lat": 22.188,
  "end_lon": 113.535,
  "avoid_stairs": true,
  "max_slope": 15,
  "max_walk_km": 2.0,
  "prefer_bus": false,
  "wheelchair": false
}
```

### Intent Parsing Request
```json
{
  "text": "我想看地質但不想爬坡"
}
```

Response:
```json
{
  "tags": ["geology"],
  "avoid_stairs": true,
  "max_slope": 10,
  "max_walk_km": null,
  "prefer_bus": false,
  "wheelchair": false,
  "poi_category": "geology"
}
```

## Running the Backend

```bash
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. The supported entry
points are `uvicorn main:app` from the repository root and
`uvicorn backend.main:app` from the repository root.

If `data/macau_network.graphml` is unavailable, the backend automatically uses
a small offline fallback graph so that the API and frontend can still be
developed and tested. Generate the real Macau graph with:

```bash
python map_downloader.py
```

## Running the Frontend

```bash
cd frontend
flutter pub get
flutter run
```

Desktop builds default to `http://localhost:8000`; Android defaults to
`http://10.0.2.2:8000` for the Android emulator. The app's **後端伺服器網址**
field can be changed at runtime. For an Android phone on the same Wi-Fi, enter
the computer's LAN address (for example, `http://192.168.1.10:8000`), start the
backend with `--host 0.0.0.0`, and allow port 8000 through the computer firewall.

## Release downloads

Push a version tag such as `v1.4.0` to build Windows x64, Linux x64, Intel
macOS (x86_64), Android ARM, and Android x86_64 APK packages in GitHub Actions.
The workflow publishes all five files as assets on a GitHub Release. The app
requires the FastAPI backend to be running; the release contains the Flutter
clients, not a hosted backend.

## Key Features Implemented

### Phase 1: Data & Graph Foundation ✓
- OSMnx downloads Macau road network (30k+ nodes, 87k+ edges)
- Synthetic DEM elevation data with slope calculation
- Synthetic bus routes (10 stops, 5 routes)
- Multi-modal graph with transfer penalties

### Phase 2: Core Routing API ✓
- A* algorithm with customizable cost functions
- Stairs avoidance (slope > 20% or highway=steps)
- Max slope constraint
- Wheelchair accessible mode (max 8% slope)
- Bus preference with transfer penalty
- GeoJSON output with walk/bus segments

### Phase 3: LLM Intent Parsing ✓
- Keyword-based parsing (Qwen3 Function Calling compatible)
- Supports: avoid stairs, wheelchair, bus preference, max walk distance, slope limits
- POI category detection (geology, history, food, shopping, nature)

### Phase 4: Dynamic Re-routing & Flutter UI ✓
- `/route/update` endpoint for GPS deviation & weather alerts
- Flutter map with `flutter_map` & OpenStreetMap tiles
- Chat interface with suggestion chips
- Real-time route display with markers

## Testing

```bash
python -m pytest backend
```

## Configuration

- Macau bounding box: (22.25, 22.05, 113.65, 113.45)
- Default walking speed: 5 km/h
- Default bus speed: 25 km/h
- Transfer penalty: 300 seconds
- Graph cached in `data/cache/`

## Extending

### Add Real DEM Data
Place GeoTIFF in `data/dem.tif` and update `load_dem_data()` in `graph_builder.py`

### Add Real Bus Data
Replace `_generate_synthetic_bus_data()` with GTFS parser

### Integrate Qwen3 API
Replace `parse_user_intent()` in `main.py` with actual Qwen3 Function Calling

### Add Weather/Crowd Data
Implement scheduled fetcher in `main.py` startup and integrate with `/route/update`