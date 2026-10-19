---
name: EggGrade IoT Evidence Workbench
description: An evidence-first daylight instrument for fail-closed EggGrade IoT research operations.
colors:
  ink: "#15221d"
  muted: "#64706a"
  paper: "#f7f4ec"
  paper-deep: "#eee8dc"
  rule: "#cfc8ba"
  amber: "#d77f22"
  amber-soft: "#f0cf9e"
  teal: "#245864"
  teal-soft: "#b9d1d0"
  red: "#a54138"
  red-soft: "#e2b9b1"
  violet: "#6d577c"
  focus: "#83aab2"
  workspace-focus: "#245864"
typography:
  workspace-heading:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "clamp(32px, 3.4vw, 46px)"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: "-0.035em"
  display:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "clamp(40px, 5vw, 73px)"
    fontWeight: 500
    lineHeight: 0.98
    letterSpacing: "-0.045em"
  headline:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "clamp(38px, 5vw, 62px)"
    fontWeight: 500
    letterSpacing: "-0.045em"
  title:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "25px"
    fontWeight: 500
  body:
    fontFamily: 'Aptos, "Segoe UI", Arial, sans-serif'
    fontWeight: 400
  label:
    fontFamily: 'Aptos, "Segoe UI", Arial, sans-serif'
    fontSize: "11px"
    fontWeight: 800
    letterSpacing: "0.09em"
rounded:
  square: "0"
  control: "4px"
  upload: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "34px"
components:
  workspace-button:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "0 18px"
  workspace-button-hover:
    backgroundColor: "#304b3f"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "#ffffff"
    rounded: "{rounded.square}"
    padding: "0 18px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "#2b4037"
    textColor: "#ffffff"
    rounded: "{rounded.square}"
  evidence-frame:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    width: "104px"
  field-select:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    padding: "0 34px 0 10px"
    height: "42px"
---

# Design System: EggGrade IoT Evidence Workbench

## Overview

**Creative North Star: "The Daylight Vendor Instrument"**

### Current production workspace

The production `/` entry now opens the custom login, followed by **Analyze** and **History** only. Its source of truth is `apps/web/src/SessionGate.tsx`, `Workspace.tsx`, `AutomaticBox.tsx`, `ModelWorkbench.tsx`, and `workspace.css`; `main.tsx` selects this surface outside development. The native counterparts are `apps/mobile/lib/workspace.dart`, `automatic_box.dart`, and `theme.dart`. The retained `App.tsx` is the development simulator. Sections explicitly labeled **Legacy simulator** below describe that older surface and do not prescribe production navigation, density, geometry, or language behavior.

This is a refinement of the established paper, ink, amber, Georgia, and sans-serif identity. It makes one image, one action, and one result easy to follow. Thin rules, quiet controls, short instructions, and progressive detail replace the simulator's dense operational shell. The source-built candling symbol is decorative; image areas show the selected file or the latest camera-service preview without substituting decorative egg imagery.

The product name is exactly **EggGrade IoT** following the 2026-10-19 rename. The web wordmark pairs Georgia **EggGrade** with a small sans-serif **IoT** suffix and exposes **EggGrade IoT** as a single accessible image name. The rename preserves the existing cream, ink, amber, and teal identity.

Analyze defaults to **Automatic**, with **Attach photo** beside it. The automatic surface follows one placement, one saved research result, then removal before the next placement. Its camera connection, current instruction, and latest saved result remain distinct. Camera setup uses progressive disclosure, while manual attachment keeps its existing image, analyze, and result sequence. Both modes use the same History destination. This extends the Daylight Vendor Instrument and inherited seed `2df5ec83`; it introduces no replacement visual world or token palette.

**Key Characteristics:**

- Paper, ink, amber, restrained serif hierarchy, and a sans-serif operating layer.
- Automatic and manual image sources within the existing Analyze destination.
- One visible next action, with the latest saved result distinguished from the current camera view.
- Thin rules, quiet controls, short instructions, and progressive detail.
- Research status beside results and an appearance-only footer.

