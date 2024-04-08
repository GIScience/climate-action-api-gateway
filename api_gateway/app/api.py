import asyncio
import logging.config
import os
import uuid
from asyncio.exceptions import TimeoutError
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Tuple
from uuid import UUID

import hydra
import uvicorn
import yaml
from aio_pika import ExchangeType
from aiormq import ChannelClosed, ChannelNotFoundEntity
from cache import AsyncTTL
from fastapi import APIRouter, FastAPI, WebSocket, HTTPException
from fastapi.responses import FileResponse
from hydra import compose
from pydantic.dataclasses import dataclass
from starlette.websockets import WebSocketDisconnect

from climatoology.base.artifact import _Artifact
from climatoology.base.event import ComputeCommandStatus, ComputeCommandResult
from climatoology.base.operator import Info, Concern
from climatoology.broker.message_broker import AsyncRabbitMQ, RabbitMQManagementAPI
from climatoology.store.object_store import MinioStorage
from climatoology.utility.exception import InfoNotReceivedException, ClimatoologyVersionMismatchException

config_dir = os.getenv('API_GATEWAY_APP_CONFIG_DIR', str(Path('conf').absolute()))

log_level = os.getenv('LOG_LEVEL', 'INFO')
log_config = f'{config_dir}/logging/app/logging.yaml'
log = logging.getLogger(__name__)


@dataclass
class CorrelationIdObject:
    correlation_uuid: UUID


@dataclass
class Concerns:
    items: set[str]


@asynccontextmanager
async def configure_dependencies(app: FastAPI):
    log.debug('configure dependencies')

    hydra.initialize_config_dir(config_dir=config_dir, version_base=None)
    cfg = compose(config_name='config')

    app.state.storage = MinioStorage(host=cfg.store.host,
                                     port=int(cfg.store.port),
                                     access_key=cfg.store.access_key,
                                     secret_key=cfg.store.secret_key,
                                     secure=cfg.store.secure == 'True',
                                     bucket=cfg.store.bucket,
                                     file_cache=Path(cfg.store.file_cache))
    app.state.broker = AsyncRabbitMQ(host=cfg.broker.host,
                                     port=int(cfg.broker.port),
                                     user=cfg.broker.user,
                                     password=cfg.broker.password,
                                     connection_pool_max_size=int(cfg.broker.connection_pool_max_size),
                                     assert_plugin_version=cfg.broker.assert_plugin_version == 'True')

    await app.state.broker.async_init()

    app.state.broker_management_api = RabbitMQManagementAPI(api_url=cfg.broker.api_url,
                                                            user=cfg.broker.user,
                                                            password=cfg.broker.password)

    log.debug('dependencies configured')
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
    version='1.0.0',
    contact={
        'name': 'Climate Acton Team',
        'url': 'https://heigit.org/',
        'email': 'climate-action@heigit.org',
    },
    openapi_tags=tags_metadata,
    lifespan=configure_dependencies)


@health.get(path='/',
            status_code=200,
            summary='Hey, is this thing on?')
def is_ok() -> dict:
    return {'status': 'ok'}


@AsyncTTL(time_to_live=60, maxsize=1)
async def list_plugins(plugin_names: Tuple) -> List[Info]:
    plugin_list = []
    for plugin_name in plugin_names:
        try:
            plugin = await app.state.broker.request_info(plugin_name)
            plugin_list.append(plugin)
        except InfoNotReceivedException as e:
            log.warning(f'Plugin {plugin_name} has an open channel but could not be reached.',
                        exc_info=e)
            continue
        except ClimatoologyVersionMismatchException as e:
            log.warning(f'Version mismatch for plugin {plugin_name}',
                        exc_info=e)
            continue

    return plugin_list


@plugin.get(path='/',
            summary='List all currently available plugins.')
async def plugins() -> List[Info]:
    plugin_names = app.state.broker_management_api.get_active_plugins()
    plugin_names.sort()
    return await list_plugins(tuple(plugin_names))


