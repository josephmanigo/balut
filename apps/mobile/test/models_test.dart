import 'package:balut_operator/models.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> predictionJson({bool recapture = false}) => {
  'predictionId': 'prediction-001',
  'modelId': 'egg-grade',
  'createdAt': '2026-10-14T01:00:00Z',
  'sourcePrediction': recapture ? null : 'DAY_16',
  'analysisOutcome': recapture ? 'RECAPTURE_REQUIRED' : 'CLASSIFIED',
  'recaptureRequested': recapture,
  'recaptureReasons': recapture ? ['IMAGE_TOO_BLURRY'] : [],
  'operationalUseAuthorized': false,
  'operationalOutcome': 'NOT_AUTHORIZED',
  'reviewRequired': false,
};

void main() {
  test('classified result preserves research authority', () {
    final result = Prediction.fromJson(predictionJson());
    expect(result.title(false), 'Day 16');
    expect(result.recapture, false);
  });
  test('recapture gives next action without assigning a class', () {
    final result = Prediction.fromJson(predictionJson(recapture: true));
    expect(result.label, null);
    expect(result.title(false), 'Another image needed');
    expect(result.nextStep(false), 'Hold steady. Focus on the egg.');
  });
  test('unfertilized is distinct from historical reject records', () {
    final result = Prediction.fromJson({...predictionJson(), 'sourcePrediction': 'UNFERTILIZED'});
    expect(result.title(false), 'Reject');
    expect(result.title(true), 'Reject');
    expect(result.label, 'UNFERTILIZED');
    expect(Prediction.fromJson({...predictionJson(), 'sourcePrediction': 'REJECT'}).title(false), 'Reject');
  });
  test('unsupported or operational result fails closed', () {
    for (final change in [
      {'operationalUseAuthorized': true},
      {'sourcePrediction': 'SAFE_TO_EAT'},
      {'recaptureRequested': true},
      {'reviewRequired': true},
      {'recaptureReasons': null},
    ]) {
      expect(
        () => Prediction.fromJson({...predictionJson(), ...change}),
        throwsFormatException,
      );
    }
  });
}
