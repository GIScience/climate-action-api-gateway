def test_get_concerns(mocked_client):
    response = mocked_client.get('/metadata/concerns')
    assert response.status_code == 200
    assert 'ghg_emission' in response.json()['items']
