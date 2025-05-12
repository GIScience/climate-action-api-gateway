from datetime import timedelta
from typing import List
from uuid import UUID

from climatoology.base.artifact import _Artifact
from climatoology.store.object_store import COMPUTATION_INFO_FILENAME
from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

router = APIRouter(prefix='/store', tags=['store'])

STORAGE_REDIRECT_TTL = 3600


@router.get(
    path='/{plugin_id}/icon',
    summary='Fetch the icon for a plugin.',
    description='Icons are stable assets',
)
def fetch_icon(plugin_id: str, request: Request) -> RedirectResponse:
    signed_url = request.app.state.platform.storage.get_icon_url(
        plugin_id=plugin_id, expires=timedelta(seconds=STORAGE_REDIRECT_TTL + 60)
    )

    if not signed_url:
        raise HTTPException(
            status_code=404,
            detail=f'The requested icon asset for plugin {plugin_id} does not exist!',
        )
    return RedirectResponse(url=signed_url)


@router.get(
    path='/{correlation_uuid}/metadata',
    summary='Get the pre-signed URL for the computation metadata JSON file.',
    description='The metadata lists a summary of the input parameters and additional info about the computation.',
)
def fetch_metadata(correlation_uuid: UUID, request: Request) -> RedirectResponse:
    computation_uuid = request.app.state.platform.backend_db.resolve_computation_id(correlation_uuid)

    try:
        signed_url = request.app.state.platform.storage.get_artifact_url(
            correlation_uuid=computation_uuid,
            store_id=COMPUTATION_INFO_FILENAME,
            expires=timedelta(seconds=STORAGE_REDIRECT_TTL + 60),
        )
        return RedirectResponse(url=signed_url)
    except HTTPException:
        raise HTTPException(status_code=404, detail=f'The requested run {correlation_uuid} does not have metadata.')


@router.get(
    path='/{correlation_uuid}',
    summary='List all artifacts associated with a correlation uuid.',
    description='Note that this list may be emtpy if the computation has not been started or is not yet completed. '
    'To receive actual content you need to use the store uuid returned.',
)
def list_artifacts(correlation_uuid: UUID, request: Request) -> List[_Artifact]:
    computation_uuid = request.app.state.platform.backend_db.resolve_computation_id(correlation_uuid)
    return request.app.state.platform.storage.list_all(correlation_uuid=computation_uuid)


@router.get(
    path='/{correlation_uuid}/{store_id}',
    summary='Fetch a pre-signed URL pointing to the requested artifact.',
    description='The store_id can be parsed from the listing endpoint.',
)
def fetch_artifact(correlation_uuid: UUID, store_id: str, request: Request) -> RedirectResponse:
    computation_uuid = request.app.state.platform.backend_db.resolve_computation_id(correlation_uuid)
    signed_url = request.app.state.platform.storage.get_artifact_url(
        correlation_uuid=computation_uuid, store_id=store_id, expires=timedelta(seconds=STORAGE_REDIRECT_TTL + 60)
    )

    if not signed_url:
        raise HTTPException(
            status_code=404, detail=f'The requested element {correlation_uuid}/{store_id} does not exist!'
        )
    return RedirectResponse(url=signed_url)
