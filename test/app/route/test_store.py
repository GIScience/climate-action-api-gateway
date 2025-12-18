import uuid

from climatoology.base.computation import ComputationState


def test_fetch_icon(mocked_client):
    response = mocked_client.get('/store/test_plugin/icon', follow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'


def test_fetch_metadata(mocked_client, deduplicated_uuid, default_computation_info, backend_with_computations):
    expected_metadata = default_computation_info.model_dump(mode='json')
    # Because we never actually sent the test to celery, it considers the task to be `PENDING`.
    # This would be fixed when we resolve https://gitlab.heigit.org/climate-action/climatoology/-/issues/246
    expected_metadata['status'] = ComputationState.PENDING

    response = mocked_client.get(f'/store/{deduplicated_uuid}/metadata')
    metadata = response.json()

    assert response.status_code == 200
    assert metadata == expected_metadata


def test_fetch_metadata_unknown(mocked_client, deduplicated_uuid):
    response = mocked_client.get(f'/store/{deduplicated_uuid}/metadata')

    assert response.status_code == 404


def test_fetch_artifact_list(mocked_client, deduplicated_uuid, default_artifact_enriched, backend_with_computations):
    response = mocked_client.get(f'/store/{deduplicated_uuid}', follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == [default_artifact_enriched.model_dump(mode='json')]


def test_fetch_artifact_list_computation_unknown(mocked_client, backend_with_computations):
    correlation_uuid = uuid.uuid4()
    response = mocked_client.get(f'/store/{correlation_uuid}', follow_redirects=False)

    assert response.status_code == 404


def test_fetch_artifact(mocked_client, deduplicated_uuid):
    response = mocked_client.get(f'/store/{deduplicated_uuid}/{deduplicated_uuid}', follow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'