**The Next-Action Rule.** Show one clear next action. Keep supplementary image tips and saved-record metadata behind native disclosures. Account setup uses brief hints beside the relevant field.

**The Compact-Authority Rule.** Keep research status next to the result and the appearance-only limitation visible in the workspace footer. Compact wording must preserve the factual boundary.

**The Current-Step Rule.** In Automatic mode, present connection state, the current instruction, and the latest saved result as separate information. Keep the completed result above the camera preview on phones, and identify it as saved rather than implying that it classifies every subsequent preview.

Frontmatter retains shared tokens and the simulator's observed scales. The `workspace-*` tokens and the `control`/`upload` radii describe production refinements; `square`, the older heading scales, evidence-frame, and field-select remain simulator references. This documentation records the shipped implementation, not an approved visual comp or an accessibility/security certification.

### Legacy simulator

EggGrade IoT is an evidence-first operational workbench, not a marketing dashboard and not a food-safety verdict machine. The implemented thesis is explicit: eight stopped candling views lead, while every grade remains subordinate to provenance, quality gates, device readiness, and human review. The screen reads like a physical inspection bench in daylight—chalk-colored work surfaces, dark ink markings, warm candling amber, restrained teal, hard safety red, dense ruled ledgers, and no ornamental imagery.

The source direction is recorded in `apps/web/index.html` as **Daylight vendor instrument**, with assigned seed **`2df5ec83`**. That seed identifies the implemented visual direction; it is not an asset identifier, dataset reference, screenshot, or proof of an external design process. The current frontend uses React and TypeScript through Vite, hand-authored CSS, and `lucide-react`. It contains no bundled photography, candling raster imagery, webfont package, Tailwind theme, component framework, or external brand asset.

The information sequence is the visual hierarchy: persistent authority language, connection and interlock readiness, eight-view evidence, a fail-closed operational result, then the decision ledger, tallies, history, review, and synchronization context. Density is intentional, but the interface must remain inspectable rather than compressed into opaque status cards.

**Key Characteristics:**

- Evidence frames precede and visually outweigh the aggregate result.
- Source facts, model morphology, operational outcome, and human disposition remain separate.
- Paper-and-ink surfaces, square geometry, thin rules, and sparse tonal blocks create structure without decorative chrome.
- Synthetic, unavailable, blocked, and unvalidated states are named in visible text.
- Serif headlines provide editorial gravity; the sans-serif operating layer stays compact and numerical.
- Outcome color is semantic support, never the only carrier of meaning.

**The Evidence-Before-Grade Rule.** New screens must show the evidence and its authority before presenting a machine outcome as actionable information.

**The Authority-Is-Visible Rule.** Synthetic, shadow, blocked, pending, unvalidated, or missing evidence must remain visible near the affected control or result; never hide authority in a tooltip or metadata-only view.

## Colors

The shared palette applies to both surfaces. Production uses ink on paper, an amber active-navigation rule, teal technical readiness, and violet recapture. Day 16 result text uses a darker amber (`#96550e`) for readable emphasis. `workspace-focus` is the production focus outline; the older `focus` token belongs to simulator controls. The eight-view and operational-outcome mappings below apply where those legacy concepts are rendered; the upload workflow instead shows research class estimates or an unclassified recapture request.

The normative palette is defined in the frontmatter and mirrors the reusable CSS custom properties. It combines warm daylight neutrals with dark green-black ink, candling amber, restrained evidence teal, safety red, and a distinct review violet.

### Primary

- **Ink** (`colors.ink`) is the app shell, primary action, heavy rule, and highest-emphasis text. It establishes instrument authority without using pure black.
- **Paper** (`colors.paper`) is the principal work surface. **Paper Deep** (`colors.paper-deep`) separates the browser surround, empty surfaces, and lower-emphasis material without shadow.

### Secondary

