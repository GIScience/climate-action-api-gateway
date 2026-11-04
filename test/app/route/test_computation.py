import time
import uuid
from unittest.mock import patch

import pytest
from celery.exceptions import TaskRevokedError
from celery.result import AsyncResult
from climatoology.app.settings import EXCHANGE_NAME
from climatoology.base.computation import ComputationState


def test_computation_status_unknown(mocked_client, general_uuid):
    response = mocked_client.get(f'/computation/{general_uuid}/state')
    assert response.status_code == 404


def test_computation_status_success(mocked_client, deduplicated_uuid, backend_with_computation_deduplicated):
    response = mocked_client.get(f'/computation/{deduplicated_uuid}/state')
    assert response.status_code == 200
    assert response.json() == {'state': ComputationState.SUCCESS, 'message': ''}


def test_computation_status_revoked_q_time_exceeded(
    mocked_client, general_uuid, default_aoi_feature_pure_dict, default_plugin
):
    mocked_client.app.state.settings.computation_queue_time = 0.0
    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        mocked_client.post('/plugin/test_plugin', json={'aoi': default_aoi_feature_pure_dict, 'params': {'id': 1}})

    # Wait for the task to be processed before we query its state
    with pytest.raises(TaskRevokedError):
        AsyncResult(id=str(general_uuid)).get(timeout=5)

    response = mocked_client.get(f'/computation/{general_uuid}/state')

    assert response.status_code == 200
    assert response.json() == {
        'state': ComputationState.REVOKED,
        'message': 'The task has been canceled due to high server load, please retry.',
    }


@pytest.mark.skip(
    'This test only fails on this branch. I had problems with it in another branch as well. '
    'I think it is only due to how we set up the test client. '
    'Investigate (https://gitlab.heigit.org/climate-action/api-gateway/-/work_items/87)!'
)
def test_computation_status_message_on_wrong_input(
    mocked_client, general_uuid, default_aoi_feature_pure_dict, default_plugin
):
    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        mocked_client.post(
            '/plugin/test_plugin', json={'aoi': default_aoi_feature_pure_dict, 'params': {'wrong': True}}
        )

    time.sleep(1)  # let the worker do its job
    response = mocked_client.get(f'/computation/{general_uuid}/state')

    assert response.status_code == 200
    assert response.json() == {
        'state': ComputationState.FAILURE,
        'message': "ID: Field required. You provided: {'wrong': True}.",
    }

    # streamed endpoint should also have a message
    response = mocked_client.get(f'/computation/{general_uuid}/state/stream')

    assert response.status_code == 200
    assert (
        response.text
        == 'data: {"state":"FAILURE","message":"ID: Field required. You provided: {\'wrong\': True}."}\n\n'
    )


def test_computation_status_stream_unknown(mocked_client, general_uuid):
    response = mocked_client.get(f'/computation/{general_uuid}/state/stream')
    assert response.status_code == 404


def test_computation_status_stream_only_once_if_already_completed(
    mocked_client, deduplicated_uuid, backend_with_computation_deduplicated
):
    response = mocked_client.get(f'/computation/{deduplicated_uuid}/state/stream')

    assert response.status_code == 200
    assert response.text == 'data: {"state":"SUCCESS","message":""}\n\n'


def test_computation_status_stream_pushes_each_state(mocked_client, default_plugin, default_computation_info):
    correlation_uuid = uuid.uuid4()

    plugin_key = mocked_client.app.state.platform.backend_db.read_info_key(
        plugin_id=default_computation_info.plugin_info.id, language=default_computation_info.language
    )
    mocked_client.app.state.platform.backend_db.register_computation(
        plugin_key=plugin_key,
        computation_shelf_life=None,
        correlation_uuid=correlation_uuid,
        requested_params=default_computation_info.requested_params,
        aoi=default_computation_info.aoi,
        is_demo=False,
        language=default_computation_info.language,
    )
    mocked_client.app.state.platform.celery_app.send_task(
        name='compute',
        kwargs={
            'aoi': default_computation_info.aoi.model_dump(mode='json'),
            'params': default_computation_info.params,
            'lang': default_computation_info.language,
        },
        task_id=str(correlation_uuid),
        routing_key=default_computation_info.plugin_info.id,
        exchange=EXCHANGE_NAME,
        countdown=1,  # wait 1 second before starting, so we get the PENDING state
    )

    response = mocked_client.get(f'/computation/{correlation_uuid}/state/stream')
    assert response.status_code == 200

    expected_response = ''
    for state in (ComputationState.PENDING, ComputationState.STARTED, ComputationState.SUCCESS):
        expected_response += f'data: {{"state":"{state}","message":""}}\n\n'

    assert response.text == expected_response


def test_computation_status_stream_time_limit(mocked_client, general_uuid, backend_with_computation_registered):
    with patch.object(mocked_client.app.state.settings, 'stream_time_limit', 0):
        response = mocked_client.get(f'/computation/{general_uuid}/state/stream')

    assert response.status_code == 200

    # Only one data response/result was published
    assert response.text == 'data: {"state":"PENDING","message":""}\n\n'
