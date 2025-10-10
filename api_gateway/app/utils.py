from api_gateway.app.settings import GatewaySettings

GATEWAY_SETTINGS = GatewaySettings()


def cache_ttl(seconds: int) -> int:
    """Override `seconds` if global settings are for `no-cache`"""
    return 0 if GATEWAY_SETTINGS.disable_caching else seconds
