# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project mostly adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased](https://gitlab.heigit.org/climate-action/api-gateway/-/compare/2.3.2...main)

### Changed

- update `climatoology` to version 7.0.1

### Added

- `platform` functionality that was provided in `climatoology<=6.4.3` has been moved
  here ([#184](https://gitlab.heigit.org/climate-action/climatoology/-/issues/184)).
  The following elements have been moved and renamed:
    - `climatoology.app.platform.CacheOverrides`: `api_gateway.sender.CacheOverrides`
    - `climatoology.app.settings.SenderSettings`: `api_gateway.sender.SenderSettings`
    - `climatoology.app.platform.CeleryPlatform`: `api_gateway.sender.CelerySender`
- a `run-alembic.sh` script to easily run migrations against the backend database

## [2.3.2](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/2.3.1) - 2025-06-04

### Changed

- updated climatoology to 6.4.2 with new db schema
- test the endpoints using a deduplicated
  correlation_uuid ([31](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/31))

### Fixed

- added a temporary hack to prevent computations taken from the Q by the broker from showing up as pending indefinitely

### Added

- an env variable `DISABLE_CACHING` to optionally disable caching of all
  endpoints ([#22](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/22))

## [2.3.1](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/2.3.1) - 2025-05-13

### Changed

- all endpoints now end uniformly WITHOUT /
- return `ComputationInfo` from the `compuatation/medadata` endpoint instead of a redirect URL
- settings are now all grouped in settings.py under `GatewaySettings`

### Added

- added `computation_queue_time` and `computation_time_limit` as optional gateway settings
- caching to all endpoints that use any platform resource to prevent too many calls

## [2.3.0](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/2.3.0) - 2025-05-09

### Changed

- updated climatoology to version 6.4.0, which includes deduplicating computations
- Removed `plugin_version` from `get_icon_url()` which is no longer required (
  see [#155](https://gitlab.heigit.org/climate-action/climatoology/-/issues/155))
- Replaced `ComputationState` with the `CommandComputeStatus` from `climatoology`
- Response type from `/{correlation_uuid}/state` is now `ClimatoologyStateInfo`, which includes both the state and
  optionally (currently only for `ClimatoologyUserError` or `InputValidationError` results) a message (closes
  [#22](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/22))
- Restructured the repository to use multiple files separated by route
- Cache plugin info in `get_plugin` call as it is no longer a live probe of the plugin

### Added

- `{plugin_id}/demo` endpoint to compute an indefinitely cached demo artifact
- Basic test for all endpoints to be extended in the
  future ([#15](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/15))
- a plugin status call `{plugin_id}/status` that allows a health check for plugins
- Coverage and linting to CI

## [2.2.0](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/2.2.0)

### Deprecated

- the websocket endpoint is currently broken

### Changed

- update climatoology to version 6.0.0 that uses Celery as the underlying task management library
- made `aoi` a separate input parameter for compute requests

### Added

- `state` endpoint for computations ([#12](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/12))
- `store/{plugin_id}/icon` endpoint to retrieve the icon file from the assets storage

## [2.1.1](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/2.1.1) - 2024-09-17

### Changed

- `fetch`-endpoints now redirect to a pre-signed S3 url instead of providing a file
  response [#11](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/11)
- update climatoology to 5.2.0

### Fixed

- docker repository path can now be set through an env-var to allow migration to the internal docker repository

## [2.1.0](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/2.1.0) - 2024-06-13

### Changed

- swagger and redoc can now be disabled through a feature switch env-var `DISABLE_SWAGGER`. This is necessary to prevent
  external calls by the swagger website.
- dependency cleanup

### Added

- the openapi.json now exposes the api and the climatoology version
  automatically ([#8](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/8))

## [2.0.0](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/2.0.0) - 2024-06-10

### Changed

- update climatoology to 4.0.0

### Fixed

- the logical check for the existence of an artifact
- an issue where websockets were blocking all resources in the api rendering it a single user
  application ([#3](https://gitlab.heigit.org/climate-action/api-gateway/-/issues/3))

### Added

- licence GNU Affero GPL v3
- endpoint to retrieve computation metadata `/{correlation_uuid}/metadata/`

## [1.0.0](https://gitlab.heigit.org/climate-action/api-gateway/-/releases/1.0.0) - 2024-02-09

### Added

- extracting the API gateway from [climatoology](https://gitlab.heigit.org/climate-action/climatoology) where it was
  embedded until now