def test_fetch_icon(mocked_client):
    response = mocked_client.get('/store/test_plugin/icon', allow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'


# TODO: needs better mocking to complete successfulyy

# def test_fetch_metadata(mocked_client, general_uuid, default_plugin, default_aoi,default_computation_info, default_platform_connection ):
#     with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
#         _ = mocked_client.post('/plugin/test_plugin', json={'aoi': default_aoi, 'params': {'id':1}})
#
#     # Wait for the computation to finish
#     result = AsyncResult(id=str(general_uuid), app=default_platform_connection.celery_app)
#     _ = result.get(timeout=5)
#
#     response = mocked_client.get(f'/store/{general_uuid}/metadata')
#
#     assert response.json() == default_computation_info.model_dump(mode='json')


# def test_list_artifacts(mocked_client, general_uuid):
#     response = mocked_client.get(f'/store/{general_uuid}')
#
#     assert response.status_code == 200
#     assert response.json() == []


def test_fetch_artifact(mocked_client, general_uuid):
    response = mocked_client.get(f'/store/{general_uuid}/{general_uuid}', allow_redirects=False)

    assert response.status_code == 307
    assert response.headers['location'] == 'test-presigned-url'
