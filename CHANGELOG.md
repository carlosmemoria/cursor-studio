# Changelog

## 0.2.0 — 2026-10-15

Add single-instance GUI activation with local file forwarding and crash recovery. Generate optional 24–128 px Xcursor sizes with smooth or pixel-art scaling and scaled hotspots. Confirm replacement of existing themes, keep the previous complete version as a backup, and roll back failed publication. Add CLI size/replacement options and regression tests.

## 0.1.1 — 2026-10-15

Fix dialog contrast on light KDE desktops. Register per-theme compatibility links in `~/.icons` so libXcursor builds with legacy search paths discover XDG-installed themes. Recognize standard Windows scheme filenames and offer explicit cursor-role transfers. Add Breeze/Adwaita fallbacks and regression tests. Existing themes are never overwritten.

## 0.1.0 — 2026-10-15

Initial beta: native Qt 6 interface, static CUR PNG/DIB decoding, multiple resolutions, hotspot preview, role mapping, Xcursor theme export, per-user installation, CLI, desktop launcher, and automated tests.
