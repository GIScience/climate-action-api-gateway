import logging.config
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

import climatoology
import uvicorn
import yaml
from climatoology.app.platform import CeleryPlatform
from fastapi import FastAPI, Request
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette.middleware.base import _StreamingResponse

import api_gateway
from api_gateway.app.route import computation, health, metadata, plugin, store

config_dir = os.getenv('API_GATEWAY_APP_CONFIG_DIR', str(Path('conf').absolute()))

log_level = os.getenv('LOG_LEVEL', 'INFO')
log_config = f'{config_dir}/logging/app/logging.yaml'
log = logging.getLogger(__name__)


tags_metadata = [
    {
        'name': 'plugin',
        'description': 'Interact with plugins.',
    },
    {
        'name': 'computation',
        'description': 'Inquire about currently running computations.'
        'This endpoint implements a WebSocket.'
        'It has one optional parameter (correlation_uuid) that is used to filter updates by.'
        'The WebSocket will push updates in json format on the status of currently running computations.'
        'Be aware that you will only be sent future updates. Any historic states are lost.'
        'If you need the full set of states, make sure to subscribe to all notifications '
        'and then filter on your side.',
    },
    {
        'name': 'store',
        'description': 'Interact with the content store.',
    },
]

description = """
# Climate Action API Gateway

The API Gateway to the HeiGIT Climate Action platform abstracts all functionally for the user realm.
It servers as the single point of interaction.
"""


@asynccontextmanager
async def configure_dependencies(the_app: FastAPI):
    log.debug('Configuring Platform connection')
    the_app.state.platform = CeleryPlatform()
    FastAPICache.init(InMemoryBackend())
    log.debug('Platform configured')
    yield


app = FastAPI(
    title='Climate Action API Gateway',
    summary='Interact with the stateful Climate Action platform.',
    description=description,
    version=f'{str(api_gateway.__version__)}/{climatoology.__version__}',
    contact={
        'name': 'Climate Acton Team',
        'url': 'https://heigit.org/climate-action',
        'email': 'info@heigit.org',
    },
    openapi_tags=tags_metadata,
    lifespan=configure_dependencies,
    docs_url=None if os.getenv('DISABLE_SWAGGER', 'False') in ('True', 'true') else '/docs',
    redoc_url=None if os.getenv('DISABLE_SWAGGER', 'False') in ('True', 'true') else '/redoc',
)


@app.middleware('http')
async def remove_cache_control_header(request: Request, call_next: Callable) -> _StreamingResponse:
    """Remove the 'Cache-Control' header from the responses so the browser doesn't also cache the responses.

    By doing this, any cached results are cleared when this API is restarted. This allows us to force refresh the cache
    by simply restarting this API. We may want to do this to force the indefinitely cached `'/{plugin_id}/demo'`
    endpoint to be recreated (for example when we release updated plugins).

    This is temporary until we do idempotency & caching
    properly: https://gitlab.heigit.org/climate-action/climatoology/-/issues/110
    """
    response = await call_next(request)
    response.headers.update({'Cache-Control': 'no-cache'})
    return response


app.include_router(health.router)
app.include_router(metadata.router)
app.include_router(plugin.router)
app.include_router(computation.router)
app.include_router(store.router)


if __name__ == '__main__':
    logging.basicConfig(level=log_level.upper())
    with open(log_config) as file:
        logging.config.dictConfig(yaml.safe_load(file))
    log.info('Starting API-gateway')

    uvicorn.run(
        app,
        host='0.0.0.0',
        port=int(os.getenv('API_GATEWAY_API_PORT', 8000)),
        root_path=os.getenv('ROOT_PATH', '/'),
        log_config=log_config,
        log_level=log_level.lower(),
    )
