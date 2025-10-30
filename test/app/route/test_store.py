from unittest.mock import ANY


def test_fetch_icon(mocked_client):
    response = mocked_client.get('/store/test_plugin/icon', follow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'


def test_fetch_metadata(mocked_client, deduplicated_uuid, default_computation_info, backend_with_computations):
    expected_metadata = default_computation_info.model_dump(mode='json')
    # TODO: reconsider this. See comment in test_sender.py::test_send_compute_produces_result
    # The decision should be a little different for this test, but we should decide what we want to get as a response
    # here!
    expected_metadata['status'] = ANY
    # TODO: this is a "completed the full cyrcle" artifact, so it has a rank...
    expected_metadata['artifacts'][0]['rank'] = 0

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
