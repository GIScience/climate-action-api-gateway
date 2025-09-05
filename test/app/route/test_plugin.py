from unittest.mock import patch


def test_list_plugins(mocked_client, default_info_final, default_plugin):
    response = mocked_client.get('/plugin')

    assert response.status_code == 200

    response = response.json()
    assert response == [default_info_final.model_dump(mode='json')]


def test_get_plugin(mocked_client, default_info_final, default_plugin):
    response = mocked_client.get('/plugin/test_plugin')

    assert response.status_code == 200

    response = response.json()
    assert response == default_info_final.model_dump(mode='json')


def test_get_plugin_status_online(mocked_client, default_plugin):
    response = mocked_client.get('/plugin/test_plugin/status')

    assert response.status_code == 200

    response = response.json()
    assert response == {'status': 'online'}


def test_get_plugin_status_offline(mocked_client):
    response = mocked_client.get('/plugin/test_plugin_inexistent/status')

    assert response.status_code == 200

    response = response.json()
    assert response == {'status': 'offline'}


def test_plugin_compute(mocked_client, default_plugin, general_uuid, default_aoi_pure_dict):
    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        response = mocked_client.post('/plugin/test_plugin', json={'aoi': default_aoi_pure_dict, 'params': dict()})

        assert response.status_code == 200
        assert response.json() == {'correlation_uuid': str(general_uuid)}


def test_plugin_compute_demo(mocked_client, default_plugin, general_uuid):
    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        response = mocked_client.get('/plugin/test_plugin/demo')

        assert response.status_code == 200
        assert response.json() == {'correlation_uuid': str(general_uuid)}