- **Candling Amber** (`colors.amber`) marks Day 16-like probability and outcomes, the active navigation rule, scan activity, and caution-oriented highlights. **Amber Soft** is reserved for lower-emphasis supporting treatments.
- **Evidence Teal** (`colors.teal`) marks Day 18-like probability and outcomes, valid-frame state, and horizontal evidence affordances. **Teal Soft** is the supporting tint.

### Tertiary

- **Safety Red** (`colors.red`) marks reject-suspect, blocked readiness, hardware/model failures, and gates that are not satisfied. **Red Soft** is the supporting tint.
- **Review Violet** (`colors.violet`) is reserved for review/recapture. It keeps abstention visually distinct from reject-suspect.

### Neutral

- **Muted** (`colors.muted`) carries descriptions, metadata, labels, and secondary operational copy.
- **Rule** (`colors.rule`) creates the ledger system: dividers, frame boundaries, table rows, and field borders.
- **Focus** (`colors.focus`) is the visible keyboard focus outline and must remain distinct from outcome colors.

### Semantic color constraints

| Meaning | Color role | Required companion signal |
| --- | --- | --- |
| Day 16-like | Candling Amber | `Day 16-like` or `D16` text and a numeric value where applicable |
| Day 18-like | Evidence Teal | `Day 18-like` or `D18` text and a numeric value where applicable |
| Reject-suspect | Safety Red | `Suspect—segregate for review` or equivalent review instruction |
| Review/recapture | Review Violet | Explicit `Review / recapture` wording |
| Blocked or not satisfied | Safety Red | A named missing prerequisite or blocked state |
| Valid view | Evidence Teal | Check icon plus quality text |
| Invalid view | Neutral/dark invalid surface | X icon plus quality flag or `not captured` text |

**The No-Safety-Green Rule.** Teal may identify Day 18-like morphology or a valid technical check, but it must never mean safe to eat, approved for sale, pathogen-free, or regulator-approved. No green-family color may imply food safety.

**The Four-Outcome Rule.** Do not collapse reject-suspect and review/recapture into one red error state. Red means segregation/review is suspected; violet means the system abstained and needs review or recapture.

**The Never-Color-Alone Rule.** Every colored status also needs readable wording, an icon or geometry change, and—when quantitative—a number.

## Typography

### Current production workspace

Production keeps Georgia for the brand, welcoming login copy, page headings, and result titles. Sans-serif text carries instructions, fields, navigation, and metadata. Page headings use `typography.workspace-heading`; login and page headings share regular weight and restrained negative tracking. Automatic instructions retain regular serif hierarchy, while “Latest saved result” is a quiet sentence-case status label. Short sentences and generous separation establish hierarchy without adding uppercase labels. Android carries the serif voice with bundled Libre Caslon Text and a 34/28/23dp headline ramp; native body text retains system scaling. Existing Georgia is an identity constraint, not a recommendation to select system display faces for unrelated products.

### Shared identity and legacy simulator scales

**Display Font:** Georgia, falling back to Times New Roman and the platform serif.

**Body Font:** Aptos, falling back to Segoe UI, Arial, and the platform sans-serif.

**Character:** The serif layer gives the workbench a calm, editorial seriousness without pretending to be a laboratory certificate. The sans-serif layer behaves like an operator instrument: compact, legible, and neutral. Tabular numerals stabilize angles, probabilities, confidence, counts, and gate metrics.

### Hierarchy

- **Display** (`typography.display`): the workbench thesis on the overview. Keep it concise, with the existing approximately 680px line measure.
- **Headline** (`typography.headline`): page-level headings for history, review, devices, models, analytics, users, and audit views.
- **Title** (`typography.title`): section headings and role titles. Compact section variants may reduce to 20px while preserving the serif family and medium weight.
- **Body** (`typography.body`): operational explanations and prose. Prominent supporting copy uses 17px at 1.55 line-height on wide screens and 15px at 1.42 on mobile; routine descriptions are generally 12–15px.
- **Label** (`typography.label`): uppercase authority labels, result labels, table headings, and gate states. Use sparingly; it is a scanning layer, not a paragraph style.
- **Metrics:** use the body family with tabular numerals and strong weight. Existing key sizes range from 19px for measurements to 27–31px for view and tally counts.

