# High-DPI display support

This document describes the KiProd desktop GUI's high-DPI approach and the checks
needed before claiming support across operating systems and display configurations.

## Current implementation

The GUI uses PySide6 with Qt 6. Qt 6 scales widgets, text, and standard controls from
the operating system's device-pixel ratio. KiProd does not enable a second global
scale factor. Its initial window size is selected from the primary screen's available
logical geometry, capped at 1180 × 760 logical pixels, and accounts for the window's
minimum layout size when the screen allows. The AI usage indicator is in the status
bar, and the run controls use layouts so they can distribute available width.

The sizing helper has headless unit coverage. A Qt minimal-platform smoke run has
opened the GUI and exercised run workflows, but that backend does not reproduce a
normal desktop's fonts, screen geometry, or mixed-monitor behavior. Native interactive
acceptance remains necessary.

## Implementation rules

- Use Qt layouts, size policies, and stretch factors. Avoid fixed widget sizes unless
  a control has a real content constraint.
- Treat values from `QScreen.availableGeometry()` as logical pixels. Do not multiply
  them by `devicePixelRatio()`; Qt already applies the platform scale factor.
- Prefer system fonts and point-sized text. Avoid pixel-sized fonts and manually
  scaling font sizes.
- Keep buttons and labels concise so the run bar remains usable at smaller logical
  resolutions. Let progress and text areas take the remaining space.
- For raster icons or images, provide suitable high-resolution variants or set the
  image's device-pixel ratio. Prefer SVG icons when available.
- Make long tables, forms, and settings pages scrollable. Do not make a screen-sized
  window minimum that prevents the user from resizing it.
- When supporting multiple monitors, size and place the window using the screen it
  is currently on, not only the primary screen. Re-check geometry after moving the
  window between monitors with different scale factors.
- Do not add `QT_SCALE_FACTOR` or deprecated high-DPI application attributes as a
  product workaround without a demonstrated platform bug; either can double-scale
  Qt 6 widgets.

## Acceptance checklist

Run the GUI on Windows, macOS, and Linux with the packaged PySide6 version. Check at
least these logical scaling settings where the operating system supports them:

- 100%, 125%, 150%, and 200% scaling.
- A lower-resolution display such as 1366 × 768 at 150% scaling.
- A 4K display at 200% scaling.
- Two monitors with different scale factors; move the window between them.
- A non-default operating-system text size, then restart the application.

For each setup, confirm that:

- The window opens within the work area and remains resizable.
- Project and run controls do not overlap or disappear.
- Tab labels, table headers, buttons, status messages, and dialogs remain readable.
- The BOM, quote review, component settings, comparison, and advanced TOML views can
  be reached without clipped controls.
- Moving the window between monitors updates its scaling without blurry or oversized
  content.
- Screenshots and automated assertions use logical geometry rather than expecting a
  fixed physical-pixel size.

Record operating system version, display resolution, scale factor, Qt/PySide6 version,
and any visual defect with each acceptance result.
