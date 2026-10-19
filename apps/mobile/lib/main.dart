import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'api_client.dart';
import 'models.dart';
import 'theme.dart';
import 'workspace.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final certificate = await rootBundle.load(
    'assets/certificates/balut-local-box.pem',
  );
  SecurityContext.defaultContext.setTrustedCertificatesBytes(
    certificate.buffer.asUint8List(
      certificate.offsetInBytes,
      certificate.lengthInBytes,
    ),
  );
  runApp(const BalutOperatorApp());
}

class BalutOperatorApp extends StatefulWidget {
  const BalutOperatorApp({this.api, super.key});
  final ApiClient? api;
  @override
  State<BalutOperatorApp> createState() => _BalutOperatorAppState();
}

class _BalutOperatorAppState extends State<BalutOperatorApp> {
  late final ApiClient _api = widget.api ?? ApiClient();
  bool _filipino = false;
  bool _checking = true;
  AuthSession? _session;
  String? _error;
  @override
  void initState() {
    super.initState();
    _connect(restore: true);
  }

  @override
  void dispose() {
    if (widget.api == null) _api.close();
    super.dispose();
  }

  Future<void> _connect({bool restore = false}) async {
    setState(() {
      _checking = true;
      _error = null;
      _session = null;
    });
    try {
      if (restore) await _api.restore();
      final session = await _api.session();
      if (mounted) setState(() => _session = session);
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  void _expired() => setState(() {
    _session = const AuthSession(authenticated: false, setupRequired: false);
    _error = _filipino
        ? 'Natapos ang session. Mag-sign in muli.'
        : 'Session ended. Sign in again.';
  });

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'EggGrade IoT',
    theme: balutTheme(Brightness.light),
    darkTheme: balutTheme(Brightness.dark),
    locale: Locale(_filipino ? 'fil' : 'en'),
    supportedLocales: const [Locale('en'), Locale('fil')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    home: Builder(
      builder: (context) {
        Future<void> server() async {
          final changed = await Navigator.of(context).push<bool>(
            MaterialPageRoute(
              builder: (_) => ServerPage(api: _api, filipino: _filipino),
            ),
          );
          if (changed == true && mounted) await _connect();
        }

        if (_checking) {
          return const Scaffold(
            body: SafeArea(
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Brand(),
                    SizedBox(height: 32),
                    BusyLabel('Opening your workspace…'),
                  ],
                ),
              ),
            ),
          );
        }
        if (_session?.authenticated == true && _error == null) {
          return Workspace(
            api: _api,
            filipino: _filipino,
            onLanguage: () => setState(() => _filipino = !_filipino),
            onExpired: _expired,
            onSignedOut: () => setState(
              () => _session = const AuthSession(
                authenticated: false,
                setupRequired: false,
              ),
            ),
          );
        }
        if (_session == null || (_error != null && _session!.authenticated)) {
          return Scaffold(
            appBar: AppBar(title: const Brand()),
            body: SafeArea(
              child: Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(24),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 430),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Icon(
                          Icons.link_off,
                          color: Theme.of(context).colorScheme.secondary,
                          size: 36,
                        ),
                        const SizedBox(height: 24),
                        Text(
                          _filipino
                              ? 'Ikonekta ang workspace.'
                              : 'Connect your workspace.',
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          _filipino
                              ? 'Gamitin ang parehong EggGrade IoT server ng web app.'
                              : 'Use the same EggGrade IoT server as your web app.',
                        ),
                        if (_error != null) Notice(_error!),
                        Text(
                          _api.base.toString(),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                        const SizedBox(height: 24),
                        FilledButton(
                          onPressed: _connect,
                          child: Text(
                            _filipino ? 'Subukan muli' : 'Retry connection',
                          ),
                        ),
                        const SizedBox(height: 8),
                        TextButton(
                          onPressed: server,
                          child: Text(
                            _filipino ? 'Baguhin ang server' : 'Change server',
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          );
        }
        return AccountPage(
          api: _api,
          setupRequired: _session!.setupRequired,
          filipino: _filipino,
          notice: _error,
          onLanguage: () => setState(() => _filipino = !_filipino),
          onServer: server,
          onSignedIn: () => setState(() {
            _error = null;
            _session = const AuthSession(
              authenticated: true,
              setupRequired: false,
            );
          }),
        );
      },
    ),
  );
}

class AccountPage extends StatefulWidget {
  const AccountPage({
    required this.api,
    required this.setupRequired,
    required this.filipino,
    required this.onLanguage,
    required this.onServer,
    required this.onSignedIn,
    this.notice,
    super.key,
  });
  final ApiClient api;
  final bool setupRequired, filipino;
  final VoidCallback onLanguage, onServer, onSignedIn;
  final String? notice;
  @override
  State<AccountPage> createState() => _AccountPageState();
}

class _AccountPageState extends State<AccountPage> {
  final _form = GlobalKey<FormState>();
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _confirmation = TextEditingController();
  late bool _creating = widget.setupRequired;
  late bool _canRegister = widget.setupRequired;
  bool _visible = false, _busy = false;
  String? _error;
  String t(String en, String fil) => widget.filipino ? fil : en;
  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    _confirmation.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy || !_form.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.login(
        _username.text,
        _password.text,
        confirmation: _creating ? _confirmation.text : null,
      );
      if (!mounted) return;
      TextInput.finishAutofillContext();
      _password.clear();
      _confirmation.clear();
      widget.onSignedIn();
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.toString();
        if (error is ApiFailure && error.status == 409) {
          _creating = false;
          _canRegister = false;
        }
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final form = SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Flexible(
                    child: TextButton(
                      onPressed: _busy ? null : widget.onServer,
                      child: Text(t('Your workspace', 'Iyong workspace')),
                    ),
                  ),
                  TextButton.icon(
                    onPressed: _busy ? null : widget.onLanguage,
                    icon: const Icon(Icons.translate, size: 18),
                    label: Text(widget.filipino ? 'English' : 'Filipino'),
                  ),
                ],
              ),
              const SizedBox(height: 28),
              Align(
                alignment: Alignment.centerLeft,
                child: Icon(
                  Icons.lock_outline,
                  color: theme.colorScheme.secondary,
                  size: 27,
                ),
              ),
              const SizedBox(height: 24),
              Text(
                _creating
                    ? t('Create your account.', 'Gumawa ng account.')
                    : t('Welcome back.', 'Maligayang pagbabalik.'),
                style: theme.textTheme.headlineLarge,
              ),
              const SizedBox(height: 14),
              Text(
                _creating
                    ? t(
                        'Your username. Your password. Your workbench.',
                        'Iyong username, password, at workbench.',
                      )
                    : t(
                        'Sign in to your EggGrade IoT workbench.',
                        'Mag-sign in sa iyong EggGrade IoT workbench.',
                      ),
                style: theme.textTheme.bodyMedium!.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 32),
              AutofillGroup(
                child: Form(
                  key: _form,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextFormField(
                        controller: _username,
                        enabled: !_busy,
                        autofillHints: const [AutofillHints.username],
                        textInputAction: TextInputAction.next,
                        autocorrect: false,
                        enableSuggestions: false,
                        decoration: InputDecoration(
                          labelText: 'Username',
                          hintText: t(
                            'Enter your username',
                            'Ilagay ang username',
                          ),
                        ),
                        validator: (value) => _creating
                            ? RegExp(
                                    r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,31}$',
                                  ).hasMatch(value!.trim())
                                  ? null
                                  : t(
                                      'Use 3–32 letters, numbers, dots or hyphens.',
                                      'Gumamit ng 3–32 letra o numero.',
                                    )
                            : value!.trim().isEmpty
                            ? t('Enter your username.', 'Ilagay ang username.')
                            : null,
                      ),
                      const SizedBox(height: 24),
                      TextFormField(
                        controller: _password,
                        enabled: !_busy,
                        obscureText: !_visible,
                        autocorrect: false,
                        enableSuggestions: false,
                        autofillHints: [
                          _creating
                              ? AutofillHints.newPassword
                              : AutofillHints.password,
                        ],
                        textInputAction: _creating
                            ? TextInputAction.next
                            : TextInputAction.done,
                        onFieldSubmitted: (_) {
                          if (!_creating) _submit();
                        },
                        decoration: InputDecoration(
                          labelText: 'Password',
                          helperText: _creating
                              ? t(
                                  'At least 12 characters. A short phrase works well.',
                                  '12 character pataas. Maaaring maikling parirala.',
                                )
                              : null,
                          suffixIcon: IconButton(
                            tooltip: _visible
                                ? t('Hide password', 'Itago ang password')
                                : t('Show password', 'Ipakita ang password'),
                            onPressed: () =>
                                setState(() => _visible = !_visible),
                            icon: Icon(
                              _visible
                                  ? Icons.visibility_off_outlined
                                  : Icons.visibility_outlined,
                            ),
                          ),
                        ),
                        validator: (value) => value!.isEmpty
                            ? t('Enter your password.', 'Ilagay ang password.')
                            : (_creating && value.runes.length < 12) ||
                                  value.runes.length > 128
                            ? t(
                                'Use 12–128 characters.',
                                'Gumamit ng 12–128 character.',
                              )
                            : null,
                      ),
                      if (_creating) ...[
                        const SizedBox(height: 24),
                        TextFormField(
                          controller: _confirmation,
                          enabled: !_busy,
                          obscureText: !_visible,
                          autocorrect: false,
                          enableSuggestions: false,
                          autofillHints: const [AutofillHints.newPassword],
                          textInputAction: TextInputAction.done,
                          onFieldSubmitted: (_) => _submit(),
                          decoration: InputDecoration(
                            labelText: t(
                              'Confirm password',
                              'Ulitin ang password',
                            ),
                          ),
                          validator: (value) => value != _password.text
                              ? t(
                                  'Passwords do not match.',
                                  'Hindi magkapareho ang mga password.',
                                )
                              : null,
                        ),
                      ],
                      if (_error != null || widget.notice != null)
                        Notice(_error ?? widget.notice!),
                      const SizedBox(height: 28),
                      FilledButton(
                        onPressed: _busy ? null : _submit,
                        child: _busy
                            ? BusyLabel(
                                _creating
                                    ? t(
                                        'Creating account…',
                                        'Ginagawa ang account…',
                                      )
                                    : t('Signing in…', 'Nagsa-sign in…'),
                              )
                            : Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      _creating
                                          ? t(
                                              'Create account',
                                              'Gumawa ng account',
                                            )
                                          : t('Sign in', 'Mag-sign in'),
                                    ),
                                  ),
                                  const Icon(Icons.arrow_forward, size: 20),
                                ],
                              ),
                      ),
                    ],
                  ),
                ),
              ),
              if (_canRegister)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: TextButton(
                    onPressed: _busy
                        ? null
                        : () => setState(() {
                            _creating = !_creating;
                            _error = null;
                            _password.clear();
                            _confirmation.clear();
                            _visible = false;
                            _form.currentState!.reset();
                          }),
                    child: Text(
                      _creating
                          ? t(
                              'Already set up? Sign in',
                              'May account na? Mag-sign in',
                            )
                          : t('Create an account', 'Gumawa ng account'),
                    ),
                  ),
                ),
              const SizedBox(height: 24),
              Text(
                _creating
                    ? t(
                        'One account per workspace. Your existing records stay.',
                        'Isang account bawat workspace. Mananatili ang mga tala.',
                      )
                    : t(
                        'Use the same account as your web app.',
                        'Gamitin ang account ng iyong web app.',
                      ),
                style: theme.textTheme.bodySmall,
              ),
              const SizedBox(height: 40),
              Text(
                t(
                  'Images and records stay on your EggGrade IoT server.',
                  'Naka-save sa EggGrade IoT server ang mga larawan at tala.',
                ),
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, box) {
            if (box.maxWidth >= 900 && box.maxHeight >= 600) {
              return Row(
                children: [
                  Expanded(
                    child: Container(
                      color: ink,
                      padding: const EdgeInsets.all(48),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Brand(onDark: true),
                          const Spacer(),
                          const Icon(
                            Icons.egg_outlined,
                            size: 72,
                            color: amber,
                          ),
                          const SizedBox(height: 32),
                          Text(
                            t('A closer look.', 'Mas malinaw na kuha.'),
                            style: theme.textTheme.headlineLarge!.copyWith(
                              color: paper,
                            ),
                          ),
                          Text(
                            t('A clearer record.', 'Mas maayos na tala.'),
                            style: theme.textTheme.headlineLarge!.copyWith(
                              color: amber,
                            ),
                          ),
                          const SizedBox(height: 24),
                          Text(
                            t(
                              'Your candling workspace, all in one place.',
                              'Isang lugar para sa iyong mga larawan.',
                            ),
                            style: const TextStyle(color: paper),
                          ),
                          const Spacer(),
                          const Text(
                            'EggGrade IoT',
                            style: TextStyle(color: amber),
                          ),
                        ],
                      ),
                    ),
                  ),
                  Expanded(child: form),
                ],
              );
            }
            return Column(
              children: [
                Container(
                  width: double.infinity,
                  color: ink,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 22,
                  ),
                  child: const Brand(onDark: true),
                ),
                Expanded(child: form),
              ],
            );
          },
        ),
      ),
    );
  }
}