**The Two-Layer Type Rule.** Serif is for hierarchy and interpretation; sans-serif is for operation, evidence, metadata, controls, and numbers.

**The Numeric Stability Rule.** Angles, percentages, confidence, counts, and view totals use tabular numerals so updates do not make the layout jump.

**The Plain-Language Rule.** Typography must not elevate `REJECT_SUSPECT` into a definitive hazard claim. Prefer the implemented operator label, “Suspect—segregate for review.”

## Layout

### Current production workspace

The desktop login pairs a dark brand panel with a paper form panel. The authenticated surface uses a top header, two named destinations, and a centered main area (1320px maximum). The manual analysis area pairs image upload with a result column, separated by one vertical rule. Automatic places its image-source choice above a ruled connection row, then pairs the camera preview with the current instruction and latest saved result in equal columns. Box setup sits below this working area. History uses ruled disclosure rows rather than a dashboard grid.

The native Android workspace carries this identity through Material 3 roles in `apps/mobile/lib/theme.dart`. It bundles Libre Caslon Text for the serif voice rather than redistributing Georgia. Native fields, the system image picker, at least 48dp controls, scrollable forms, keyboard insets, and system dark mode preserve Android behavior. Compact screens use two Analyze/History segments; expanded screens use a navigation rail and image/result columns. Login uses a compact forest brand strip on phones and a split composition at 900dp. Supporting connection settings remain outside the main task navigation. Body text follows system scaling; the wordmark scales down only if necessary to fit.

At 1000px and below, margins and column gaps tighten. At 700px and below, the login keeps a compact brand strip, navigation moves to a full-width header row, and image/result columns stack. Automatic places the current instruction and saved result before the camera preview and scrolls that region into view when a result arrives in the active mode. Manual completion also moves focus to its result panel. The native automatic layout uses equal columns at 760dp of available content width and above, with a 40dp gap and 1160dp maximum; below that width, it places the instruction and result first. A new automatic result scrolls the active native page to its top. History dates and record fields stack; long filenames and IDs wrap. Preserve the inherited 320px web minimum without introducing page-wide overflow.

The web workspace header reduces the main wordmark to 26px at widths of 700px and below; the login wordmark retains its existing scale. The six rename-review screenshots in `.impeccable/review/egggrade/` cover login and workspace at 1440px, 375px, and 320px. Their fixture-backed checks establish layout and naming only, with no page-wide overflow at those widths; they do not establish live authentication, camera or model behavior, or native visual acceptance.

### Legacy simulator

The default shell is a two-column workbench: a sticky 232px navigation rail and a flexible main surface with 34px horizontal padding and 72px bottom breathing room. The main surface has no fixed maximum width; evidence should use the available field-laptop space. Horizontal and vertical rules organize content more often than independent cards.

The overview deliberately alternates asymmetrical grids:

- Hero copy and readiness ledger use an approximately 1.25fr/0.75fr split with a 58px gap.
- The eight evidence frames occupy one horizontally scrollable strip, each at least 104px wide with 7px gaps.
- Scenario selection, the synthetic-run action, and its authority note form a three-part control deck.
- Result and decision ledger use an approximately 1.2fr/0.8fr split.
- Tally and recent inspections use an approximately 0.7fr/1.3fr split.

The spacing vocabulary in frontmatter records the most reusable observed increments. Larger section spacing is intentionally editorial rather than a perfectly mathematical scale: 31–46px separates major evidence bands, while 7–18px handles dense local relationships. Preserve this contrast between generous sections and compact data rows.

### Responsive behavior

