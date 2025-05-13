import pytest
from climatoology.base.event import ComputationState
from starlette.websockets import WebSocketDisconnect


def test_subscribe_compute_status(mocked_client, general_uuid):
    with pytest.raises(WebSocketDisconnect):
        with mocked_client.websocket_connect(f'/computation/{general_uuid}') as _:
            pass


def test_computation_status_default_is_pending(mocked_client, general_uuid):
    response = mocked_client.get(f'/computation/{general_uuid}/state')
    assert response.status_code == 200
    assert response.json() == {'state': ComputationState.PENDING.value, 'message': ''}
