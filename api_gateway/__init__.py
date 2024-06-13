import importlib.metadata

from semver import Version

__version__: Version = Version.parse(importlib.metadata.version('api_gateway'))
