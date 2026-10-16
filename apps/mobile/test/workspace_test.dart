import 'dart:convert';
import 'package:balut_operator/api_client.dart';
import 'package:balut_operator/main.dart';
import 'package:balut_operator/models.dart';
import 'package:balut_operator/theme.dart';
import 'package:balut_operator/workspace.dart';
import 'package:balut_operator/automatic_box.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'models_test.dart' show predictionJson;

class TestApi extends ApiClient {
  TestApi({
    this.setup = true,
    this.signedIn = false,
    this.failHistory = false,
    this.expiredLogout = false,
  });
  bool setup, signedIn, failHistory, expiredLogout;
  int registrations = 0;
  BoxStatus box = const BoxStatus();
  int analyses = 0;
  @override
  Future<BoxStatus> boxStatus() async => box;
  @override
  Future<BoxStatus> boxAction(String action, Map<String, Object> body) async {
    box = action == 'connect'
        ? const BoxStatus(
            cameraUrl: 'http://192.168.1.50',
            connected: true,
            state: 'needs_reference',
          )
        : const BoxStatus(
            cameraUrl: 'http://192.168.1.50',
            connected: true,
            calibrated: true,
            enabled: true,
            state: 'waiting',
          );
    return box;
  }

  @override
  Future<void> restore() async {}
  @override
  Future<AuthSession> session() async =>
      AuthSession(authenticated: signedIn, setupRequired: setup);
  @override
  Future<void> login(
    String username,
    String password, {
    String? confirmation,
  }) async {
    registrations++;
    signedIn = true;
    setup = false;
  }

  @override
  Future<bool> modelReady() async => true;
  @override
  Future<void> logout() async {
    if (expiredLogout) throw const ApiFailure('Session ended.', 401);
    signedIn = false;
  }

  @override
  Future<List<Prediction>> history() async {
    if (failHistory) throw const ApiFailure('Offline');
    return [
      Prediction.fromJson(predictionJson()),
      Prediction.fromJson(predictionJson(recapture: true)),
    ];
  }
}

