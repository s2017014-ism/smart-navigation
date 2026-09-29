import 'package:flutter_test/flutter_test.dart';

import 'package:macau_navigation/main.dart';

void main() {
  testWidgets('map location selection controls are shown', (tester) async {
    await tester.pumpWidget(const MacauNavigationApp());

    expect(find.byTooltip('在地圖選擇起點'), findsOneWidget);
    expect(find.byTooltip('在地圖選擇終點'), findsOneWidget);
    expect(find.byTooltip('隱藏設定'), findsOneWidget);
    expect(find.text('N 字頭夜間線只在 00:00–06:00 營運'), findsNothing);
    expect(find.text('後端伺服器網址'), findsOneWidget);
    expect(find.text('點擊地圖設定起點'), findsOneWidget);

    await tester.tap(find.byTooltip('在地圖選擇終點'));
    await tester.pump();

    expect(find.text('點擊地圖設定終點'), findsOneWidget);

    await tester.tap(find.byTooltip('隱藏設定'));
    await tester.pumpAndSettle();

    expect(find.byTooltip('顯示設定'), findsOneWidget);
    expect(find.byTooltip('在地圖選擇起點'), findsNothing);

    await tester.tap(find.byTooltip('顯示設定'));
    await tester.pumpAndSettle();

    expect(find.byTooltip('在地圖選擇起點'), findsOneWidget);
  });
}
