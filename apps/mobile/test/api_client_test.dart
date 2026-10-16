import 'dart:io';
import 'dart:convert';
import 'package:balut_operator/api_client.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'models_test.dart' show predictionJson;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));
  test('bundled box certificate loads into a validating TLS context', () async {
    final data = await rootBundle.load(
      'assets/certificates/balut-local-box.pem',
    );
    final context = SecurityContext(withTrustedRoots: false);
    expect(
      () => context.setTrustedCertificatesBytes(
        data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
      ),
      returnsNormally,
    );
  });
  test('HTTP success without an authenticated session is rejected', () async {
    final api = ApiClient(
      httpClient: MockClient(
        (request) async => http.Response('{"authenticated":false}', 200),
      ),
    );
    await expectLater(
      api.login('owner', 'a chosen password'),
      throwsA(isA<ApiFailure>()),
    );
  });
  test(
    'registration stores session only, authenticated calls use it, logout revokes it',
    () async {
      final calls = <http.Request>[];
      final api = ApiClient(
        httpClient: MockClient((request) async {
          calls.add(request);
          if (request.url.path.endsWith('/register')) {
            expect(jsonDecode(request.body), {
              'username': 'owner',
              'password': 'a chosen password',
              'confirmPassword': 'a chosen password',
            });
            return http.Response(
              '{"authenticated":true}',
              201,
              headers: {
                'set-cookie':
                    'balut_session=session-token; HttpOnly; SameSite=Strict; Path=/',
              },
            );
          }
          if (request.url.path.endsWith('/logout')) {
            return http.Response('{"authenticated":false}', 200);
          }
          return http.Response(
            '{"authenticated":true,"setupRequired":false}',
            200,
          );
        }),
      );
      await api.restore();
      await api.login(
        ' owner ',
        'a chosen password',
        confirmation: 'a chosen password',
      );
      await api.session();
      expect(calls.last.headers['cookie'], 'balut_session=session-token');
      expect(calls.first.headers['x-balut-origin'], 'local');
      expect(calls.every((request) => !request.followRedirects), true);
      final storage = await const FlutterSecureStorage().readAll();
      expect(
        storage.values.any((value) => value.contains('a chosen password')),
        false,
      );
      await api.logout();
      expect(
        await const FlutterSecureStorage().read(key: 'workspace_session'),
        null,
      );
    },
  );
  test(
    '401 clears stored session; changing host never sends old credentials',
    () async {
      FlutterSecureStorage.setMockInitialValues({
        'workspace_session': 'balut_session=old',
      });
      final api = ApiClient(
        httpClient: MockClient((request) async {
          if (request.url.host == '127.0.0.1') return http.Response('{}', 401);
          expect(request.headers.containsKey('cookie'), false);
          return http.Response(
            '{"authenticated":false,"setupRequired":false}',
            200,
          );
        }),
      );
      await api.restore();
      await expectLater(
        api.history(),
        throwsA(
          isA<ApiFailure>().having((error) => error.status, 'status', 401),
        ),
      );
      expect(
        await const FlutterSecureStorage().read(key: 'workspace_session'),
        null,
      );
      await api.changeServer('https://balut.example.com');
      await api.session();
    },
  );
  test('image retry keeps the same key and raw JPEG payload', () async {
    var count = 0;
    final bytes = Uint8List.fromList([255, 216, 255, 0]);
    final api = ApiClient(
      httpClient: MockClient((request) async {
        count++;
        expect(request.url.path, '/api/v1/egg-analysis');
        expect(request.headers['idempotency-key'], 'same-key-123');
        expect(request.headers['content-type'], 'image/jpeg');
        expect(request.bodyBytes, bytes);
        return count == 1
            ? http.Response('{}', 503)
            : http.Response(jsonEncode(predictionJson()), 200);
      }),
    );
    await expectLater(
      api.analyze(bytes, 'same-key-123'),
      throwsA(isA<ApiFailure>()),
    );
    expect((await api.analyze(bytes, 'same-key-123')).label, 'DAY_16');
  });
  test(
    'server addresses reject insecure remote hosts, credentials and paths',
    () {
      for (final address in [
        'http://192.168.1.2:8765',
        'https://user:pass@example.com',
        'https://example.com/path',
        'file:///test',
        'https://example.com?q=1',
      ]) {
        expect(
          () => ApiClient.parseServer(address),
          throwsA(isA<ApiFailure>()),
        );
      }
      expect(
        ApiClient.parseServer('https://example.com/').toString(),
        'https://example.com',
      );
      expect(ApiClient.parseServer('http://127.0.0.1:8765').host, '127.0.0.1');
    },
  );
}
