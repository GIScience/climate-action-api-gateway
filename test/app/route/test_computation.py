import time
from unittest.mock import patch

import pytest
from climatoology.base.event import ComputationState
from starlette.websockets import WebSocketDisconnect


def test_subscribe_compute_status(mocked_client, general_uuid):
    with pytest.raises(WebSocketDisconnect):
        with mocked_client.websocket_connect(f'/computation/{general_uuid}') as _:
            pass


def test_computation_status_unknown(mocked_client, general_uuid):
    response = mocked_client.get(f'/computation/{general_uuid}/state')
    assert response.status_code == 404


def test_computation_status_pending(mocked_client, deduplicated_uuid, backend_with_computation):
    response = mocked_client.get(f'/computation/{deduplicated_uuid}/state')
    assert response.status_code == 200
    assert response.json() == {'state': ComputationState.PENDING.value, 'message': ''}


def test_computation_status_revoked_q_time_exceeded(mocked_client, general_uuid, default_aoi_pure_dict, default_plugin):
    mocked_client.app.state.settings.computation_queue_time = 0.0
    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        mocked_client.post('/plugin/test_plugin', json={'aoi': default_aoi_pure_dict, 'params': {'id': 1}})
    response = mocked_client.get(f'/computation/{general_uuid}/state')

    assert response.status_code == 200
    assert response.json() == {
        'state': ComputationState.REVOKED.value,
        'message': 'The task has been canceled due to high server load, please retry.',
    }


def test_computation_status_message_on_wrong_input(mocked_client, general_uuid, default_aoi_pure_dict, default_plugin):
    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        mocked_client.post('/plugin/test_plugin', json={'aoi': default_aoi_pure_dict, 'params': {'wrong': True}})

    time.sleep(1)  # let the worker do its job
    response = mocked_client.get(f'/computation/{general_uuid}/state')

    assert response.status_code == 200
    assert response.json() == {
        'state': ComputationState.FAILURE.value,
        'message': "ID: Field required. You provided: {'wrong': True}.",
    }
