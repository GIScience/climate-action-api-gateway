import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, List
from uuid import UUID

import geojson_pydantic
from climatoology.app.platform import CacheOverrides
from climatoology.app.plugin import generate_plugin_name
from climatoology.base.baseoperator import AoiProperties
from climatoology.base.info import _Info
from climatoology.utility.exception import InfoNotReceivedException, VersionMismatchException
from fastapi import APIRouter, Body, HTTPException
from fastapi_cache.decorator import cache
from starlette.requests import Request

log = logging.getLogger(__name__)

router = APIRouter(prefix='/plugin', tags=['plugin'])


class PluginStatus(StrEnum):
    ONLINE = 'online'
    OFFLINE = 'offline'


@dataclass
class PluginStatusObject:
    status: PluginStatus


@dataclass
class CorrelationIdObject:
    correlation_uuid: UUID


@router.get(path='', summary='List all currently available plugins.')
@cache(expire=60)
async def list_plugins(request: Request) -> List[_Info]:
    plugin_ids = list(request.app.state.platform.list_active_plugins())
    plugin_ids.sort()

    plugin_list = []
    for plugin_id in plugin_ids:
        try:
            plugin_info = await get_plugin(plugin_id=plugin_id, request=request)
            plugin_list.append(plugin_info)
        except HTTPException as e:
            log.warning(f'Plugin {plugin_id} has an open channel but info could not be loaded.', exc_info=e)
            continue

    return plugin_list


@router.get(path='/{plugin_id}', summary='Get information on a specific plugin or check its online status.')
@cache(expire=60 * 60)
async def get_plugin(plugin_id: str, request: Request) -> _Info:
    try:
        return request.app.state.platform.request_info(plugin_id=plugin_id)
    except InfoNotReceivedException as e:
        raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} does not exist.') from e
    except VersionMismatchException as e:
        raise HTTPException(
            status_code=500, detail=f'Plugin {plugin_id} is not in a correct state (version mismatch).'
        ) from e


@router.get(path='/{plugin_id}/status', summary='Is this plugin online?')
@cache(expire=60)
def get_plugin_status(plugin_id: str, request: Request) -> PluginStatusObject:
    plugin_name = generate_plugin_name(plugin_id=plugin_id)
    try:
        pong = request.app.state.platform.celery_app.control.inspect().ping(destination=[plugin_name])
        pong = pong.get(plugin_name, {'ok': 'no'})
        if pong['ok'] == 'pong':
            return PluginStatusObject(status=PluginStatus.ONLINE)
    except Exception:
        pass
    return PluginStatusObject(status=PluginStatus.OFFLINE)


@router.post(
    path='/{plugin_id}',
    summary='Schedule a computation task on a plugin.',
    description='The parameters depend on the chosen plugin. '
    'Their input schema can be requested from the /plugin GET methods.',
)
@cache(expire=3)
def plugin_compute(
    plugin_id: str,
    aoi: Annotated[
        geojson_pydantic.Feature[geojson_pydantic.MultiPolygon, AoiProperties],
        Body(
            examples=[
                {
                    'type': 'Feature',
                    'properties': {'name': 'name', 'id': 'id'},
                    'geometry': {
                        'coordinates': [[[[8.66, 49.42], [8.66, 49.41], [8.67, 49.41], [8.67, 49.42], [8.66, 49.42]]]],
                        'type': 'MultiPolygon',
                    },
                }
            ]
        ),
    ],
    params: dict,
    request: Request,
) -> CorrelationIdObject:
    correlation_uuid = uuid.uuid4()
    request.app.state.platform.send_compute_request(
        plugin_id=plugin_id,
        aoi=aoi,
        params=params,
        correlation_uuid=correlation_uuid,
        task_time_limit=request.app.state.settings.computation_time_limit,
        q_time=request.app.state.settings.computation_queue_time,
    )
    return CorrelationIdObject(correlation_uuid)


@router.get(
    path='/{plugin_id}/demo',
    summary='Get the correlation id for the demo computation.',
    description='Each plugin provides a demo computation that is precomputed and features a preview of the '
    'functionality.',
)
@cache(expire=3)
async def plugin_demo(plugin_id: str, request: Request) -> CorrelationIdObject:
    correlation_uuid = uuid.uuid4()
    info = await get_plugin(plugin_id, request)

    if not info.demo_config:
        raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} does not provide a demo.')

    demo_aoi_properties = AoiProperties(name='Demo', id=f'{plugin_id}-demo')
    aoi_feature = geojson_pydantic.Feature(
        type='Feature', geometry=info.demo_config.aoi, properties=demo_aoi_properties
    )

    request.app.state.platform.send_compute_request(
        plugin_id=plugin_id,
        aoi=aoi_feature,
        params=info.demo_config.params,
        correlation_uuid=correlation_uuid,
        override_shelf_life=CacheOverrides.FOREVER,
    )
    return CorrelationIdObject(correlation_uuid)
