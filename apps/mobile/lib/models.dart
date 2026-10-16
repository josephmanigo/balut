class AuthSession {
  const AuthSession({required this.authenticated, required this.setupRequired});
  final bool authenticated;
  final bool setupRequired;
  factory AuthSession.fromJson(Map<String, dynamic> json) => AuthSession(
    authenticated: json['authenticated'] == true,
    setupRequired: json['setupRequired'] == true,
  );
}

class BoxStatus {
  const BoxStatus({
    this.cameraUrl = '',
    this.enabled = false,
    this.connected = false,
    this.calibrated = false,
    this.state = 'not_connected',
    this.preview,
    this.result,
  });
  final String cameraUrl, state;
  final bool enabled, connected, calibrated;
  final String? preview;
  final Prediction? result;
  factory BoxStatus.fromJson(Map<String, dynamic> json) => BoxStatus(
    cameraUrl: json['cameraUrl'] as String,
    enabled: json['enabled'] == true,
    connected: json['connected'] == true,
    calibrated: json['calibrated'] == true,
    state: json['state'] as String,
    preview: json['preview'] as String?,
    result: json['result'] == null
        ? null
        : Prediction.fromJson(json['result'] as Map<String, dynamic>),
  );
}

class Prediction {
  const Prediction({
    required this.id,
    required this.modelId,
    required this.createdAt,
    required this.label,
    required this.recapture,
    required this.reasons,
  });
  final String id;
  final String modelId;
  final DateTime createdAt;
  final String? label;
  final bool recapture;
  final List<String> reasons;

  factory Prediction.fromJson(Map<String, dynamic> json) {
    final label = json['sourcePrediction'];
    final recapture = json['recaptureRequested'] == true;
    final classified =
        json['analysisOutcome'] == 'CLASSIFIED' &&
        const ['DAY_16', 'DAY_18', 'REJECT'].contains(label) &&
        !recapture;
    final unclassified =
        json['analysisOutcome'] == 'RECAPTURE_REQUIRED' &&
        label == null &&
        recapture;
    if (json['operationalUseAuthorized'] != false ||
        json['operationalOutcome'] != 'NOT_AUTHORIZED' ||
        json['reviewRequired'] != false ||
        !(classified || unclassified) ||
        json['recaptureReasons'] is! List) {
      throw const FormatException(
        'Unsupported result. No class has been assigned.',
      );
    }
    return Prediction(
      id: json['predictionId'] as String,
      modelId: json['modelId'] as String,
      createdAt: DateTime.parse(json['createdAt'] as String),
      label: label as String?,
      recapture: recapture,
      reasons: (json['recaptureReasons'] as List).cast<String>(),
    );
  }

  String title(bool filipino) => recapture
      ? (filipino ? 'Kailangan ng ibang larawan' : 'Another image needed')
      : switch (label) {
          'DAY_16' => 'Day 16',
          'DAY_18' => 'Day 18',
          _ => filipino ? 'Posibleng reject' : 'Reject — suspected',
        };

  String nextStep(bool filipino) {
    final messages = <String, (String, String)>{
      'IMAGE_TOO_SMALL': (
        'Use a larger image.',
        'Gumamit ng mas malaking larawan.',
      ),
      'LOW_CONTRAST': (
        'Adjust the candling light.',
        'Ayusin ang ilaw ng candling.',
      ),
      'IMAGE_TOO_BLURRY': (
        'Hold steady. Focus on the egg.',
        'Huwag igalaw. Ituon sa itlog.',
      ),
      'EXPOSURE_CLIPPED': (
        'Adjust exposure. Keep shell details visible.',
        'Ayusin ang exposure. Ipakita ang detalye.',
      ),
      'UNFAMILIAR_APPEARANCE': (
        'Center one egg. Use consistent lighting.',
        'Igitna ang itlog. Gumamit ng pantay na ilaw.',
      ),
    };
    final message =
        messages[reasons.firstOrNull] ??
        (
          'Take another view of the same egg.',
          'Kunan muli sa ibang anggulo ang itlog.',
        );
    return filipino ? message.$2 : message.$1;
  }
}
