import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

void main() => runApp(const MacauNavigationApp());

class MacauNavigationApp extends StatelessWidget {
  const MacauNavigationApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Smart Navigation',
        theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
        home: const NavigationPage(),
      );
}

class NavigationPage extends StatefulWidget {
  const NavigationPage({super.key});
  @override
  State<NavigationPage> createState() => _NavigationPageState();
}

class _NavigationPageState extends State<NavigationPage> {
  final startLat = TextEditingController(text: '22.192');
  final startLon = TextEditingController(text: '113.539');
  final endLat = TextEditingController(text: '22.188');
  final endLon = TextEditingController(text: '113.535');
  final apiBaseUrl = TextEditingController(
    text: defaultTargetPlatform == TargetPlatform.android
        ? 'http://10.0.2.2:8000'
        : 'http://localhost:8000',
  );
  final routeLines = <Polyline>[];
  final routeInstructions = <Map<String, dynamic>>[];
  final routeOptions = <Map<String, dynamic>>[];
  final recommendedPlaces = <Map<String, dynamic>>[];
  final selectedPurposes = <String>{'culture'};
  int selectedOptionIndex = 0;
  int durationMinutes = 120;
  int requestedPlaceCount = 4;
  LatLng startPosition = const LatLng(22.192, 113.539);
  LatLng endPosition = const LatLng(22.188, 113.535);
  String status = '選擇旅遊目的、時間和地點數後推薦行程';
  bool loading = false;
  bool generatingPath = false;
  bool preferBus = false;
  bool selectingStart = true;
  bool tourMode = true;
  bool plannerVisible = true;

  static const purposes = <String, String>{
    'culture': '文化',
    'food': '美食',
    'architecture': '建築',
    'history': '歷史',
  };
  static const minimumTourThinkingDuration = Duration(seconds: 5);
  static const pathGenerationDisplayDuration = Duration(milliseconds: 700);

  Uri _serverUri(String path) {
    final baseUri = Uri.parse(apiBaseUrl.text.trim());
    if (!baseUri.hasScheme || !baseUri.hasAuthority) {
      throw const FormatException('請輸入有效的後端網址，例如 http://192.168.1.10:8000');
    }
    return baseUri.resolve(path);
  }

  Future<void> _requireRoadNetwork() async {
    final response = await http
        .get(_serverUri('/health'))
        .timeout(const Duration(seconds: 5));
    if (response.statusCode != 200) {
      throw Exception('無法連接路線服務，請先啟動 localhost:8000 的後端。');
    }
    final health = jsonDecode(response.body);
    if (health is! Map<String, dynamic>) {
      throw const FormatException('後端健康檢查回應格式錯誤');
    }
    final nodeCount = health['node_count'];
    if (health['road_network_loaded'] == false ||
        (health['road_network_loaded'] == null &&
            nodeCount is num &&
            nodeCount <= 5)) {
      throw Exception(
        '後端目前只載入測試路網，無法規劃真實道路。請確認 data/macau_network.graphml '
        '存在並重新啟動後端。',
      );
    }
  }

  void _clearPlan() {
    routeLines.clear();
    routeInstructions.clear();
    routeOptions.clear();
    recommendedPlaces.clear();
    generatingPath = false;
  }

  void _selectMapTarget(bool isStart) {
    setState(() {
      selectingStart = isStart;
      status = '請點擊地圖設定${isStart ? '起點' : '終點'}';
    });
  }

  void _selectMapPoint(LatLng position) {
    setState(() {
      if (tourMode || selectingStart) {
        startPosition = position;
        startLat.text = position.latitude.toStringAsFixed(6);
        startLon.text = position.longitude.toStringAsFixed(6);
      } else {
        endPosition = position;
        endLat.text = position.latitude.toStringAsFixed(6);
        endLon.text = position.longitude.toStringAsFixed(6);
      }
      _clearPlan();
      final isStart = tourMode || selectingStart;
      status = '已設定${isStart ? '起點' : '終點'}：'
          '${position.latitude.toStringAsFixed(6)}, '
          '${position.longitude.toStringAsFixed(6)}';
    });
  }

  void _updatePosition({
    required TextEditingController latitude,
    required TextEditingController longitude,
    required bool isStart,
  }) {
    final lat = double.tryParse(latitude.text);
    final lon = double.tryParse(longitude.text);
    if (lat == null || lon == null) return;

    setState(() {
      if (isStart) {
        startPosition = LatLng(lat, lon);
      } else {
        endPosition = LatLng(lat, lon);
      }
      _clearPlan();
    });
  }