class ServerPage extends StatefulWidget {
  const ServerPage({required this.api, required this.filipino, super.key});
  final ApiClient api;
  final bool filipino;
  @override
  State<ServerPage> createState() => _ServerPageState();
}

class _ServerPageState extends State<ServerPage> {
  late final _address = TextEditingController(text: widget.api.base.toString());
  String? _error;
  bool _busy = false;
  @override
  void dispose() {
    _address.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.api.changeServer(_address.text);
      if (mounted) Navigator.pop(context, true);
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(widget.filipino ? 'EggGrade IoT server' : 'Workspace connection'),
    ),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text(
            widget.filipino ? 'Isang workspace.' : 'One shared workspace.',
            style: Theme.of(context).textTheme.headlineLarge,
          ),
          const SizedBox(height: 16),
          Text(
            widget.filipino
                ? 'Ilagay ang address ng iyong EggGrade IoT server.'
                : 'Enter your EggGrade IoT server address. Your account and records stay together.',
          ),
          const SizedBox(height: 28),
          TextField(
            controller: _address,
            enabled: !_busy,
            keyboardType: TextInputType.url,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: 'Server address',
              hintText: 'https://balut.example.com',
            ),
          ),
          if (_error != null) Notice(_error!),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(widget.filipino ? 'Kumonekta' : 'Connect'),
          ),
          const SizedBox(height: 20),
          Text(
            widget.filipino
                ? 'Kailangan ng USB connection para sa lokal na laptop server.'
                : 'The current laptop service connects through USB. Online access needs a deployed HTTPS server.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    ),
  );
}
