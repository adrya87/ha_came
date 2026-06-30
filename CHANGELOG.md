# Changelog

All notable changes to this project are documented here.

This project follows semantic versioning where practical:

- MAJOR: breaking configuration or entity behavior changes
- MINOR: new supported CAME API features or Home Assistant platform capabilities
- PATCH: bug fixes, compatibility fixes, and internal maintenance

## [1.1.0] - 2026-06-30

### Fixed

- Aligned CAME API command handling for lights, openings, relays, energy meters, scenarios, and thermoregulation.
- Fixed invalid manually assigned Home Assistant entity IDs.
- Fixed digital input binary sensor state mapping for CAME active-low inputs.
- Fixed integration unload handling for listener thread, energy polling task, services, and dispatcher listeners.
- Added HTTP request timeout handling to avoid stuck API calls.
- Removed external `pycame` requirement from the manifest because the client is bundled in the integration.

### Changed

- Improved thermoregulation handling for plant season, zone configuration, dehumidifier mode, and humidity target.
- Made device state updates merge partial CAME status updates instead of replacing all cached device metadata.
- Made list response parsing tolerant of documented and legacy response field names.
- Registered scenario create/delete services declared in `services.yaml`.

## [1.0.1] - Previous

- Baseline version before the 1.1.0 API alignment and Home Assistant compatibility fixes.
