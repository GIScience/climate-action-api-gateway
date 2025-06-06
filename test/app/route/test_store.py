def test_fetch_icon(mocked_client):
    response = mocked_client.get('/store/test_plugin/icon', allow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'


def test_fetch_artifact(mocked_client, general_uuid):
    response = mocked_client.get(f'/store/{general_uuid}/{general_uuid}', allow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'
