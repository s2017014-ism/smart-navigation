import 'package:flutter_test/flutter_test.dart';

import 'package:macau_navigation/main.dart';

void main() {
  testWidgets('planner and map are split into stacked sections',
      (tester) async {
    await tester.pumpWidget(const MacauNavigationApp());

    expect(find.byTooltip('在地圖選擇起點'), findsOneWidget);
    expect(find.text('後端伺服器網址'), findsOneWidget);
    expect(find.text('推薦我的行程'), findsOneWidget);
    expect(find.text('文化'), findsOneWidget);
    expect(find.text('美食'), findsOneWidget);
    expect(find.text('建築'), findsOneWidget);
    expect(find.text('歷史'), findsOneWidget);
    expect(find.textContaining('上方｜行程規劃'), findsOneWidget);
    expect(find.textContaining('下方｜地圖與路線'), findsOneWidget);

    await tester.tap(find.text('起終點導航'));
    await tester.pumpAndSettle();

    expect(find.byTooltip('在地圖選擇終點'), findsOneWidget);
    expect(find.text('優先使用公車'), findsOneWidget);

    await tester.tap(find.text('推薦景點行程'));
    await tester.pumpAndSettle();

    expect(find.byTooltip('在地圖選擇起點'), findsOneWidget);
    expect(find.text('推薦我的行程'), findsOneWidget);
  });
}