- **Above 1050px:** full 232px sidebar with brand copy, text navigation, authority stamp, and locale label.
- **1050px and below:** the sidebar contracts to 80px and becomes icon-led; hero content becomes one column; the control deck becomes two columns with its authority note spanning the row.
- **760px and below:** the shell becomes a sticky top navigation bar. Main horizontal padding reduces to 17px. Hero, decision band, lower workbench, ledgers, role matrix, and gate sequence become single-column. The evidence strip keeps all eight frames in one horizontal row at 124px each and adds a visible “Swipe to inspect all 8 views” cue. The scenario control and synthetic-run action move before the frame strip, and the action becomes full width.
- **320px minimum:** the root declares a 320px minimum width. New screens must avoid introducing a higher structural minimum; wide data tables should use an intentional horizontal scroll wrapper, as the existing inspection table does.

### Navigation behavior

Desktop and compact-tablet navigation expose all nine destinations: Workbench, Inspections, Human review, Batches & eggs, Device health, Model releases, Analytics, Users & roles, and Audit trail. The active destination uses a warm amber rule plus a darker ink surface and `aria-current="page"`.

On mobile, exactly four primary destinations remain in the top bar: **Workbench, Inspections, Human review, and Device health**. **More** opens a fixed menu containing **Batches & eggs, Model releases, Analytics, Users & roles, and Audit trail**. Selecting any destination closes the menu. Preserve `aria-expanded`, `aria-controls`, the menu/menuitem roles, and `aria-current` when extending this pattern. The language control remains at the trailing edge of the top bar; the shadow-mode authority stamp is hidden there only because the full synthetic authority banner remains in main content.

**The Four-Plus-More Rule.** Do not squeeze all nine destinations into the mobile top bar or silently drop secondary destinations. Keep the implemented four primary views and the labeled More menu.

**The Evidence-Stays-Sequential Rule.** On narrow screens, allow horizontal inspection of all eight views; do not wrap them into an order that obscures the angle sequence.

## Elevation & Depth

Production retains flat paper/ink surfaces, thin rules, and no shadow vocabulary. Buttons change color over 160ms; the upload area changes background/border over 150ms. Loading spins communicate actual waiting. Reduced-motion rules disable workspace transitions and inherit the global animation reduction. The scan sweep, sticky rail, and More menu described below are simulator-only.

This is a flat-by-default system with no `box-shadow` vocabulary. Depth comes from tonal contrast, 1px rules, occasional 3px ink rules, dark instrument plates, and nested paper values. The sticky rail/top bar and fixed mobile More menu rely on position and `z-index`, not shadow. New work should preserve this material honesty.

Motion is limited to a linear loading spin and an alternating scan sweep. The scan sweep is an activity cue over the evidence strip; it is not a claim that a camera is operating. The global reduced-motion query collapses animations to a near-instant single iteration and disables smooth scrolling.

**The Flat-Instrument Rule.** Do not add generic floating-card shadows, glass blur, gradients, or elevated dashboard tiles. Use rules and tonal layers first.

**The Motion-Must-Declare-Activity Rule.** Motion may show waiting, refreshing, or synthetic evidence generation; it must never imply physical capture, motion, illumination, or inference that is not actually occurring.

## Shapes

### Current production workspace

Production softens functional controls with `rounded.control` and the upload area with `rounded.upload`, while keeping the surrounding page ruled and flat. These purposeful refinements supersede the simulator's universal square-control rule. Primary controls have at least 44px height; login fields and submission actions are larger. Small circular step numbers and status dots support text. They do not establish pill cards or pill navigation as a pattern.

Automatic uses the same small-corner controls for its mode choice and camera setup. The contained camera image sits inside a quiet ruled frame with 6px corners on the web and 6dp corners on Android. Preserve the image's proportions; the preview is evidence content, not a background treatment. This frame does not establish a general card system.

### Legacy simulator

The form language is square, ruled, and workbench-like. Controls, frames, banners, marks, menus, data plates, tables, and content containers use zero-radius corners. The brand mark is a 39px outlined square on desktop and a 38px square on mobile. Primary interactive targets are generally at least 44px high or wide. Probability bars are thin rectangular tracks; status markers are compact squares or vertical bars.

