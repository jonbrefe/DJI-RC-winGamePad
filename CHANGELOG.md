# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Virtual Xbox gamepad backend (`--backend vgamepad`, now the default) so the sticks
  become real analog axes for drone/FPV sims; left dial mapped to the triggers.
- Reusable `djirc` package: `protocol` (DUML framing, checksums, decoding, `Controller`),
  `reader` (auto-reconnecting poll thread), and `gui` (skeuomorphic Tk view).
- Battery percentage decoding and display.
- Button and flight-mode decoding (`0x27` packet) mapped to gamepad buttons / keys.
- Skeuomorphic controller GUI in `test_control.py` plus console protocol explorers
  (`--discover`, `--sweep`, `--watch`, `--diff`).
- `DRIVER_INSTALL.md`: install just the USB VCOM driver without the full DJI Assistant 2,
  including a licensing note.
- Packaging (`pyproject.toml`) with `djirc-run` / `djirc-test` console scripts and
  backend extras; offline `pytest` suite; `ruff` config; GitHub Actions CI; `.gitignore`.

### Changed
- Default input backend is now `vgamepad` (was `directinput`).
- Standardized project text in English and expanded backend selection guidance.

### Fixed
- Stop injecting stale input after serial read timeouts / disconnects; release held keys
  on shutdown.
- Stick knob no longer leaves its ring (magnitude clamp instead of per-axis clamp).

## [0.1.0]

- Initial fork: validate serial packets, explicit `--port` selection, safer shutdown.