  @override
  void dispose() {
    startLat.dispose();
    startLon.dispose();
    endLat.dispose();
    endLon.dispose();
    apiBaseUrl.dispose();
    super.dispose();
  }

  Future<void> plan() async {
    setState(() {
      loading = true;
      status = '規劃中...';
      _clearPlan();
    });
    try {
      await _requireRoadNetwork();
      final response = await http.post(
        _serverUri('/route/plan'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'start_lat': double.parse(startLat.text),
          'start_lon': double.parse(startLon.text),
          'end_lat': double.parse(endLat.text),
          'end_lon': double.parse(endLon.text),
          'prefer_bus': preferBus,
        }),
      );
      final data = jsonDecode(response.body);
      if (response.statusCode != 200) throw Exception(data['detail'] ?? '請求失敗');
      final geojson = Map<String, dynamic>.from(data['geojson'] as Map);
      final options = (data['options'] as List? ?? [geojson])
          .map((option) => Map<String, dynamic>.from(option as Map))
          .toList();
      if (options.isEmpty) {
        throw Exception('後端沒有提供可用路線。');
      }
      for (final option in options) {
        final routeProperties =
            option['properties'] as Map<String, dynamic>? ?? {};
        final distance = routeProperties['total_distance'];
        final features = option['features'];
        final hasDrawableRoute = features is List &&
            features.any((feature) {
              if (feature is! Map<String, dynamic>) return false;
              final geometry = feature['geometry'];
              return geometry is Map<String, dynamic> &&
                  geometry['coordinates'] is List &&
                  (geometry['coordinates'] as List).length > 1;
            });
        if (distance is! num || distance <= 0 || !hasDrawableRoute) {
          throw Exception('後端回傳的路線距離為 0 或路線無效，請確認路網資料是否完整。');
        }
      }
      setState(() {
        routeOptions
          ..clear()
          ..addAll(options);
        selectedOptionIndex = 0;
        _showRouteOption(options.first);
      });
    } catch (error) {
      setState(() => status = '錯誤：$error');
    } finally {
      setState(() => loading = false);
    }
  }

  Future<void> planTour() async {
    if (selectedPurposes.isEmpty) {
      setState(() => status = '請至少選擇一種旅遊目的');
      return;
    }
    final planningStartedAt = DateTime.now();
    setState(() {
      loading = true;
      status = '正在思考並安排景點，請稍候...';
      _clearPlan();
    });
    try {
      await _requireRoadNetwork();
      final response = await http.post(
        _serverUri('/tour/plan'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'start_lat': double.parse(startLat.text),
          'start_lon': double.parse(startLon.text),
          'duration_minutes': durationMinutes,
          'place_count': requestedPlaceCount,
          'purposes': selectedPurposes.toList(),
        }),
      );
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      if (response.statusCode != 200) {
        throw Exception(data['detail'] ?? '行程規劃失敗');
      }
      final summary = data['summary'] as Map<String, dynamic>;
      final places = (data['places'] as List)
          .map((place) => Map<String, dynamic>.from(place as Map))
          .toList();
      final geojson = data['geojson'] as Map<String, dynamic>;
      final features = geojson['features'] as List;
      final thinkingTime = DateTime.now().difference(planningStartedAt);
      if (thinkingTime < minimumTourThinkingDuration) {
        await Future<void>.delayed(minimumTourThinkingDuration - thinkingTime);
      }
      if (!mounted) return;
      setState(() {
        recommendedPlaces.addAll(places);
        loading = false;
        generatingPath = true;
        status = '行程已安排，正在產生地圖路線...';
      });
      await Future<void>.delayed(pathGenerationDisplayDuration);
      if (!mounted) return;
      setState(() {
        routeLines.addAll(_polylines(features));
        routeInstructions.addAll(features.map((feature) =>
            Map<String, dynamic>.from(
                (feature as Map<String, dynamic>)['properties'] as Map)));
        generatingPath = false;
        status = '時間內安排 ${places.length}/$requestedPlaceCount 個地點 · 步行約 '
            '${(summary['travel_minutes'] as num).toInt()} 分鐘 · '
            '參觀約 ${(summary['visit_minutes'] as num).toInt()} 分鐘';
      });
    } catch (error) {
      if (mounted) setState(() => status = '錯誤：$error');
    } finally {
      if (mounted) {
        setState(() {
          loading = false;
          generatingPath = false;
        });
      }
    }
  }

  List<Polyline> _polylines(List features) => features.map((feature) {
        final featureMap = feature as Map<String, dynamic>;
        final coordinates = featureMap['geometry']['coordinates'] as List;
        final mode = featureMap['properties']['mode'];
        return Polyline(
          points: coordinates
              .map((point) => LatLng(
                  (point[1] as num).toDouble(), (point[0] as num).toDouble()))
              .toList(),
          color: mode == 'bus' ? Colors.deepOrange : Colors.blue,
          strokeWidth: 5,
        );
      }).toList();

  void _showRouteOption(Map<String, dynamic> geojson) {
    final properties = geojson['properties'] as Map<String, dynamic>;
    final features = geojson['features'] as List;
    routeLines
      ..clear()
      ..addAll(_polylines(features));
    routeInstructions
      ..clear()
      ..addAll(features.map((feature) => Map<String, dynamic>.from(
          (feature as Map<String, dynamic>)['properties'] as Map)));
    final walkDistance = (properties['walk_distance'] as num).toDouble();
    final busDistance = (properties['bus_distance'] as num).toDouble();
    final routeNames = (properties['routes'] as List? ?? []).join('、');
    status = busDistance > 0
        ? '步行 ${walkDistance.toStringAsFixed(0)} 公尺 · 公車 $routeNames · '
            '${(properties['num_transfers'] as num).toInt()} 次轉乘'
        : '距離 ${(properties['total_distance'] as num).toStringAsFixed(0)} 公尺';
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('智慧旅遊規劃'),
          actions: [
            IconButton(
              tooltip: plannerVisible ? '隱藏行程設定' : '顯示行程設定',
              onPressed: () => setState(() => plannerVisible = !plannerVisible),
              icon: Icon(
                plannerVisible ? Icons.expand_less : Icons.expand_more,
              ),
            ),
          ],
        ),
        body: Column(children: [
          if (plannerVisible) ...[
            Expanded(
              flex: 6,
              child: _plannerPage(),
            ),
            const Divider(height: 1),
          ],
          Expanded(
            flex: plannerVisible ? 7 : 1,
            child: _mapPage(),
          ),
        ]),
      );

  Widget _plannerPage() => SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('行程規劃',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            TextField(
              controller: apiBaseUrl,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: '後端伺服器網址',
                hintText: '例如 http://192.168.1.10:8000',
                isDense: true,
              ),
            ),
            const SizedBox(height: 8),
            SegmentedButton<bool>(
              segments: const [
                ButtonSegment(value: true, label: Text('推薦景點行程')),
                ButtonSegment(value: false, label: Text('起終點導航')),
              ],
              selected: {tourMode},
              onSelectionChanged: (selection) => setState(() {
                tourMode = selection.first;
                _clearPlan();
                status = '請設定起點和行程偏好';
              }),
            ),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                  child: _field(
                      '起點緯度',
                      startLat,
                      () => _updatePosition(
                          latitude: startLat,
                          longitude: startLon,
                          isStart: true))),
              Expanded(
                  child: _field(
                      '起點經度',
                      startLon,
                      () => _updatePosition(
                          latitude: startLat,
                          longitude: startLon,
                          isStart: true))),
              IconButton.filledTonal(
                tooltip: '在地圖選擇起點',
                onPressed: () => _selectMapTarget(true),
                icon: const Icon(Icons.add_location_alt),
              ),
            ]),
            if (tourMode) ...[
              _tourPreferences(),
              const ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text('分數說明與資料來源'),
                children: [
                  Padding(
                    padding: EdgeInsets.only(bottom: 8),
                    child: Text(
                      '分數代表公開地圖標籤與目的的符合程度，不是網路評分或品質排名。'
                      '文化景點資料來自 HOTOSM／OpenStreetMap（2026-08-07 快照）；'
                      '美食地點來自 OpenStreetMap Nominatim（2026-09-29 查詢）。'
                      '每個地點會依文化、餐飲、'
                      '歷史及建築標籤分別計分；沒有相關標籤就顯示 0。'
                      '行程時間包含景點間步行和預估停留，不包含從最後景點返回起點。'
                      '開放時間、參觀時間和步行時間可能不完整或已過時。',
                    ),
                  ),
                ],
              ),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: loading || generatingPath ? null : planTour,
                  icon: const Icon(Icons.auto_awesome),
                  label: Text(
                    loading
                        ? '正在思考，請稍候...'
                        : generatingPath
                            ? '正在產生路線...'
                            : '推薦我的行程',
                  ),
                ),
              ),
            ] else ...[
              Row(children: [
                Expanded(
                    child: _field(
                        '終點緯度',
                        endLat,
                        () => _updatePosition(
                            latitude: endLat,
                            longitude: endLon,
                            isStart: false))),
                Expanded(
                    child: _field(
                        '終點經度',
                        endLon,
                        () => _updatePosition(
                            latitude: endLat,
                            longitude: endLon,
                            isStart: false))),
                IconButton.filledTonal(
                  tooltip: '在地圖選擇終點',
                  onPressed: () => _selectMapTarget(false),
                  icon: const Icon(Icons.add_location_alt),
                ),
              ]),
              SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('優先使用公車'),
                  value: preferBus,
                  onChanged: (value) => setState(() => preferBus = value)),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: loading ? null : plan,
                  child: Text(loading ? '規劃中...' : '規劃起終點路線'),
                ),
              ),
            ],
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  if (loading || generatingPath) ...[
                    const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    const SizedBox(width: 8),
                  ],
                  Expanded(child: Text(status)),
                ],
              ),
            ),
            if (recommendedPlaces.isNotEmpty) ...[
              const Text('推薦地點｜各項分數為公開地圖標籤符合度，並非評價',
                  style: TextStyle(fontWeight: FontWeight.w600)),
              ...recommendedPlaces.map(_placeTile),
            ],
          ],
        ),
      );

  Widget _tourPreferences() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Text('可用總時間'),
            Expanded(
              child: Slider(
                min: 30,
                max: 720,
                divisions: 23,
                value: durationMinutes.toDouble(),
                label: _formatDuration(durationMinutes),
                onChanged: (value) =>
                    setState(() => durationMinutes = (value / 30).round() * 30),
              ),
            ),
            Text(_formatDuration(durationMinutes)),
          ]),
          Row(children: [
            const Text('想去地點數'),
            const SizedBox(width: 16),
            DropdownButton<int>(
              value: requestedPlaceCount,
              items: List.generate(
                  10,
                  (index) => DropdownMenuItem(
                      value: index + 1, child: Text('${index + 1} 個'))),
              onChanged: (value) {
                if (value != null) {
                  setState(() => requestedPlaceCount = value);
                }
              },
            ),
            const SizedBox(width: 18),
            const Text('旅遊目的（可多選）'),
          ]),
          Wrap(
            spacing: 4,
            runSpacing: 0,
            children: purposes.entries
                .map((purpose) => FilterChip(
                      label: Text(purpose.value),
                      selected: selectedPurposes.contains(purpose.key),
                      onSelected: (selected) => setState(() {
                        if (selected) {
                          selectedPurposes.add(purpose.key);
                        } else {
                          selectedPurposes.remove(purpose.key);
                        }
                      }),
                    ))
                .toList(),
          ),
        ],
      );

  Widget _placeTile(Map<String, dynamic> place) {
    final scores = place['scores'] as Map<String, dynamic>;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 3),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${place['sequence']}. ${place['name']}',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          Text('步行 ${place['travel_minutes']} 分鐘 · 停留約 '
              '${place['visit_minutes']} 分鐘 · 符合度 ${place['relevance_score']}'),
          Wrap(
            spacing: 10,
            children: purposes.entries
                .map((purpose) =>
                    Text('${purpose.value} ${scores[purpose.key]}'))
                .toList(),
          ),
          if (place['opening_hours'] != null)
            Text('資料中的開放時間：${place['opening_hours']}'),
          if (place['website'] != null)
            Text('網站：${place['website']}',
                maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
    );
  }

  String _formatDuration(int minutes) => minutes % 60 == 0
      ? '${minutes ~/ 60} 小時'
      : '${minutes ~/ 60} 小時 ${minutes % 60} 分鐘';

  Widget _mapPage() => Stack(
        children: [
          FlutterMap(
            options: MapOptions(
              initialCenter: const LatLng(22.192, 113.539),
              initialZoom: 13,
              onTap: (_, position) => _selectMapPoint(position),
            ),
            children: [
              TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.example.macau_navigation'),
              if (routeLines.isNotEmpty) PolylineLayer(polylines: routeLines),
              MarkerLayer(markers: [
                _pin(startPosition, '起點', Colors.green),
                if (tourMode)
                  ...recommendedPlaces.map((place) => _visitPin(place))
                else
                  _pin(endPosition, '終點', Colors.red),
              ]),
            ],
          ),
          Positioned(
            top: 8,
            left: 8,
            right: 8,
            child: Card(
              child: Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: Text(
                  '地圖與路線　點擊地圖設定${tourMode || selectingStart ? '起點' : '終點'}',
                ),
              ),
            ),
          ),
          if (routeOptions.length > 1)
            Positioned(
              top: 52,
              left: 8,
              right: 8,
              child: SizedBox(
                height: 48,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  children: List.generate(routeOptions.length, (index) {
                    final properties = routeOptions[index]['properties']
                        as Map<String, dynamic>;
                    final label = properties['option_label'] as String? ??
                        '方案 ${index + 1}';
                    final minutes =
                        ((properties['total_time'] as num).toDouble() / 60)
                            .ceil();
                    return Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ChoiceChip(
                        label: Text('$label · 約 $minutes 分'),
                        selected: selectedOptionIndex == index,
                        onSelected: (_) => setState(() {
                          selectedOptionIndex = index;
                          _showRouteOption(routeOptions[index]);
                        }),
                      ),
                    );
                  }),
                ),
              ),
            ),
          if (!tourMode && routeInstructions.isNotEmpty)
            Positioned(
              bottom: 8,
              left: 8,
              right: 8,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 150),
                child: Card(
                  child: ListView.separated(
                    shrinkWrap: true,
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    itemCount: routeInstructions.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) =>
                        _instructionTile(routeInstructions[index]),
                  ),
                ),
              ),
            ),
        ],
      );

  Marker _visitPin(Map<String, dynamic> place) {
    final number = place['sequence'] as int;
    final color = Colors.primaries[(number - 1) % Colors.primaries.length];
    return Marker(
      point: LatLng(
          (place['lat'] as num).toDouble(), (place['lon'] as num).toDouble()),
      width: 80,
      height: 68,
      alignment: Alignment.topCenter,
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
          decoration: BoxDecoration(
              color: Colors.white, borderRadius: BorderRadius.circular(4)),
          child: Text('$number. ${place['name']}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: color, fontWeight: FontWeight.bold)),
        ),
        Icon(Icons.location_on, color: color, size: 40),
      ]),
    );
  }

  Widget _instructionTile(Map<String, dynamic> instruction) {
    final distance = (instruction['distance'] as num?)?.toDouble() ?? 0;
    final isBus = instruction['mode'] == 'bus';
    final boarding = instruction['boarding_stop'] as Map<String, dynamic>?;
    final alighting = instruction['alighting_stop'] as Map<String, dynamic>?;

    return ListTile(
      dense: true,
      leading: Icon(
        isBus ? Icons.directions_bus : Icons.directions_walk,
        color: isBus ? Colors.deepOrange : Colors.blue,
      ),
      title: Text(
        isBus
            ? '搭乘 ${instruction['route_name']} 號巴士'
            : '步行 ${_formatDistance(distance)}',
      ),
      subtitle: Text(
        isBus
            ? '${boarding?['name'] ?? boarding?['code'] ?? ''} → '
                '${alighting?['name'] ?? alighting?['code'] ?? ''}'
            : instruction['instruction'] as String? ?? '步行路段',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: isBus ? const Icon(Icons.arrow_forward_ios, size: 14) : null,
    );
  }

  String _formatDistance(double distance) => distance >= 1000
      ? '${(distance / 1000).toStringAsFixed(1)} 公里'
      : '${distance.toStringAsFixed(0)} 公尺';

  Marker _pin(LatLng position, String label, Color color) => Marker(
        point: position,
        width: 76,
        height: 70,
        alignment: Alignment.topCenter,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
              decoration: BoxDecoration(
                  color: Colors.white, borderRadius: BorderRadius.circular(4)),
              child: Text(label,
                  style: TextStyle(color: color, fontWeight: FontWeight.bold)),
            ),
            Icon(Icons.location_on, color: color, size: 40),
          ],
        ),
      );

  Widget _field(String label, TextEditingController controller,
          VoidCallback onChanged) =>
      Padding(
        padding: const EdgeInsets.all(4),
        child: TextField(
          controller: controller,
          onChanged: (_) => onChanged(),
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(
              labelText: label, border: const OutlineInputBorder()),
        ),
      );
}
