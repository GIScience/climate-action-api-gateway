from dataclasses import dataclass
from uuid import UUID

from celery.exceptions import TaskRevokedError, TimeLimitExceeded
from celery.result import AsyncResult
from climatoology.base.event import ComputationState
from climatoology.utility.exception import ClimatoologyUserError, InputValidationError
from fastapi import APIRouter, WebSocketException
from starlette.requests import Request
from starlette.websockets import WebSocket

router = APIRouter(prefix='/computation', tags=['computation'])


@dataclass
class ComputationStateInfo:
    state: ComputationState
    message: str = ''


@router.websocket(path='/{correlation_uuid}')
async def subscribe_compute_status(websocket: WebSocket, correlation_uuid: UUID) -> None:
    raise WebSocketException(code=1000, reason='Not Implemented')


@router.get(
    path='/{correlation_uuid}/state',
    summary='Get the state of the computation with messages.',
    description='Get the state of the computation with messages. States are equal to the celery computation states '
    'described here: https://docs.celeryq.dev/en/stable/userguide/tasks.html#built-in-states',
)
def get_computation_status(correlation_uuid: UUID, request: Request) -> ComputationStateInfo:
    computation_uuid = request.app.state.platform.backend_db.resolve_computation_id(
        correlation_uuid
    )  # TODO: add tests for all endpoints with correlation_uuid

    result = AsyncResult(id=str(computation_uuid), app=request.app.state.platform.celery_app)
    message = ''
    if isinstance(result.result, (ClimatoologyUserError, InputValidationError)):
        message = str(result.result)
    elif isinstance(result.result, TimeLimitExceeded):
        message = 'The requested computation is too big, try using a smaller area or revise the input parameters.'
    elif isinstance(result.result, TaskRevokedError):
        message = 'The task has been canceled due to high server load, please retry.'
    return ComputationStateInfo(state=result.state, message=message)
