import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'api_client.dart';
import 'models.dart';
import 'automatic_box.dart';
import 'theme.dart';

class Workspace extends StatefulWidget {
  const Workspace({
    required this.api,
    required this.filipino,
    required this.onLanguage,
    required this.onSignedOut,
    required this.onExpired,
    super.key,
  });
  final ApiClient api;
  final bool filipino;
  final VoidCallback onLanguage, onSignedOut, onExpired;
  @override
  State<Workspace> createState() => _WorkspaceState();
}

class _WorkspaceState extends State<Workspace> {
  int _view = 0, _historyVersion = 0;
  bool _signingOut = false;
  String? _error;
  String t(String en, String fil) => widget.filipino ? fil : en;
  Future<void> _logout() async {
    setState(() {
      _signingOut = true;
      _error = null;
    });
    try {
      await widget.api.logout();
      if (mounted) widget.onSignedOut();
    } on Object catch (error) {
      if (mounted) {
        if (error is ApiFailure && error.status == 401) {
          widget.onExpired();
        } else {
          setState(() => _error = error.toString());
        }
      }
    } finally {
      if (mounted) setState(() => _signingOut = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Brand(),
      actions: [
        PopupMenuButton<String>(
          tooltip: t('Account and language', 'Account at wika'),
          enabled: !_signingOut,
          icon: const Icon(Icons.more_horiz),
          onSelected: (value) {
            if (value == 'language') {
              widget.onLanguage();
            } else {
              _logout();
            }
          },
          itemBuilder: (_) => [
            PopupMenuItem(
              value: 'language',
              child: Text(widget.filipino ? 'English' : 'Filipino'),
            ),
            PopupMenuItem(
              value: 'logout',
              child: Text(t('Sign out', 'Lumabas')),
            ),
          ],
        ),
      ],
    ),
    body: SafeArea(
      child: LayoutBuilder(
        builder: (context, box) {
          final wide = box.maxWidth >= 900;
          final content = Column(
            children: [
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Notice(_error!),
                ),
              if (_signingOut) const LinearProgressIndicator(),
              if (!wide)
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 12,
                  ),
                  child: SizedBox(
                    width: double.infinity,
                    child: SegmentedButton<int>(
                      showSelectedIcon: false,
                      segments: [
                        ButtonSegment(
                          value: 0,
                          icon: const Icon(Icons.document_scanner_outlined),
                          label: Text(t('Analyze', 'Suriin')),
                        ),
                        ButtonSegment(
                          value: 1,
                          icon: const Icon(Icons.history),
                          label: Text(t('History', 'Mga tala')),
                        ),
                      ],
                      selected: {_view},
                      onSelectionChanged: (value) =>
                          setState(() => _view = value.first),
                      style: SegmentedButton.styleFrom(
                        minimumSize: const Size(48, 48),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(4),
                        ),
                      ),
                    ),
                  ),
                ),
              Expanded(
                child: IndexedStack(
                  index: _view,
                  children: [
                    AutomaticBoxPage(
                      active: _view == 0,
                      api: widget.api,
                      filipino: widget.filipino,
                      onExpired: widget.onExpired,
                      onSaved: () => setState(() => _historyVersion++),
                    ),
                    HistoryPage(
                      api: widget.api,
                      filipino: widget.filipino,
                      version: _historyVersion,
                      active: _view == 1,
                      onExpired: widget.onExpired,
                      onAnalyze: () => setState(() => _view = 0),
                    ),
                  ],
                ),
              ),
            ],
          );
          if (!wide) return content;
          return Row(
            children: [
              NavigationRail(
                selectedIndex: _view,
                onDestinationSelected: (index) => setState(() => _view = index),
                labelType: NavigationRailLabelType.all,
                destinations: [
                  NavigationRailDestination(
                    icon: const Icon(Icons.document_scanner_outlined),
                    label: Text(t('Analyze', 'Suriin')),
                  ),
                  NavigationRailDestination(
                    icon: const Icon(Icons.history),
                    label: Text(t('History', 'Mga tala')),
                  ),
                ],
              ),
              const VerticalDivider(width: 1),
              Expanded(child: content),
            ],
          );
        },
      ),
    ),
  );
}

