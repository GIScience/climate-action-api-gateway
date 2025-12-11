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


def test_fetch_artifact(mocked_client, deduplicated_uuid):
    response = mocked_client.get(f'/store/{deduplicated_uuid}/{deduplicated_uuid}', follow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'
