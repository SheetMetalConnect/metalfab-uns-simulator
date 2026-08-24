# Changelog

All notable changes to the MetalFab UNS Simulator. Format follows
[Keep a Changelog](https://keepachangelog.com/); the project uses simple 0.x
versioning. `src/metalfab_uns_sim/__init__.py` holds the version and
`pyproject.toml` reads it from there; git tags mark releases (`git tag v0.1.1`).
The git history is the source of truth for detail.

## [0.1.1] - 2026-08-24

### Fixed
- **A disconnected simulator no longer looks healthy.** `MQTTClient._do_publish`
  had no branch for "client missing or not connected": the message vanished, the
  dropped counter stayed at 0 and the status topic kept reporting a clean run.
  Those messages are now counted as dropped and logged at WARNING.
- **The multi-site publisher checks the broker's answer.** paho returns
  `MQTT_ERR_NO_CONN` rather than raising, and `SemanticPublisher.publish` threw
  the result away, so every `publish_*` method reported success while nothing
  reached the broker. Publishes are now counted through one chokepoint
  (`_record_publish`) that logs a WARNING on the healthy-to-failing transition
  and an INFO on recovery - once per transition, not once per message, because
  this path runs at tick rate.
- **`clear_retained` no longer reports topics it did not clear.** It logged
  "Cleared N retained topics" from a loop counter; it now subtracts the rejected
  publishes and warns when any were rejected.

### Changed
- **One place for the version.** `pyproject.toml` declares
  `dynamic = ["version"]` and reads `metalfab_uns_sim.__version__`, so the
  package version and the module version cannot drift apart.

### Added
- **Tests for the publish paths above** - three cases in
  `tests/test_mqtt_client.py` covering the disconnected drop, the
  warn-once-per-transition behaviour and the recovery log.
- **Environment variable table in the README** - broker, credentials, topic-tree
  levels and starting complexity level, with their defaults.

## [0.1.0]

Initial release: multi-site UNS simulator with ESPR digital product passport and
realistic OEE. Later commits on this version renamed the `_historian` data
contract to `_raw` to match UMH Core conventions and added
`_energy-monitor_v1`, added the OEE deep-dive dashboard, and exposed the
WebSocket port for the browser dashboards.
