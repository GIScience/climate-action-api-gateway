from typing import Optional, TypeVar

from fastapi import Query
from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.customization import CustomizedPage, UseCursorEncoding, UseParamsFields
from fastapi_pagination.types import Cursor

from api_gateway.app.settings import GatewaySettings

GATEWAY_SETTINGS = GatewaySettings()


def cache_ttl(seconds: int) -> int:
    """Override `seconds` if global settings are for `no-cache`"""
    return 0 if GATEWAY_SETTINGS.disable_caching else seconds


def cursor_raw_str_encoder(cp: CursorParams, c: Optional[Cursor]) -> Optional[str]:
    if isinstance(c, bytes):
        c = c.decode()
    return c


def cursor_raw_str_decoder(cp: CursorParams, s: Optional[str]) -> Optional[Cursor]:
    return s


T = TypeVar('T')

GatewayCursorPage = CustomizedPage[
    CursorPage[T],
    UseParamsFields(size=Query(50, ge=1, le=100, description='Page size', alias='page_size')),
    # The FE and various layers that the requests are channeled through can have issues with certain types of encoding.
    # Therefore we have chosen not to encode the cursor at all for now.
    # An alternative to the custom (non-)encoding would be to use an unquoted cursor: UseQuotedCursor(False)
    # but it ends with '=' which could be problematic somewhere along the line (e.g. when going via tyk)
    UseCursorEncoding(encoder=cursor_raw_str_encoder, decoder=cursor_raw_str_decoder),
]