Borders are structural rather than decorative: 1px neutral rules partition evidence and ledgers, while 1–3px ink rules terminate major sections. A dark plate may identify an instrument/device region, but it should not become a rounded “card.”

**The Square-Bench Rule.** Preserve zero-radius geometry unless a real input or device constraint requires another shape. Do not introduce pill chips as a default status pattern.

**The Rules-Before-Boxes Rule.** Prefer shared horizontal rules and split ledgers to a collection of individually bordered cards.

## Components

### Current production workspace

- **Account access:** web sign-in always shows “New here? Sign up.” Create-account mode uses username, password, and confirmation, stays open after a duplicate-username error, and offers a return to sign-in. Preserve password visibility, brief field hints, inline errors, pending submission, and copy explaining that each account has private inspection history. The session check chooses first-run creation, sign-in, or the workspace; visual polish alone makes no authentication-security claim.
- **Image source:** Automatic is selected initially; Attach photo remains immediately available beside it. Web mode buttons expose pressed state and use ink/paper for the selected mode. Android uses a native segmented control. These are modes within Analyze, not additional primary destinations.
- **Automatic camera and instruction:** keep the connection row, current instruction, camera preview, and latest saved result legible as separate facts. Show one short next step for connection, empty reference, placement, steady capture, removal, recapture, pause, or interruption. The latest saved result retains its research label; a recapture remains unclassified. Web status uses a polite atomic live region; native state copy uses a live-region semantic container. Loading motion appears during analysis, not as continuous camera decoration.
- **Box setup:** keep camera address, Connect camera, explicit empty-box confirmation, and Save empty view & start together. Setup is exposed until the empty reference is established, then becomes a secondary disclosure. Pause/Resume remains beside connection status once calibrated. Retain the visible fixed-camera/lighting instruction and the statement that scene change is not an egg-presence sensor. Document the displayed interaction without implying hardware validation.
- **Upload and result:** a keyboard-accessible file picker and drag area accept one JPEG, with a preview and change/remove controls. The primary action waits for an image and model availability. Loading, connection failure, class estimate, and recapture are explicit states. The result is a polite live region; mobile completion moves focus to its panel.
- **Recapture and authority:** show the first actionable image tip immediately. Additional reasons stay in “More image tips.” A recapture assigns no class and requires another image. Research status stays beside the result; “Appearance only · Not a food-safety assessment” stays visible in the footer. Saved-record identifiers are optional detail.
- **History and navigation:** only Analyze and History are primary destinations. Automatic and manual captures share the saved-record history. History shows up to 50 recent records, with expandable identifiers, model, and result type. Provide distinct loading, failure/retry, and empty states. Switching views preserves the analysis component's state.
- **Language and accessibility:** main operator copy supports English and Filipino, and the active view updates document language. Some service errors, accessible labels, result labels, and page titles remain English; this is not complete localization. Keep the skip link, native disclosures, visible focus, text-supported status colors, and reduced-motion behavior. Production focus uses a 3px outline with 4px offset.

### Legacy simulator components

The remaining component subsections describe `App.tsx` and its simulator behavior. In particular, its synthetic authority banner, nine destinations, four-plus-More mobile navigation, and limited Filipino preview are not the production workspace contract.

### Authority banner and stamp

The authority banner is persistent main-content provenance: an amber-outlined warm paper strip with a bold uppercase authority label and plain-language limitation. In this build it states **SYNTHETIC DEMONSTRATION** and explicitly says that no physical egg images, trained CNN, or validated hardware result is present. The sidebar stamp reinforces **Shadow mode / No food-safety claim** on non-mobile layouts. Preserve this wording hierarchy wherever synthetic records are displayed.

Authority copy must describe what actually happened. The synthetic-run control creates deterministic probability vectors; its adjacent note explicitly says it does not start motion, lighting, a camera, or a CNN. Never shorten that to “Scan” without the synthetic qualifier and nearby limitation.

