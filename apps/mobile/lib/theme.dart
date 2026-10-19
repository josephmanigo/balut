import 'package:flutter/material.dart';

const ink = Color(0xFF15221D);
const paper = Color(0xFFF7F4EC);
const amber = Color(0xFFF0CF9E);
const teal = Color(0xFF245864);

ThemeData balutTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(seedColor: teal, brightness: brightness)
      .copyWith(
        primary: dark ? amber : ink,
        onPrimary: dark ? ink : paper,
        surface: dark ? ink : paper,
        onSurface: dark ? paper : ink,
        onSurfaceVariant: dark
            ? const Color(0xFFBDCCC2)
            : const Color(0xFF58665E),
        outline: dark ? const Color(0xFF809487) : const Color(0xFF8A958C),
        outlineVariant: dark
            ? const Color(0xFF3F5347)
            : const Color(0xFFCFC8BA),
        secondary: dark ? const Color(0xFFB9D1D0) : teal,
        secondaryContainer: dark
            ? const Color(0xFF304B3F)
            : const Color(0xFFEAE4D8),
        onSecondaryContainer: dark ? paper : ink,
      );
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    brightness: brightness,
  );
  TextStyle serif(TextStyle? style, double size) => style!.copyWith(
    fontFamily: 'BalutSerif',
    fontSize: size,
    fontWeight: FontWeight.w400,
    height: 1.2,
    letterSpacing: -size * .02,
  );
  return base.copyWith(
    scaffoldBackgroundColor: scheme.surface,
    textTheme: base.textTheme.copyWith(
      headlineLarge: serif(base.textTheme.headlineLarge, 36),
      headlineMedium: serif(base.textTheme.headlineMedium, 30),
      headlineSmall: serif(base.textTheme.headlineSmall, 24),
      bodyLarge: base.textTheme.bodyLarge!.copyWith(height: 1.6),
      bodyMedium: base.textTheme.bodyMedium!.copyWith(
        fontSize: 16,
        height: 1.6,
      ),
      bodySmall: base.textTheme.bodySmall!.copyWith(
        fontSize: 14,
        height: 1.6,
        color: scheme.onSurfaceVariant,
      ),
      labelLarge: base.textTheme.labelLarge!.copyWith(
        fontSize: 15,
        fontWeight: FontWeight.w600,
        letterSpacing: 0,
      ),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: scheme.surface,
      foregroundColor: scheme.onSurface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF1C2E24) : const Color(0xFFFDFBF6),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 17),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(4)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(4),
        borderSide: BorderSide(color: scheme.outline),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(4),
        borderSide: BorderSide(color: scheme.secondary, width: 2),
      ),
      helperMaxLines: 3,
      errorMaxLines: 3,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(48, 54),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(48, 50),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
    dividerTheme: DividerThemeData(
      color: scheme.outlineVariant,
      thickness: 1,
      space: 32,
    ),
    expansionTileTheme: const ExpansionTileThemeData(
      tilePadding: EdgeInsets.zero,
      childrenPadding: EdgeInsets.only(bottom: 16),
    ),
  );
}

class Brand extends StatelessWidget {
  const Brand({this.onDark = false, super.key});
  final bool onDark;
  @override
  Widget build(BuildContext context) => Semantics(
    label: 'EggGrade IoT',
    child: ExcludeSemantics(
      child: FittedBox(
        fit: BoxFit.scaleDown,
        alignment: Alignment.centerLeft,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.document_scanner_outlined,
              size: 27,
              color: onDark ? amber : Theme.of(context).colorScheme.secondary,
            ),
            const SizedBox(width: 10),
            Text(
              'EggGrade',
              style: TextStyle(
                fontFamily: 'BalutSerif',
                fontSize: 29,
                letterSpacing: -1,
                color: onDark ? paper : null,
              ),
            ),
            const SizedBox(width: 5),
            Text(
              'IoT',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: onDark ? paper : null,
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class Notice extends StatelessWidget {
  const Notice(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) => Semantics(
    liveRegion: true,
    child: Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      margin: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        text,
        style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
      ),
    ),
  );
}

class BusyLabel extends StatelessWidget {
  const BusyLabel(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      SizedBox.square(
        dimension: 18,
        child: CircularProgressIndicator(
          strokeWidth: 2,
          color: DefaultTextStyle.of(context).style.color,
        ),
      ),
      const SizedBox(width: 12),
      Flexible(child: Text(text)),
    ],
  );
}
