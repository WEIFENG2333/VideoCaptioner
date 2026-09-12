# Custom UI Icons

Place app-owned SVG icons in this directory and load them through
`videocaptioner.ui.common.app_icons`.

Prefer 24x24 viewBox line icons for toolbar and navigation actions. Use
`FluentIcon` first when a standard icon already exists.

For app-owned icons:

- add the SVG here with a 24x24 `viewBox`;
- use `currentColor` for stroke/fill color;
- register the file name in `AppIcon`;
- render it with `render_svg_icon()` or apply it to buttons with
  `apply_button_icon()`.
