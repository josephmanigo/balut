import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'models.dart';

class ApiFailure implements Exception {
  const ApiFailure(this.message, [this.status = 0]);
  final String message;
  final int status;
  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({http.Client? httpClient, FlutterSecureStorage? storage})
    : _http = httpClient ?? http.Client(),
      _storage = storage ?? const FlutterSecureStorage();
  final http.Client _http;
  final FlutterSecureStorage _storage;
  Uri base = Uri.parse(
    const String.fromEnvironment(
      'BALUT_SERVER',
      defaultValue: 'http://127.0.0.1:8765',
    ),
  );
  String? _cookie;

  static Uri parseServer(String address) {
    final uri = Uri.tryParse(address.trim());
    final loopback =
        uri != null && const ['127.0.0.1', 'localhost'].contains(uri.host);
    if (uri == null ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        !const ['', '/'].contains(uri.path) ||
        (uri.scheme != 'https' && !(uri.scheme == 'http' && loopback))) {
      throw const ApiFailure(
        'Use an HTTPS server address, or localhost for USB testing.',
      );
    }
    return uri.replace(path: '');
  }

  Future<void> restore() async {
    base = parseServer(
      await _storage.read(key: 'workspace_server') ?? base.toString(),
    );
    _cookie = await _storage.read(key: 'workspace_session');
  }

  Future<void> changeServer(String address) async {
    final next = parseServer(address);
    await _storage.delete(key: 'workspace_session');
    _cookie = null;
    await _storage.write(key: 'workspace_server', value: next.toString());
    base = next;
  }

  Future<Map<String, dynamic>> _request(
    String path, {
    Object? body,
    String? key,
  }) async {
    final request = http.Request(
      body == null ? 'GET' : 'POST',
      base.resolve('/api/v1/$path'),
    );
    // Never forward a session to a redirect target or a different server.
    request.followRedirects = false;
    request.headers.addAll({
      'X-Balut-Origin': 'local',
      if (_cookie != null) 'Cookie': _cookie!,
    });
    if (body is Uint8List) {
      request.headers.addAll({
        'Content-Type': 'image/jpeg',
        'Idempotency-Key': key!,
      });
      request.bodyBytes = body;
    } else if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    late http.Response response;
    try {
      response =
          await (() async => http.Response.fromStream(
            await _http.send(request),
          ))().timeout(
            Duration(
              seconds: body is Uint8List || path.startsWith('box/')
                  ? 45
                  : 12,
            ),
          );
    } on TimeoutException {
      throw const ApiFailure(
        'Connection interrupted. Try again with the same image.',
      );
    } on http.ClientException {
      throw const ApiFailure(
        'Cannot connect. Check your server and try again.',
      );
    }
    if (response.statusCode == 401) {
      _cookie = null;
      await _storage.delete(key: 'workspace_session');
      throw ApiFailure(
        path == 'auth/login'
            ? 'Username or password is incorrect.'
            : 'Session ended. Sign in again.',
        401,
      );
    }
    if (response.statusCode >= 300) {
      var message = switch (response.statusCode) {
        413 => 'Choose a JPEG under 10 MB.',
        429 => 'The service is busy. Wait a moment and retry.',
        422 =>
          body is Uint8List
              ? 'Choose a valid JPEG, 32 pixels or larger and at most 16 megapixels.'
              : 'Check your details. Passwords need 12–128 characters.',
        _ => 'Request failed. Check your connection and retry.',
      };
      if (const [400, 409].contains(response.statusCode)) {
        try {
          final detail = (jsonDecode(response.body) as Map)['detail'];
          if (detail is String) message = detail;
        } on Object {
          /* Keep the fallback for non-JSON errors. */
        }
      }
      throw ApiFailure(message, response.statusCode);
    }
    final setCookie = response.headers['set-cookie'];
    if (setCookie != null && path != 'auth/logout') {
      final match = RegExp(
        r'(?:^|,\s*)balut_session=([A-Za-z0-9_-]+)(?:;|$)',
      ).firstMatch(setCookie);
      if (match != null) {
        _cookie = 'balut_session=${match.group(1)}';
        await _storage.write(key: 'workspace_session', value: _cookie);
      }
    }
    try {
      return jsonDecode(response.body) as Map<String, dynamic>;
    } on Object {
      throw const ApiFailure(
        'The server returned an unreadable response. Retry.',
      );
    }
  }

  Future<AuthSession> session() async =>
      AuthSession.fromJson(await _request('auth/session'));
  Future<void> login(
    String username,
    String password, {
    String? confirmation,
  }) async {
    final response = await _request(
      confirmation == null ? 'auth/login' : 'auth/register',
      body: {
        'username': username.trim(),
        'password': password,
        if (confirmation != null) 'confirmPassword': confirmation,
      },
    );
    if (response['authenticated'] != true || _cookie == null) {
      throw const ApiFailure('Sign-in could not be confirmed. Try again.');
    }
  }

  Future<void> logout() async {
    await _request('auth/logout', body: <String, Object>{});
    _cookie = null;
    await _storage.delete(key: 'workspace_session');
  }

  Future<bool> modelReady() async =>
      (await _request('models'))['analysisModelId'] != null;
  Future<List<Prediction>> history() async =>
      ((await _request('model-predictions?limit=50'))['items'] as List)
          .map((item) => Prediction.fromJson(item as Map<String, dynamic>))
          .toList();
  Future<Prediction> analyze(Uint8List bytes, String key) async =>
      Prediction.fromJson(
        await _request('egg-analysis', body: bytes, key: key),
      );
  Future<BoxStatus> boxStatus() async =>
      BoxStatus.fromJson(await _request('box/status'));
  Future<BoxStatus> boxAction(String action, Map<String, Object> body) async =>
      BoxStatus.fromJson(await _request('box/$action', body: body));
  static String newRequestKey() {
    final random = Random.secure();
    return List.generate(
      24,
      (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'),
    ).join();
  }

  void close() => _http.close();
}