### Evidence frame

An evidence frame is an `article` with four inspectable layers:

1. A 4:3 evidence area showing the ordered view number and target holder angle.
2. A visible authority label: currently `SYNTHETIC FRAME` or `NO IMAGE`; no external candling image is bundled.
3. Three per-view probability rows—D16, D18, and REJ—with a colored bar and numeric integer value.
4. A validity row with check/X icon plus the first quality flag, `quality pass`, or `not captured`.

The aggregation-only review/recapture outcome is not a fourth per-frame CNN probability bar. It emerges from evidence quality and decision gates. Invalid frames use a neutral dark surface and explicit failure text; valid frames use teal text plus a check.

### Probability rows

Probability tracks are 4px high with a neutral base. D16 uses amber, D18 uses teal, and REJ uses red. Labels occupy a stable left column, bars flex, and integer values align in a tabular right column. Keep all three rows visible so contributors cannot visually cherry-pick the winning class.

### Operational result and decision ledger

The result is a large status region with `role="status"`, polite live announcement, and atomic updates. It includes an explicit outcome label, explanation, aggregate confidence, class margin, and view agreement. Semantic headline color follows the four-outcome mapping, but the full outcome wording always remains visible.

The adjacent decision ledger preserves the facts that qualify the outcome: recorded age, decision authority, model release, quality-gate version, and machine flags. Do not merge this ledger into the result prose or replace missing values with reassuring placeholders.

### Readiness and gate rows

Readiness rows combine a colored square, a named prerequisite, and a textual value such as `Not connected` or `No validated release`. Release gates show sequence number, gate title, and visible `Not satisfied` status. Teal “good” treatment is allowed only for a demonstrated technical state, never for food safety.

### Buttons and fields

- **Primary action:** a square 44px-high ink button with white type, compact horizontal padding, icon plus label, and a darker ink hover. Disabled synthetic generation uses reduced opacity and a wait cursor.
- **Icon button:** a minimum 44×44px ruled square with an accessible label; hover changes the paper tone to white.
- **Text action:** borderless, bold, icon-assisted, and used inside tables or rows—not as the principal page action.
- **Select field:** a 42px-high square white field with a neutral rule and visible label.
- **Focus:** buttons and selects use the dedicated 3px focus outline with 2px offset. New interactive controls must receive an equivalent visible `:focus-visible` treatment.

### Lists, tables, and empty states

Inspection and queue rows are full-width rule-separated buttons. Outcome is carried by text and, where used, a vertical marker. Wide inspection tables declare an 850px internal minimum and scroll inside `.table-wrap` rather than forcing the page wider. Empty states use a Lucide icon, an explicit title, and evidence-honest explanatory copy; they never fabricate sample records to make the interface look populated.

### Navigation and icons

The only implemented icon library is `lucide-react`. Icons are simple line symbols, generally 14–34px, and support labels rather than replacing meaning. Decorative icons are marked `aria-hidden` where the surrounding text supplies the name. Icon-only controls require an `aria-label`; nav buttons retain text in the DOM and a `title`. Do not introduce emoji, icon fonts, or mixed illustration styles as status language.

### Accessibility and live behavior

- The connection notice is an `aria-live="polite"` sentence.
- The operational result is polite, atomic live status.
- Primary navigation exposes its accessible name and current page.
- The language control exposes pressed state and names the limited preview/return action.
- The analytics plot exposes a text alternative through `role="img"` and `aria-label`.
- Focus is visually explicit; primary/icon navigation targets reach approximately 44px.
- Reduced-motion preferences suppress ongoing spin and scan animations.
- Statuses pair color with text, icons, labels, geometry, or numbers.

These are implemented behaviors, not a claim of a completed accessibility audit. When adding menu interactions, retain the existing semantics and consider explicit focus placement, Escape handling, and return focus rather than assuming `role="menu"` provides those behaviors automatically.

### Language scope

