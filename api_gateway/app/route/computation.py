from dataclasses import dataclass
from uuid import UUID

from celery.result import AsyncResult
from climatoology.base.event import ComputationState
from climatoology.utility.exception import ClimatoologyUserError, InputValidationError
from fastapi import APIRouter, HTTPException
from starlette.requests import Request
from starlette.websockets import WebSocket

router = APIRouter(prefix='/computation', tags=['computation'])


@dataclass
class ComputationStateInfo:
    state: ComputationState
    message: str = ''


@router.websocket(path='/')
async def subscribe_compute_status(websocket: WebSocket, correlation_uuid: UUID = None) -> None:
    return HTTPException(status_code=501, detail='This endpoint will be fixed soon')


@router.get(
    path='/{correlation_uuid}/state',
    summary='Get the state of the computation with messages.',
    description='Get the state of the computation with messages. States are equal to the celery computation states '
    'described here: https://docs.celeryq.dev/en/stable/userguide/tasks.html#built-in-states',
)
def get_computation_status(correlation_uuid: UUID, request: Request) -> ComputationStateInfo:
    result = AsyncResult(id=str(correlation_uuid), app=request.app.state.platform.celery_app)
    message = ''
    if type(result.result) in (ClimatoologyUserError, InputValidationError):
        message = str(result.result)
    return ComputationStateInfo(state=result.state, message=message)
