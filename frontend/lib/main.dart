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
        title: 'Macau Navigation',
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
  final chat = TextEditingController();
  final routeLines = <Polyline>[];
  final routeInstructions = <Map<String, dynamic>>[];
  final routeOptions = <Map<String, dynamic>>[];
  int selectedOptionIndex = 0;
  LatLng startPosition = const LatLng(22.192, 113.539);
  LatLng endPosition = const LatLng(22.188, 113.535);
  String status = '輸入起點與終點後規劃路線';
  bool loading = false;
  bool preferBus = false;
  bool selectingStart = true;
  bool showControls = true;

  void _selectMapTarget(bool isStart) {
    setState(() {
      selectingStart = isStart;
      status = '請點擊地圖設定${isStart ? '起點' : '終點'}';
    });
  }

  void _selectMapPoint(LatLng position) {
    setState(() {
      if (selectingStart) {
        startPosition = position;
        startLat.text = position.latitude.toStringAsFixed(6);
        startLon.text = position.longitude.toStringAsFixed(6);
      } else {
        endPosition = position;
        endLat.text = position.latitude.toStringAsFixed(6);
        endLon.text = position.longitude.toStringAsFixed(6);
      }
      routeLines.clear();
      routeInstructions.clear();
      routeOptions.clear();
      status = '已設定${selectingStart ? '起點' : '終點'}：'
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
      routeLines.clear();
      routeInstructions.clear();
      routeOptions.clear();
    });
  }

  @override
  void dispose() {
    startLat.dispose();
    startLon.dispose();
    endLat.dispose();
    endLon.dispose();
    apiBaseUrl.dispose();
    chat.dispose();
    super.dispose();
  }

  Future<void> plan() async {
    setState(() {
      loading = true;
      status = '規劃中...';
      routeLines.clear();
      routeInstructions.clear();
      routeOptions.clear();
    });
    try {
      final baseUri = Uri.parse(apiBaseUrl.text.trim());
      if (!baseUri.hasScheme || !baseUri.hasAuthority) {
        throw const FormatException('請輸入有效的後端網址，例如 http://192.168.1.10:8000');
      }
      final response = await http.post(
        baseUri.resolve('/route/plan'),
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

  void _showRouteOption(Map<String, dynamic> geojson) {
    final properties = geojson['properties'] as Map<String, dynamic>;
    final features = geojson['features'] as List;
    routeLines
      ..clear()
      ..addAll(features.map((feature) {
        final featureMap = feature as Map<String, dynamic>;
        final coordinates = featureMap['geometry']['coordinates'] as List;
        final mode = featureMap['properties']['mode'];
        return Polyline(
          points: coordinates
              .map((point) => LatLng((point[1] as num).toDouble(),
                  (point[0] as num).toDouble()))
              .toList(),
          color: mode == 'bus' ? Colors.deepOrange : Colors.blue,
          strokeWidth: 5,
        );
      }));
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
          title: const Text('澳門智慧導航'),
          actions: [
            IconButton(
              tooltip: showControls ? '隱藏設定' : '顯示設定',
              onPressed: () => setState(() => showControls = !showControls),
              icon: Icon(showControls ? Icons.expand_less : Icons.tune),
            ),
          ],
        ),
        body: Column(children: [
          AnimatedSize(
              duration: const Duration(milliseconds: 200),
              child: showControls
                  ? Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(children: [
                        TextField(
                          controller: apiBaseUrl,
                          keyboardType: TextInputType.url,
                          decoration: const InputDecoration(
                            labelText: '後端伺服器網址',
                            hintText: '例如 http://192.168.1.10:8000',
                            border: OutlineInputBorder(),
                          ),
                        ),
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
                            isSelected: selectingStart,
                            onPressed: () => _selectMapTarget(true),
                            icon: const Icon(Icons.add_location_alt),
                          ),
                        ]),
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
                            isSelected: !selectingStart,
                            onPressed: () => _selectMapTarget(false),
                            icon: const Icon(Icons.add_location_alt),
                          ),
                        ]),
                        SwitchListTile(
                            title: const Text('優先使用公車'),
                            value: preferBus,
                            onChanged: (value) =>
                                setState(() => preferBus = value)),
                        SizedBox(
                            width: double.infinity,
                            child: FilledButton(
                                onPressed: loading ? null : plan,
                                child: Text(loading ? '規劃中...' : '規劃路線'))),
                        Text(status),
                      ]))
                  : const SizedBox.shrink()),
          Expanded(
            child: Stack(
              children: [
                FlutterMap(
                  options: MapOptions(
                    initialCenter: const LatLng(22.192, 113.539),
                    initialZoom: 13,
                    onTap: (_, position) => _selectMapPoint(position),
                  ),
                  children: [
                    TileLayer(
                        urlTemplate:
                            'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                        userAgentPackageName: 'com.example.macau_navigation'),
                    if (routeLines.isNotEmpty)
                      PolylineLayer(polylines: routeLines),
                    MarkerLayer(markers: [
                      _pin(startPosition, '起點', Colors.green),
                      _pin(endPosition, '終點', Colors.red),
                    ]),
                  ],
                ),
                Positioned(
                  top: 12,
                  left: 12,
                  right: 12,
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 8),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text('點擊地圖設定${selectingStart ? '起點' : '終點'}'),
                          if (routeOptions.length > 1)
                            SingleChildScrollView(
                              scrollDirection: Axis.horizontal,
                              child: Row(
                                children: List.generate(routeOptions.length,
                                    (index) {
                                  final properties = routeOptions[index]
                                      ['properties'] as Map<String, dynamic>;
                                  final label = properties['option_label']
                                      as String? ?? '方案 ${index + 1}';
                                  final minutes =
                                      ((properties['total_time'] as num)
                                                  .toDouble() /
                                              60)
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
                        ],
                      ),
                    ),
                  ),
                ),
                if (routeInstructions.isNotEmpty)
                  Positioned(
                    bottom: 8,
                    left: 8,
                    right: 8,
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 180),
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
            ),
          ),
          Padding(
              padding: const EdgeInsets.all(8),
              child: Row(children: [
                Expanded(
                    child: TextField(
                        controller: chat,
                        decoration: const InputDecoration(
                            hintText: '例如：我想坐公車，最多步行2公里'))),
                IconButton(
                    icon: const Icon(Icons.send),
                    onPressed: () {
                      if (chat.text.isNotEmpty) {
                        setState(() => status = '偏好已收到：${chat.text}');
                      }
                    }),
              ])),
        ]),
      );

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