void main() {
  testWidgets('signing out of an expired session returns to sign in', (
    tester,
  ) async {
    await tester.pumpWidget(
      BalutOperatorApp(
        api: TestApi(setup: false, signedIn: true, expiredLogout: true),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byType(PopupMenuButton<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle();
    expect(find.text('Welcome back.'), findsOneWidget);
  });
  testWidgets(
    'create account validates confirmation then opens Analyze and shared History',
    (tester) async {
      tester.view.physicalSize = const Size(780, 1688);
      tester.view.devicePixelRatio = 2;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final api = TestApi();
      await tester.pumpWidget(BalutOperatorApp(api: api));
      await tester.pumpAndSettle();
      expect(find.text('Create your account.'), findsOneWidget);
      await tester.enterText(find.byType(TextFormField).at(0), 'owner');
      await tester.enterText(
        find.byType(TextFormField).at(1),
        'a chosen password',
      );
      await tester.enterText(
        find.byType(TextFormField).at(2),
        'different password',
      );
      await tester.ensureVisible(find.text('Create account'));
      await tester.tap(find.text('Create account'));
      await tester.pumpAndSettle();
      expect(find.text('Passwords do not match.'), findsOneWidget);
      expect(api.registrations, 0);
      await tester.enterText(
        find.byType(TextFormField).at(2),
        'a chosen password',
      );
      await tester.ensureVisible(find.text('Create account'));
      await tester.tap(find.text('Create account'));
      await tester.pumpAndSettle();
      expect(find.text('Connect your box.'), findsOneWidget);
      expect(find.text('Attach photo'), findsNothing);
      expect(find.text('Choose candling JPEG'), findsNothing);
      expect(api.registrations, 1);
      await tester.tap(find.text('History'));
      await tester.pumpAndSettle();
      expect(find.text('Day 16'), findsOneWidget);
      expect(find.text('Another image needed'), findsOneWidget);
      await tester.tap(find.byType(PopupMenuButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sign out'));
      await tester.pumpAndSettle();
      expect(find.text('Welcome back.'), findsOneWidget);
      expect(find.text('Create account'), findsNothing);
      expect(tester.takeException(), null);
    },
  );
  testWidgets('history failure is explicit and refresh recovers', (
    tester,
  ) async {
    final api = TestApi(setup: false, signedIn: true, failHistory: true);
    await tester.pumpWidget(BalutOperatorApp(api: api));
    await tester.pumpAndSettle();
    await tester.tap(find.text('History'));
    await tester.pumpAndSettle();
    expect(find.text('Records could not load. Try Refresh.'), findsOneWidget);
    api.failHistory = false;
    await tester.tap(find.text('Refresh'));
    await tester.pumpAndSettle();
    expect(find.text('Day 16'), findsOneWidget);
    expect(tester.takeException(), null);
  });
  for (final size in [
    const Size(320, 700),
    const Size(700, 320),
    const Size(1100, 800),
    const Size(1000, 420),
  ]) {
    testWidgets('account and workspace fit ${size.width} at 130% text', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          theme: balutTheme(Brightness.dark),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: const TextScaler.linear(1.3)),
            child: child!,
          ),
          home: AccountPage(
            api: TestApi(),
            setupRequired: true,
            filipino: false,
            onLanguage: () {},
            onServer: () {},
            onSignedIn: () {},
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), null);
      await tester.pumpWidget(
        MaterialApp(
          theme: balutTheme(Brightness.dark),
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: const TextScaler.linear(1.3)),
            child: child!,
          ),
          home: Workspace(
            api: TestApi(),
            filipino: false,
            onLanguage: () {},
            onSignedOut: () {},
            onExpired: () {},
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), null);
      expect(find.text('Attach photo'), findsNothing);
      expect(find.byType(AutomaticBoxPage), findsOneWidget);
    });
  }
  testWidgets('automatic mode receives a result without attaching a photo', (
    tester,
  ) async {
    final api = TestApi();
    api.box = const BoxStatus(
      cameraUrl: 'http://192.168.1.50',
      enabled: true,
      calibrated: true,
      connected: true,
      state: 'waiting',
    );
    var saved = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: balutTheme(Brightness.light),
        home: Scaffold(
          body: AutomaticBoxPage(
            api: api,
            filipino: false,
            onExpired: () {},
            onSaved: () => saved++,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Ready for an egg.'), findsOneWidget);
    api.box = BoxStatus(
      cameraUrl: 'http://192.168.1.50',
      enabled: true,
      calibrated: true,
      connected: true,
      state: 'remove_egg',
      result: Prediction.fromJson(predictionJson()),
    );
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(find.text('Day 16'), findsOneWidget);
    expect(find.text('Analyze next egg'), findsNothing);
    expect(saved, 1);
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(saved, 1);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('paused analysis still receives changing live camera frames', (
    tester,
  ) async {
    final api = TestApi();
    const first =
        'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAC0lEQVR4nGNgQAYAAA4AAamRc7EAAAAASUVORK5CYII=';
    const next =
        'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg==';
    api.box = const BoxStatus(
      connected: true,
      calibrated: true,
      state: 'paused',
      preview: first,
    );
    var saved = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AutomaticBoxPage(
            api: api,
            filipino: false,
            onExpired: () {},
            onSaved: () => saved++,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      (tester.widget<Image>(find.byType(Image)).image as MemoryImage).bytes,
      base64Decode(first),
    );
    api.box = const BoxStatus(
      connected: true,
      calibrated: true,
      state: 'paused',
      preview: next,
    );
    await tester.pump(const Duration(milliseconds: 250));
    await tester.pumpAndSettle();
    expect(
      (tester.widget<Image>(find.byType(Image)).image as MemoryImage).bytes,
      base64Decode(next),
    );
    expect(find.text('Automatic mode paused.'), findsOneWidget);
    expect(saved, 0);
    await tester.pumpWidget(const SizedBox());
  });
}