Filipino is currently a **limited preview**, not full localization. The toggle changes only the overview evidence thesis, supporting subtitle, synthetic-run button label, and recent-inspections heading. Most navigation, authority language, readiness, evidence details, outcomes, tables, empty states, and secondary pages remain English, and the document-level `<html lang="en">` value does not change. Contributors must not describe the current build as fully bilingual or localized. Full Filipino support requires complete message coverage, terminology review, locale-aware document language, layout testing for translated strings, and equivalent accessibility labels.

## Do's and Don'ts

### Current production workspace

- **Do** preserve the paper/ink/amber identity, short instructions, restrained serif hierarchy, and flat ruled surfaces.
- **Do** keep the next action obvious and supplementary details collapsed until needed.
- **Do** keep Analyze and History as the essential production destinations and bring a newly returned result into view on mobile.
- **Do** retain Automatic and Attach photo together, the explicit empty-view confirmation, and a visible next action for the current camera state.
- **Do** distinguish the latest saved result from the current preview and keep the result before the preview on phones.
- **Don't** reintroduce the simulator's navigation, dense gate ledgers, or square-only controls into production by following the historical sections below.
- **Don't** turn an appearance estimate, polished login, UI review, or local software check into a food-safety, security-audit, or physical-readiness claim.
- **Don't** turn fixture-fed camera previews into physical-camera evidence or describe scene-change capture as a validated egg-presence sensor.

### Legacy simulator guardrails

The following lists retain historical simulator guidance. Shared evidence-honesty and accessibility principles still apply; simulator-specific layout, geometry, language scope, and navigation do not override the current production rules above.

### Do:

- **Do** place evidence, validity, view coverage, authority, and quality gates before an aggregate grade.
- **Do** preserve the visible distinctions among chronological source facts, morphology, machine result, evidence authority, and reviewer disposition.
- **Do** label every simulated record and synthetic frame in the immediate visual context.
- **Do** keep reject-suspect wording operational: segregate and review; it is not a confirmed rotten, unsafe, disposable, or unsellable determination.
- **Do** use the implemented four-outcome color mapping with text, icons, and numbers.
- **Do** preserve square geometry, ruled ledgers, paper/ink tonal layering, and horizontal scrolling for ordered evidence and wide tables.
- **Do** keep mobile navigation to the implemented Workbench, Inspections, Human review, and Device health primary set plus More for all remaining destinations.
- **Do** use Lucide line icons consistently and give every icon-only action an accessible name.
- **Do** respect reduced-motion and keep dynamic service/result notices in appropriate live regions.
- **Do** describe Filipino as a limited preview until message coverage and document-language behavior are actually complete.

### Don't:

- **Don't** use green or teal to assert food safety, marketability, regulatory approval, model correctness, or freedom from pathogens.
- **Don't** present `REJECT_SUSPECT` as a confirmed rotten/unsafe class, or collapse it with `REVIEW_RECAPTURE`.
- **Don't** hide missing hardware, models, images, gates, or reviewer evidence behind polished empty cards or optimistic placeholder data.
- **Don't** imply that the synthetic-run animation represents a camera, CNN, motor, illumination, or physical inspection.
- **Don't** add external egg imagery, screenshots, logos, font files, or raster assets unless they are deliberately introduced with source, license, and authority provenance. None are part of the current visual implementation.
- **Don't** invent a Tailwind, Material, or third-party component system; the current visual source of truth is the hand-authored CSS and React structure.
- **Don't** add generic shadows, gradients, glass effects, rounded-card grids, pill-status clutter, or decorative charts that weaken the ruled evidence-workbench hierarchy.
- **Don't** communicate state through color alone or remove the focus outline to achieve a cleaner screenshot.
- **Don't** squeeze secondary destinations into the mobile bar, remove the More path, or reorder the eight-view sequence into an ambiguous wrap.
- **Don't** claim full Filipino localization, an accessibility certification, user validation, real candling imagery, or physical-device readiness from this frontend.
