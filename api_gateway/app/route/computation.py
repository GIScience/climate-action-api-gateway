import logging
from dataclasses import dataclass
from typing import Annotated, Tuple
from uuid import UUID

from celery.exceptions import TaskRevokedError, TimeLimitExceeded
from celery.result import AsyncResult
from climatoology.base.computation import ComputationState
from climatoology.base.exception import ClimatoologyUserError, InputValidationError
from fastapi import APIRouter, Depends, HTTPException
from fastapi_cache.decorator import cache
from starlette.requests import Request

from api_gateway.app.route.search import router as search_router
from api_gateway.app.utils import cache_ttl

log = logging.getLogger(__name__)

router = APIRouter(prefix='/computation', tags=['computation'])
router.include_router(search_router)


@dataclass
class ComputationStateInfo:
    state: ComputationState
    message: str = ''


def _resolve_computation_id(correlation_uuid: UUID, request: Request) -> UUID:
    """Resolve the user's correlation UUID to the computation it belongs to, or raise a 404 if it is unknown."""
    computation_uuid = request.app.state.platform.backend_db.resolve_computation_id(correlation_uuid)
    if computation_uuid is None:
        raise HTTPException(status_code=404, detail=f'Correlation UUID {correlation_uuid} is unknown.')
    return computation_uuid


ResolvedComputationUUID = Annotated[UUID, Depends(_resolve_computation_id)]


def _extract_computation_status(computation_uuid: UUID, request: Request) -> Tuple[ComputationState, str]:
    """
    Read the status of an already resolved computation id. Use with caution: silently returns `PENDING` for an unknown
    computation_uuid. It is recommended to use this after resolving the user's correlation UUID
    with `_resolve_computation_id`.
    """
    result = AsyncResult(id=str(computation_uuid), app=request.app.state.platform.celery_app)

    state = ComputationState(result.state)
    task_result = result.result

    message = ''
    if isinstance(task_result, (ClimatoologyUserError, InputValidationError)):
        message = str(task_result)
    elif isinstance(task_result, TimeLimitExceeded):
        message = 'The requested computation is too big, try using a smaller area or revise the input parameters.'
    elif isinstance(task_result, TaskRevokedError):
        message = 'The task has been canceled due to high server load, please retry.'

    return state, message


@router.get(
    path='/{correlation_uuid}/state',
    summary='Get the state of the computation with messages.',
    description='Get the state of the computation with messages. States are equal to the celery computation states '
    'described here: https://docs.celeryq.dev/en/stable/userguide/tasks.html#built-in-states',
)
@cache(expire=cache_ttl(2))
async def get_computation_status(computation_uuid: ResolvedComputationUUID, request: Request) -> ComputationStateInfo:
    state, message = _extract_computation_status(computation_uuid, request)
    return ComputationStateInfo(state=state, message=message)
