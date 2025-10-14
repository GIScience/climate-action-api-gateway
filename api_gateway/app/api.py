import logging.config
from contextlib import asynccontextmanager

import climatoology
import uvicorn
import yaml
from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

import api_gateway
from api_gateway.app.route import computation, health, metadata, plugin, store
from api_gateway.app.settings import GatewaySettings
from api_gateway.sender import CelerySender

settings = GatewaySettings()

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
    the_app.state.settings = settings
    the_app.state.platform = CelerySender()
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
    docs_url=None if settings.disable_swagger else '/docs',
    redoc_url=None if settings.disable_swagger else '/redoc',
)


app.include_router(health.router)
app.include_router(metadata.router)
app.include_router(plugin.router)
app.include_router(computation.router)
app.include_router(store.router)


if __name__ == '__main__':
    log_config = settings.app_config_dir / 'logging/app/logging.yaml'
    logging.basicConfig(level=settings.log_level.upper())
    with open(log_config) as file:
        logging.config.dictConfig(yaml.safe_load(file))
    log.info('Starting API-gateway')

    uvicorn.run(
        app,
        host='0.0.0.0',
        port=settings.port,
        root_path=settings.root_path,
        log_config=str(log_config),
        log_level=settings.log_level.lower(),
    )
