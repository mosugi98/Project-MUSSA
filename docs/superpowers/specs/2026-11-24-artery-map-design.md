# Coronary artery map: a realistic segment picker (design)

Date: 2026-11-24. Status: design approved in conversation, awaiting written-spec review.

## Goal

The scoring form picks SYNTAX segments on a stick-figure tree (`ui/segment_tree.py`). Add a second picker that
shows a realistic heart illustration with all 25 segments drawn on it as clickable, tapered vessels. It is
decision support for choosing segments faster and more intuitively. It changes no scoring rule.

## Non-goals

- No change to the scoring engine, the form questions, the stored data or the export format.
- No claim of clinical anatomical accuracy for the segments the picture cannot show (see "Position quality").
- No multi-view (posterior, lateral) artwork in this step.

## Artwork and licence

- Image: "202410 Coronary arteries anterior view" by DataBase Center for Life Science (DBCLS), licence
  CC BY 4.0 (https://creativecommons.org/licenses/by/4.0), credit/source https://doi.org/10.7875/togopic.2024.242,
  Wikimedia Commons file `File:202410 Coronary arteries anterior view.svg`.
- The project owner downloaded it as a 3840 x 3840 `.webp` raster (the browser preview, not the SVG). It is used
  as a raster backdrop, downscaled to about 1400 x 1400 px, kept as `src/cagsyntax/ui/assets/heart_anterior.webp`.
  The change from the original (rasterised, resized, vessels drawn over it) is stated in the credit.
- `src/cagsyntax/ui/assets/LICENSE-artwork.md` records title, author, licence, link, source, and the
  modifications. The app's About text carries one line: "Heart illustration: DBCLS, CC BY 4.0, modified".
- The other downloaded image (`Coronary_arteries.svg`, CC BY-SA 3.0) is NOT bundled: share-alike is outside the
  licences the owner accepted.

## Components

1. **`src/cagsyntax/ui/artery_map.py`, class `ArteryMap(QWidget)`.** Same public interface as `SegmentTree`:
   signal `selection_changed(list)`; `set_scoring_dominance`, `set_selected`, `selected`, `set_first_segment`,
   `first_segment`, `segment_at(x, y)` (coordinates in the map's own logical space). Same normalisation rules
   (`SEGMENT_IDS` order, only segments applicable to the dominance). The shared selection logic is moved out of
   `SegmentTree` into a small base class only if that keeps both files simpler; otherwise it is copied once and
   covered by the same tests. `SegmentTree` keeps its behaviour and its tests.
2. **Geometry data: `ARTERY_GEO`.** For each segment id: a cubic Bezier (4 control points) in normalised image
   coordinates (0 to 1, origin top-left of the picture), a start and end stroke width in picture-relative units
   for the taper, and a flag `visible_in_picture` (true where the path follows an artery drawn in the picture,
   false where it is placed schematically). Kept in one table so it can be reviewed and corrected without
   touching widget code.
3. **Scoring panel switch.** `ScoringPanel` holds both widgets in a `QStackedWidget` with a small two-state
   control "Diagram | Schematic". Both widgets are kept in sync through the same four calls the panel already
   makes (`scoring_panel.py` around lines 195 and 281-284). Default: Diagram. The choice is remembered for the
   session only.
4. **Assets and packaging.** `ui/assets/` is added as package data in `pyproject.toml`, and
   `tools/packaging/build_exe.py` is checked and updated so the built app contains the image and the licence file.

## Drawing and interaction

- The picture is scaled to fit the widget, aspect ratio kept, centred. All overlay geometry follows that scale.
- Each applicable segment is stroked as a tapered path in the app theme: idle colour from the palette, selected
  in `theme.primary`, as the current tree does. A number badge sits at the path midpoint (existing size rules:
  larger for ids longer than two characters). The first segment of an occlusion gets the accent ring.
- Segments with `visible_in_picture` false are drawn dashed, and a one-line legend under the map reads
  "Dashed: position is schematic (not visible from the front)".
- Segments that do not exist for the dominance are neither drawn nor clickable.
- Hit test: nearest path within a tolerance in widget pixels (default 12, as the tree uses 14 logical units),
  measured on the path sampled as a polyline. Clicking the badge also selects. Ties go to the nearest path, then
  to the earlier `SEGMENT_IDS` entry. Clicking empty picture does nothing.
- Selection toggles on click and emits `selection_changed` with the normalised list, exactly as the tree does.
- Minimum size 360 x 360. The widget is disabled (not hidden) when there is no current lesion, as now.

## Position quality (stated limits)

- A front view hides the circumflex, obtuse marginals, PDA, posterolateral branches and segments 12a/12b, 13, 14,
  15, 16, 16a to 16c. Their paths are placed on the heart where those arteries run, and marked dashed. They
  are a pointing aid, not an anatomical measurement.
- Paths for the visible RCA, LAD and diagonals are traced on the artwork and checked by rendering.
- The project owner reviews rendered images for left, right and co-dominant before the feature is accepted.
  Segment placement is corrected in `ARTERY_GEO` until the owner is satisfied.

## Error handling

- If the image file cannot be loaded, the map shows a message ("Diagram image missing") and the panel falls back
  to the Schematic view automatically, so scoring is never blocked.
- Unknown segment ids passed to `set_selected` are ignored, as in `SegmentTree`.

## Testing

- `tests/test_artery_map.py`: the same contract tests as `tests/test_segment_tree.py` (toggle select, deselect,
  dominance filtering, first segment cleared when deselected, `segment_at` for every segment midpoint, none for
  empty space, disabled-state behaviour).
- Table checks: every id in `SEGMENT_IDS` has an `ARTERY_GEO` entry; all coordinates lie within 0 to 1; widths are
  positive; no applicable segment's midpoint falls outside the picture.
- Panel test: the switch shows the right widget; a selection made on one is visible on the other; a missing image
  falls back to the Schematic.
- Render check (manual, run by Claude, reviewed by the owner): offscreen PNGs for right, left and co-dominant, with
  and without selections, in light and dark themes, at two window sizes.
- The existing suite (888 passing tests as of 2026-11-24) must stay green.

## Open items to settle during implementation, not design

- Exact Bezier control points and widths: found by tracing the artwork and iterating on the render check.
- Whether the shared selection logic is extracted or copied: decided when the first draft shows how much overlaps.
