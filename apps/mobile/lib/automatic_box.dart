import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api_client.dart';
import 'models.dart';
import 'theme.dart';
import 'workspace.dart' show ResultContent;

class AutomaticBoxPage extends StatefulWidget {
  const AutomaticBoxPage({
    required this.api,
    required this.filipino,
    required this.onExpired,
    required this.onSaved,
    this.active = true,
    super.key,
  });
  final ApiClient api;
  final bool filipino;
  final bool active;
  final VoidCallback onExpired, onSaved;
  @override
  State<AutomaticBoxPage> createState() => _AutomaticBoxPageState();
}

class _AutomaticBoxPageState extends State<AutomaticBoxPage>
    with WidgetsBindingObserver {
  final _address = TextEditingController();
  final _scroll = ScrollController();
  Timer? _timer;
  BoxStatus? _status;
  String? _error, _lastId;
  bool _busy = false,
      _polling = false,
      _empty = false,
      _setup = false,
      _unreachable = false,
      _active = true;
  int _generation = 0;
  String t(String en, String fil) => widget.filipino ? fil : en;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _poll();
  }

  @override
  void dispose() {
    _timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    _address.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _active = state == AppLifecycleState.resumed;
    _timer?.cancel();
    if (_active) _poll();
  }

  void _accept(BoxStatus value) {
    if (_status == null) _address.text = value.cameraUrl;
    setState(() {
      _status = value;
      _unreachable = false;
    });
    if (value.result != null && value.result!.id != _lastId) {
      _lastId = value.result!.id;
      widget.onSaved();
      if (widget.active) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted && _scroll.hasClients) _scroll.jumpTo(0);
        });
      }
    }
  }

  Future<void> _poll() async {
    if (_polling || !mounted || !_active) return;
    _polling = true;
    final generation = _generation;
    try {
      if (!_busy) {
        final value = await widget.api.boxStatus();
        if (mounted && generation == _generation) _accept(value);
      }
    } on Object catch (error) {
      if (mounted) {
        if (error is ApiFailure && error.status == 401) {
          widget.onExpired();
        } else {
          setState(() => _unreachable = true);
        }
      }
    } finally {
      _polling = false;
      if (mounted && _active) {
        _timer?.cancel();
        _timer = Timer(const Duration(milliseconds: 250), _poll);
      }
    }
  }

  Future<void> _change(String action, Map<String, Object> body) async {
    if (_busy) return;
    _generation++;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final value = await widget.api.boxAction(action, body);
      if (mounted) {
        _accept(value);
        if (action == 'reference') {
          setState(() {
            _empty = false;
            _setup = false;
          });
        }
      }
    } on Object catch (error) {
      if (mounted) {
        if (error is ApiFailure && error.status == 401) {
          widget.onExpired();
        } else {
          setState(() => _error = error.toString());
        }
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = _status;
    final (heading, hint) = _unreachable
        ? (
            t('Connection interrupted.', 'Naputol ang koneksyon.'),
            t(
              'Check the Balut server. Reconnecting automatically.',
              'Suriin ang Balut server. Kokonekta muli.',
            ),
          )
        : switch (status?.state) {
            'waiting' => (
              t('Ready for an egg.', 'Handa para sa itlog.'),
              t(
                'Place one egg. Keep your hands clear.',
                'Maglagay ng isang itlog. Ilayo ang mga kamay.',
              ),
            ),
            'settling' => (
              t('Preparing to capture.', 'Naghahanda sa pagkuha.'),
              t(
                'Keep your hands clear. Capture continues while the holder rotates.',
                'Ilayo ang mga kamay. Kukunan kahit umiikot ang lalagyan.',
              ),
            ),
            'analyzing' => (
              t('Taking a closer look.', 'Sinusuri ang larawan.'),
              t(
                'Your result saves automatically.',
                'Awtomatikong mase-save ang resulta.',
              ),
            ),
            'remove_egg' => (
              t('Result saved.', 'Nai-save ang resulta.'),
              t(
                'Remove the egg before placing the next one.',
                'Alisin ang itlog bago ilagay ang susunod.',
              ),
            ),
            'recapture' => (
              t('Another view needed.', 'Kailangan ng ibang kuha.'),
              t(
                'Remove the egg, adjust it, then place it again.',
                'Alisin, ayusin, at ilagay muli ang itlog.',
              ),
            ),
            'needs_reference' => (
              t('Start with an empty box.', 'Magsimula sa bakanteng kahon.'),
              t(
                'Remove the egg. Keep normal candling light on.',
                'Alisin ang itlog. Gamitin ang karaniwang ilaw.',
              ),
            ),
            'paused' => (
              t('Automatic mode paused.', 'Naka-pause ang awtomatikong mode.'),
              t(
                'Live view continues. Resume when the box is ready.',
                'Tuloy ang live na kuha. Ituloy ang pagsusuri kapag handa na ang kahon.',
              ),
            ),
            'offline' => (
              t('Camera disconnected.', 'Hindi konektado ang camera.'),
              t(
                'Check power and Wi-Fi. We’ll reconnect.',
                'Suriin ang kuryente at koneksyon ng camera. Kokonekta muli.',
              ),
            ),
            'error' => (
              t('Capture saved. Retrying…', 'Nai-save ang kuha. Inuulit…'),
              t(
                'Retrying the same capture without duplicate records.',
                'Inuulit ang parehong kuha nang walang dobleng tala.',
              ),
            ),
            'connecting' => (
              t('Finding your camera…', 'Hinahanap ang camera…'),
              t(
                'Keep the box powered on.',
                'Panatilihing nakabukas ang kahon.',
              ),
            ),
            null => (
              t('Connecting…', 'Kumokonekta…'),
              t(
                'Opening the box workspace.',
                'Binubuksan ang workspace ng kahon.',
              ),
            ),
            _ => (
              t('Connect your box.', 'Ikonekta ang kahon.'),
              t(
                'Set up the camera once. Then place an egg.',
                'I-setup ang camera. Ilagay ang itlog pagkatapos.',
              ),
            ),
          };
    final scene = Container(
      width: double.infinity,
      constraints: const BoxConstraints(minHeight: 185),
      decoration: BoxDecoration(
        color: theme.colorScheme.secondaryContainer.withValues(alpha: .35),
        border: Border.all(color: theme.colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (status?.preview != null)
            Image.memory(
              base64Decode(status!.preview!),
              gaplessPlayback: true,
              height: 230,
              fit: BoxFit.contain,
              errorBuilder: (_, _, _) =>
                  const Icon(Icons.broken_image_outlined, size: 40),
            )
          else
            Padding(
              padding: const EdgeInsets.all(36),
              child: Icon(
                Icons.camera_alt_outlined,
                size: 48,
                color: theme.colorScheme.secondary,
              ),
            ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              status?.connected == true && !_unreachable
                  ? t('Live camera view', 'Live na kuha ng camera')
                  : t('Camera view', 'Tanaw ng camera'),
              style: theme.textTheme.bodySmall,
            ),
          ),
        ],
      ),
    );
    final live = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          liveRegion: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(heading, style: theme.textTheme.headlineLarge),
              const SizedBox(height: 12),
              Text(hint),
            ],
          ),
        ),
        if (status?.state == 'analyzing')
          const Padding(
            padding: EdgeInsets.only(top: 20),
            child: LinearProgressIndicator(),
          ),
        if (status?.result != null) ...[
          const Divider(height: 40),
          Text(
            t('Latest saved result', 'Huling nai-save na resulta'),
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 20),
          ResultContent(
            prediction: status!.result!,
            filipino: widget.filipino,
            onNext: null,
          ),
        ],
      ],
    );
    return SingleChildScrollView(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 32),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1160),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.sensors,
                    size: 18,
                    color: theme.colorScheme.secondary,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      status?.connected == true && !_unreachable
                          ? t('Camera connected', 'Konektado ang camera')
                          : t(
                              'Camera not connected',
                              'Hindi konektado ang camera',
                            ),
                      style: theme.textTheme.bodySmall,
                    ),
                  ),
                  if (status?.calibrated == true)
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => _change('enabled', {
                              'enabled': !status!.enabled,
                            }),
                      child: Text(
                        status!.enabled
                            ? t('Pause', 'I-pause')
                            : t('Resume', 'Ituloy'),
                      ),
                    ),
                ],
              ),
              const Divider(height: 32),
              LayoutBuilder(
                builder: (context, constraints) => constraints.maxWidth >= 760
                    ? Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(child: scene),
                          const SizedBox(width: 40),
                          Expanded(child: live),
                        ],
                      )
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [live, const SizedBox(height: 24), scene],
                      ),
              ),
              if (_error != null) Notice(_error!),
              const Divider(height: 40),
              TextButton.icon(
                onPressed: () => setState(() => _setup = !_setup),
                icon: const Icon(Icons.tune, size: 18),
                label: Text(t('Box setup', 'Setup ng kahon')),
              ),
              if (_setup || status?.calibrated != true) ...[
                const SizedBox(height: 12),
                TextField(
                  controller: _address,
                  enabled: !_busy,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: InputDecoration(
                    labelText: t('Camera address', 'Address ng camera'),
                    hintText: 'http://192.168.1.50',
                  ),
                ),
                const SizedBox(height: 12),
                OutlinedButton(
                  onPressed: _busy
                      ? null
                      : () => _change('connect', {
                          'cameraUrl': _address.text.trim(),
                        }),
                  child: Text(
                    _busy
                        ? t('Please wait…', 'Sandali…')
                        : t('Connect camera', 'Ikonekta ang camera'),
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  t(
                    'Use the camera address provided during box setup.',
                    'Gamitin ang address ng camera na ibinigay sa setup ng kahon.',
                  ),
                  style: theme.textTheme.bodySmall,
                ),
                if (status?.cameraUrl.isNotEmpty == true) ...[
                  const SizedBox(height: 20),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    value: _empty,
                    onChanged: _busy
                        ? null
                        : (value) => setState(() => _empty = value == true),
                    title: Text(
                      t(
                        'The box is empty. Lighting is ready.',
                        'Bakante ang kahon. Handa ang ilaw.',
                      ),
                    ),
                  ),
                  FilledButton(
                    onPressed: !_empty || _busy
                        ? null
                        : () => _change('reference', {'emptyConfirmed': true}),
                    child: Text(
                      t(
                        'Save empty view & start',
                        'I-save ang bakanteng kuha at simulan',
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                Text(
                  t(
                    'Keep camera and lighting fixed. A lasting scene change triggers capture; this is not an egg-presence sensor.',
                    'Panatilihing nakapirmi ang camera at ilaw. Pagbabago sa tanawin ang nagti-trigger ng kuha; hindi ito sensor ng itlog.',
                  ),
                  style: theme.textTheme.bodySmall,
                ),
              ],
              const Divider(height: 40),
              Text(
                t(
                  'Appearance only · Not a food-safety assessment',
                  'Batay sa hitsura · Hindi pagsusuri ng kaligtasan ng pagkain',
                ),
                style: theme.textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