class ResultContent extends StatelessWidget {
  const ResultContent({
    required this.prediction,
    required this.filipino,
    required this.onNext,
    super.key,
  });
  final Prediction prediction;
  final bool filipino;
  final VoidCallback? onNext;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final symbol = prediction.label == 'DAY_16'
        ? '16'
        : prediction.label == 'DAY_18'
        ? '18'
        : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: Container(
            width: 88,
            height: 96,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: theme.colorScheme.secondaryContainer,
              borderRadius: BorderRadius.circular(44),
            ),
            child: symbol != null
                ? Text(symbol, style: theme.textTheme.headlineLarge)
                : Icon(
                    prediction.recapture
                        ? Icons.refresh
                        : Icons.document_scanner_outlined,
                    size: 34,
                  ),
          ),
        ),
        const SizedBox(height: 24),
        Text(prediction.title(filipino), style: theme.textTheme.headlineLarge),
        const SizedBox(height: 12),
        Text(
          prediction.recapture
              ? (filipino
                    ? 'Walang klasipikasyon · pananaliksik'
                    : 'Unclassified · research mode')
              : (filipino
                    ? 'Tantiya para sa pananaliksik'
                    : 'Research estimate'),
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 20),
        Text(
          prediction.recapture
              ? prediction.nextStep(filipino)
              : (filipino
                    ? 'Tantiya batay sa hitsura. Hindi pagsusuri ng kaligtasan ng pagkain.'
                    : prediction.label == 'REJECT'
                    ? 'Appearance matches reject examples. Not a food-safety verdict.'
                    : 'Appearance matches ${prediction.title(false)} examples.'),
        ),
        const SizedBox(height: 28),
        if (onNext != null)
          OutlinedButton.icon(
            onPressed: onNext,
            icon: const Icon(Icons.arrow_forward, size: 18),
            label: Text(
              prediction.recapture
                  ? (filipino
                        ? 'Pumili ng ibang larawan'
                        : 'Choose another image')
                  : (filipino ? 'Suriin ang susunod' : 'Analyze next egg'),
            ),
          ),
        const SizedBox(height: 16),
        ExpansionTile(
          title: Text(
            filipino ? 'Nai-save na tala' : 'Saved prediction record',
            style: theme.textTheme.bodyMedium,
          ),
          children: [RecordDetails(prediction: prediction, filipino: filipino)],
        ),
      ],
    );
  }
}

class RecordDetails extends StatelessWidget {
  const RecordDetails({
    required this.prediction,
    required this.filipino,
    super.key,
  });
  final Prediction prediction;
  final bool filipino;
  @override
  Widget build(BuildContext context) => Align(
    alignment: Alignment.centerLeft,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          filipino ? 'ID ng tala' : 'Record ID',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        SelectableText(prediction.id),
        const SizedBox(height: 12),
        Text(
          filipino ? 'Modelo' : 'Model',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        SelectableText(prediction.modelId),
        const SizedBox(height: 12),
        Text(
          DateFormat.yMMMd().add_jm().format(prediction.createdAt.toLocal()),
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    ),
  );
}

class HistoryPage extends StatefulWidget {
  const HistoryPage({
    required this.api,
    required this.filipino,
    required this.version,
    required this.active,
    required this.onExpired,
    required this.onAnalyze,
    super.key,
  });
  final ApiClient api;
  final bool filipino, active;
  final int version;
  final VoidCallback onExpired, onAnalyze;
  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  List<Prediction>? _items;
  bool _loading = false;
  String? _error;
  String t(String en, String fil) => widget.filipino ? fil : en;
  @override
  void initState() {
    super.initState();
    if (widget.active) _load();
  }

  @override
  void didUpdateWidget(covariant HistoryPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active &&
        (!oldWidget.active || oldWidget.version != widget.version)) {
      _load();
    }
  }

  Future<void> _load() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await widget.api.history();
      if (mounted) setState(() => _items = items);
    } on Object catch (error) {
      if (mounted) {
        if (error is ApiFailure && error.status == 401) {
          widget.onExpired();
        } else {
          setState(
            () => _error = t(
              'Records could not load. Try Refresh.',
              'Hindi makuha ang mga tala. I-refresh muli.',
            ),
          );
        }
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Text(
            t('Your recent results.', 'Mga huling resulta.'),
            style: theme.textTheme.headlineLarge,
          ),
          const SizedBox(height: 12),
          Text(
            t(
              'The latest 50 records, kept in one place.',
              'Ang huling 50 tala, nasa isang lugar.',
            ),
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: _loading ? null : _load,
              icon: const Icon(Icons.refresh, size: 18),
              label: Text(t('Refresh', 'I-refresh')),
            ),
          ),
          if (_loading)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 32),
              child: BusyLabel(t('Loading records…', 'Kinukuha ang mga tala…')),
            ),
          if (_error != null) Notice(_error!),
          if (!_loading && _error == null && _items?.isEmpty == true)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 48),
              child: Column(
                children: [
                  Icon(
                    Icons.history,
                    size: 40,
                    color: theme.colorScheme.secondary,
                  ),
                  const SizedBox(height: 24),
                  Text(
                    t('A fresh start.', 'Bagong simula.'),
                    style: theme.textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    t(
                      'Your first analysis will appear here.',
                      'Dito lalabas ang unang pagsusuri.',
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 28),
                  FilledButton(
                    onPressed: widget.onAnalyze,
                    child: Text(t('Analyze an egg', 'Suriin ang itlog')),
                  ),
                ],
              ),
            ),
          if (_error == null)
            for (final item in _items ?? <Prediction>[])
              ExpansionTile(
                key: ValueKey(item.id),
                leading: Icon(
                  item.recapture
                      ? Icons.refresh
                      : Icons.document_scanner_outlined,
                  color: theme.colorScheme.secondary,
                ),
                title: Text(
                  item.title(widget.filipino),
                  style: theme.textTheme.titleMedium,
                ),
                subtitle: Text(
                  DateFormat.MMMd().add_jm().format(item.createdAt.toLocal()),
                ),
                children: [
                  RecordDetails(prediction: item, filipino: widget.filipino),
                ],
              ),
          const Divider(height: 40),
          Text(
            t('Saved on your EggGrade IoT server', 'Naka-save sa EggGrade IoT server'),
            style: theme.textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
