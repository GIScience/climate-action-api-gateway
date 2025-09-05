import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from celery.exceptions import TaskRevokedError, TimeLimitExceeded
from celery.result import AsyncResult
from climatoology.base.event import ComputationState
from climatoology.utility.exception import ClimatoologyUserError, InputValidationError
from fastapi import APIRouter, HTTPException, WebSocketException
from fastapi_cache.decorator import cache
from starlette.requests import Request
from starlette.websockets import WebSocket

log = logging.getLogger(__name__)

router = APIRouter(prefix='/computation', tags=['computation'])


@dataclass
class ComputationStateInfo:
    state: ComputationState
    message: str = ''


@router.websocket(path='/{correlation_uuid}')
async def subscribe_compute_status(websocket: WebSocket, correlation_uuid: UUID) -> None:
    log.debug(f'Received websocket request for {correlation_uuid} using websocket {websocket}')
    raise WebSocketException(code=1000, reason='Not Implemented')


@router.get(
    path='/{correlation_uuid}/state',
    summary='Get the state of the computation with messages.',
    description='Get the state of the computation with messages. States are equal to the celery computation states '
    'described here: https://docs.celeryq.dev/en/stable/userguide/tasks.html#built-in-states',
)
@cache(expire=2)
def get_computation_status(correlation_uuid: UUID, request: Request) -> ComputationStateInfo:
    computation_uuid = request.app.state.platform.backend_db.resolve_computation_id(correlation_uuid)

    result = AsyncResult(id=str(computation_uuid), app=request.app.state.platform.celery_app)
    task_result = result.result

    state = ComputationState(result.state)
    if state == ComputationState.PENDING:
        db_computations = request.app.state.platform.backend_db.read_computation(computation_uuid)
        if db_computations is None:
            raise HTTPException(status_code=404, detail=f'Correlation UUID {correlation_uuid} is unknown.')
        else:
            if db_computations.timestamp + timedelta(
                seconds=request.app.state.settings.computation_queue_time
            ) < datetime.now(UTC).replace(tzinfo=None):
                log.warning(
                    f'Manually resetting the cache time for computation {computation_uuid}. This is a current hack while the dead letter channel is not available.'
                )
                request.app.state.platform.backend_db.update_failed_computation(
                    correlation_uuid=computation_uuid,
                    failure_message='The task has been canceled due to high server load, please retry.',
                    cache=False,
                    status=ComputationState.REVOKED,
                )
                state = ComputationState.REVOKED
                task_result = TaskRevokedError()

    message = ''
    if isinstance(task_result, (ClimatoologyUserError, InputValidationError)):
        message = str(task_result)
    elif isinstance(task_result, TimeLimitExceeded):
        message = 'The requested computation is too big, try using a smaller area or revise the input parameters.'
    elif isinstance(task_result, TaskRevokedError):
        message = 'The task has been canceled due to high server load, please retry.'

    return ComputationStateInfo(state=state, message=message)
