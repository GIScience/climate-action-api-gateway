import logging.config
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import List
from uuid import UUID

import geojson_pydantic
import uvicorn
import yaml
from cache import AsyncTTL
from celery.result import AsyncResult
from fastapi import APIRouter, FastAPI, WebSocket, HTTPException
from starlette.responses import RedirectResponse

import api_gateway
import climatoology
from climatoology.app.platform import CeleryPlatform
from climatoology.base.artifact import _Artifact
from climatoology.base.baseoperator import _Info, AoiProperties
from climatoology.base.info import Concern
from climatoology.store.object_store import COMPUTATION_INFO_FILENAME
from climatoology.utility.exception import InfoNotReceivedException, ClimatoologyVersionMismatchException

config_dir = os.getenv('API_GATEWAY_APP_CONFIG_DIR', str(Path('conf').absolute()))

log_level = os.getenv('LOG_LEVEL', 'INFO')
log_config = f'{config_dir}/logging/app/logging.yaml'
log = logging.getLogger(__name__)


class ComputationState(StrEnum):
    PENDING = 'PENDING'
    STARTED = 'STARTED'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'
    RETRY = 'RETRY'
    REVOKED = 'REVOKED'


@dataclass
class CorrelationIdObject:
    correlation_uuid: UUID


@dataclass
class Concerns:
    items: set[str]


@asynccontextmanager
async def configure_dependencies(app: FastAPI):
    log.debug('Configuring Platform connection')
    app.state.platform = CeleryPlatform()
    log.debug('Platform configured')
    yield


health = APIRouter(prefix='/health')
metadata = APIRouter(prefix='/metadata', tags=['metadata'])
plugin = APIRouter(prefix='/plugin', tags=['plugin'])
computation = APIRouter(prefix='/computation', tags=['computation'])
store = APIRouter(prefix='/store', tags=['store'])

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


@health.get(path='/', status_code=200, summary='Hey, is this thing on?')
def is_ok() -> dict:
    return {'status': 'ok'}


@AsyncTTL(time_to_live=60, maxsize=1)
@plugin.get(path='/', summary='List all currently available plugins.')
def list_plugins() -> List[_Info]:
    plugin_names = list(app.state.platform.list_active_plugins())
    plugin_names.sort()

    plugin_list = []
    for plugin_name in plugin_names:
        try:
            plugin = app.state.platform.request_info(plugin_name)
            plugin_list.append(plugin)
        except InfoNotReceivedException as e:
            log.warning(f'Plugin {plugin_name} has an open channel but could not be reached.', exc_info=e)
            continue
        except ClimatoologyVersionMismatchException as e:
            log.warning(f'Version mismatch for plugin {plugin_name}', exc_info=e)
            continue

    return plugin_list


@plugin.get(path='/{plugin_id}', summary='Get information on a specific plugin or check its online status.')
def get_plugin(plugin_id: str) -> _Info:
    try:
        return app.state.platform.request_info(plugin_id=plugin_id)
    except InfoNotReceivedException as e:
        raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} does not exist.') from e
    except ClimatoologyVersionMismatchException as e:
        raise HTTPException(
            status_code=500, detail=f'Plugin {plugin_id} is not in a correct state (version mismatch).'
        ) from e


@plugin.post(
    path='/{plugin_id}',
    summary='Schedule a computation task on a plugin.',
    description='The parameters depend on the chosen plugin. '
    'Their input schema can be requested from the /plugin GET methods.',
)
def plugin_compute(
    plugin_id: str, aoi: geojson_pydantic.Feature[geojson_pydantic.MultiPolygon, AoiProperties], params: dict
) -> CorrelationIdObject:
    correlation_uuid = uuid.uuid4()
    app.state.platform.send_compute_request(
        plugin_id=plugin_id, aoi=aoi, params=params, correlation_uuid=correlation_uuid
    )
    return CorrelationIdObject(correlation_uuid)


@computation.websocket(path='/')
async def subscribe_compute_status(websocket: WebSocket, correlation_uuid: UUID = None) -> None:
    return HTTPException(status_code=501, detail='This endpoint will be fixed soon')


@computation.get(
    path='/{correlation_uuid}/state',
    summary='Get the state of the computation.',
    description='Get the state of the computation. States are equal to the celery computation states described here: https://docs.celeryq.dev/en/stable/userguide/tasks.html#built-in-states',
)
def get_computation_status(correlation_uuid: UUID) -> ComputationState:
    result = AsyncResult(id=str(correlation_uuid), app=app.state.platform.celery_app)
    return result.state


@store.get(
    path='/{correlation_uuid}',
    summary='List all artifacts associated with a correlation uuid.',
    description='Note that this list may be emtpy if the computation has not been started or is not yet completed. '
    'To receive actual content you need to use the store uuid returned.',
)
def list_artifacts(correlation_uuid: UUID) -> List[_Artifact]:
    return app.state.platform.storage.list_all(correlation_uuid=correlation_uuid)


@store.get(
    path='/{correlation_uuid}/metadata/',
    summary='Get the pre-signed URL for the computation metadata JSON file.',
    description='The metadata lists a summary of the input parameters and additional info about the computation.',
)
def fetch_metadata(correlation_uuid: UUID) -> RedirectResponse:
    try:
        return fetch_artifact(correlation_uuid, COMPUTATION_INFO_FILENAME)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f'The requested run {correlation_uuid} does not have metadata.')


@store.get(
    path='/{correlation_uuid}/{store_id}',
    summary='Fetch a pre-signed URL pointing to the requested artifact.',
    description='The store_id can be parsed from the listing endpoint.',
)
def fetch_artifact(correlation_uuid: UUID, store_id: str) -> RedirectResponse:
    signed_url = app.state.platform.storage.get_artifact_url(correlation_uuid=correlation_uuid, store_id=store_id)

    if not signed_url:
        raise HTTPException(
            status_code=404, detail=f'The requested element {correlation_uuid}/{store_id} does not exist!'
        )
    return RedirectResponse(url=signed_url)


@metadata.get(
    path='/concerns',
    summary='Retrieve a list of concerns.',
    description='Concerns are tag-like descriptions of plugin topics.',
)
def get_concerns() -> Concerns:
    return Concerns({c.value for c in Concern})


app.include_router(health)
app.include_router(metadata)
app.include_router(plugin)
app.include_router(computation)
app.include_router(store)

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
