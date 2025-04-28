import logging
import sys
import uuid
from dataclasses import dataclass
from typing import Annotated, List
from uuid import UUID

import geojson_pydantic
from climatoology.base.baseoperator import AoiProperties
from climatoology.base.info import _Info
from climatoology.utility.exception import VersionMismatchException, InfoNotReceivedException
from fastapi import APIRouter, Body, HTTPException
from fastapi_cache.decorator import cache
from starlette.requests import Request

log = logging.getLogger(__name__)

router = APIRouter(prefix='/plugin', tags=['plugin'])


@dataclass
class CorrelationIdObject:
    correlation_uuid: UUID


@router.get(path='/', summary='List all currently available plugins.')
@cache(expire=60)
def list_plugins(request: Request) -> List[_Info]:
    plugin_names = list(request.app.state.platform.list_active_plugins())
    plugin_names.sort()

    plugin_list = []
    for plugin_name in plugin_names:
        try:
            plugin = request.app.state.platform.request_info(plugin_name)
            plugin_list.append(plugin)
        except InfoNotReceivedException as e:
            log.warning(f'Plugin {plugin_name} has an open channel but could not be reached.', exc_info=e)
            continue
        except VersionMismatchException as e:
            log.warning(f'Version mismatch for plugin {plugin_name}', exc_info=e)
            continue

    return plugin_list


@router.get(path='/{plugin_id}', summary='Get information on a specific plugin or check its online status.')
def get_plugin(plugin_id: str, request: Request) -> _Info:
    try:
        return request.app.state.platform.request_info(plugin_id=plugin_id)
    except InfoNotReceivedException as e:
        raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} does not exist.') from e
    except VersionMismatchException as e:
        raise HTTPException(
            status_code=500, detail=f'Plugin {plugin_id} is not in a correct state (version mismatch).'
        ) from e


@router.post(
    path='/{plugin_id}',
    summary='Schedule a computation task on a plugin.',
    description='The parameters depend on the chosen plugin. '
    'Their input schema can be requested from the /plugin GET methods.',
)
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
        plugin_id=plugin_id, aoi=aoi, params=params, correlation_uuid=correlation_uuid
    )
    return CorrelationIdObject(correlation_uuid)


@router.get(
    path='/{plugin_id}/demo',
    summary='Get the correlation id for the demo computation.',
    description='Each plugin provides a demo computation that is precomputed and features a preview of the '
    'functionality.',
)
@cache(expire=sys.maxsize)  # TODO: should be removed in favour of proper idempotency control soon!
def plugin_demo(plugin_id: str, request: Request) -> CorrelationIdObject:
    correlation_uuid = uuid.uuid4()
    info = get_plugin(plugin_id, request)

    if not info.demo_config:
        raise HTTPException(status_code=404, detail=f'Plugin {plugin_id} does not provide a demo.')

    demo_aoi_properties = AoiProperties(name='Demo', id=f'{plugin_id}-demo')
    aoi_feature = geojson_pydantic.Feature(
        type='Feature', geometry=info.demo_config.aoi, properties=demo_aoi_properties
    )

    request.app.state.platform.send_compute_request(
        plugin_id=plugin_id, aoi=aoi_feature, params=info.demo_config.params, correlation_uuid=correlation_uuid
    )
    return CorrelationIdObject(correlation_uuid)