@plugin.get(path='/{plugin_id}',
            summary='Get information on a specific plugin or check its online status.')
async def get_plugin(plugin_id: str) -> Info:
    try:
        return await app.state.broker.request_info(plugin_id=plugin_id)
    except InfoNotReceivedException as e:
        raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} does not exist.') from e
    except ClimatoologyVersionMismatchException as e:
        raise HTTPException(status_code=500,
                            detail=f'Plugin {plugin_id} is not in a correct state (version mismatch).') from e


@plugin.post(path='/{plugin_id}',
             summary='Schedule a computation task on a plugin.',
             description='The parameters depend on the chosen plugin. '
                         'Their input schema can be requested from the /plugin GET methods.')
async def plugin_compute(plugin_id: str, params: dict) -> CorrelationIdObject:
    correlation_uuid = uuid.uuid4()
    try:
        await app.state.broker.send_compute(plugin_id, params, correlation_uuid)
    except ChannelNotFoundEntity as e:
        await app.state.broker.publish_status_update(correlation_uuid=correlation_uuid,
                                                     status=ComputeCommandStatus.FAILED)
        raise HTTPException(status_code=404, detail='The plugin is not online.') from e
    await app.state.broker.publish_status_update(correlation_uuid=correlation_uuid,
                                                 status=ComputeCommandStatus.SCHEDULED)
    return CorrelationIdObject(correlation_uuid)


@computation.websocket(path='/')
async def subscribe_compute_status(websocket: WebSocket, correlation_uuid: UUID = None) -> None:
    async with app.state.broker.connection_pool.acquire() as connection:
        async with connection.channel() as channel:

            await websocket.accept()

            async def subscribe_callback(message):
                status = ComputeCommandResult.model_validate_json(message.body.decode())
                if not correlation_uuid or status.correlation_uuid == correlation_uuid:
                    await websocket.send_json(status.model_dump_json())

            try:
                exchange = await channel.declare_exchange(app.state.broker.get_status_exchange(), ExchangeType.FANOUT)
                queue = await channel.declare_queue(exclusive=True)
                await queue.bind(exchange)
                await queue.consume(subscribe_callback)
                log.info(f'Websocket {queue.name} interaction has been started')

                while True:
                    await asyncio.wait_for(websocket.receive_json(), timeout=10.0)

            except (TimeoutError, WebSocketDisconnect):
                log.info(f'Websocket {queue.name} interaction has been finished')
            except ChannelClosed:
                log.exception(f'Websocket {queue.name} interaction has been abruptly finished')
            finally:
                await queue.delete(if_unused=False, if_empty=False)


@store.get(path='/{correlation_uuid}',
           summary='List all artifacts associated with a correlation uuid.',
           description='Note that this list may be emtpy if the computation has not been started '
                       'or is not yet completed. '
                       'To receive actual content you need to use the store uuid returned.')
def list_artifacts(correlation_uuid: UUID) -> List[_Artifact]:
    return app.state.storage.list_all(correlation_uuid=correlation_uuid)


@store.get(path='/{correlation_uuid}/{store_id}',
           summary='Download a specific file.',
           description='The store_id can be parsed from the listing endpoint.')
def fetch_artifact(correlation_uuid: UUID, store_id: str) -> FileResponse:
    file_path = app.state.storage.fetch(correlation_uuid=correlation_uuid,
                                        store_id=store_id)

    if not file_path or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f'The requested element {correlation_uuid}/{store_id} does '
                                                    'not exist!')
    return FileResponse(path=file_path)


@metadata.get(path='/concerns',
              summary='Retrieve a list of concerns.',
              description='Concerns are tag-like descriptions of plugin topics.')
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

    uvicorn.run(app,
                host='0.0.0.0',
                port=int(os.getenv('API_GATEWAY_API_PORT', 8000)),
                root_path=os.getenv('ROOT_PATH', '/'),
                log_config=log_config,
                log_level=log_level.lower())
