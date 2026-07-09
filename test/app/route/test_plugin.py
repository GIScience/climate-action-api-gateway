from unittest.mock import patch

import pytest
from climatoology.base.plugin_info import DEFAULT_LANGUAGE
from climatoology.store.database.models.computation import ComputationLookupTable, ComputationTable
from climatoology.store.database.models.plugin_info import PluginInfoTable
from semver import Version
from sqlalchemy import select, update
from sqlalchemy.orm import Session


def test_list_plugins(mocked_client, default_info_response, default_plugin):
    response = mocked_client.get('/plugin')

    assert response.status_code == 200

    response = response.json()
    assert response == [default_info_response.model_dump(mode='json')]


def test_list_plugins_only_latest_version(
    mocked_client, default_plugin_info_final, default_info_response, default_plugin, default_backend_db
):
    newer_plugin_info = default_plugin_info_final.model_copy(deep=True)
    newer_plugin_info.version = Version(4, 0, 0)
    default_backend_db.write_info(info=newer_plugin_info)

    expected_plugin_response = default_info_response.model_copy(deep=True)
    expected_plugin_response.version = Version(4, 0, 0)

    response = mocked_client.get('/plugin')

    assert response.status_code == 200

    response = response.json()
    assert response == [expected_plugin_response.model_dump(mode='json')]


def test_list_plugins_lang(mocked_client, default_info_response, default_plugin):
    response = mocked_client.get('/plugin', params={'lang': 'de'})

    assert response.status_code == 200

    response = response.json()

    assert len(response) == 1
    response_info = response[0]
    assert response_info['language'] == 'de'
    assert response_info['methodology'] == 'Die Methoden auf Deutsch'


def test_list_plugins_unknown_lang(mocked_client, default_info_response, default_plugin):
    response = mocked_client.get('/plugin', params={'lang': 'aa'})

    assert response.status_code == 200

    response = response.json()

    assert response == [default_info_response.model_dump(mode='json')]


def test_list_plugins_invalid_among_us(mocked_client, default_plugin, default_backend_db):
    with Session(default_backend_db.engine) as session:
        session.execute(update(PluginInfoTable).values(demo_config='{}'))
        session.commit()
    response = mocked_client.get('/plugin')

    assert response.status_code == 200

    response = response.json()
    assert response == []


def test_get_plugin(mocked_client, default_info_response, default_plugin):
    response = mocked_client.get('/plugin/test_plugin')

    assert response.status_code == 200

    response = response.json()
    assert response == default_info_response.model_dump(mode='json')


def test_get_plugin_by_language(mocked_client, default_info_response, default_plugin):
    response = mocked_client.get('/plugin/test_plugin', params={'lang': 'de'})

    assert response.status_code == 200

    response = response.json()

    assert response['language'] == 'de'
    assert response['methodology'] == 'Die Methoden auf Deutsch'


def test_get_plugin_by_language_unknonwn(mocked_client, default_info_response, default_plugin):
    response = mocked_client.get('/plugin/test_plugin', params={'lang': 'aa'}, follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == default_info_response.model_dump(mode='json')


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


@pytest.mark.parametrize(
    'request_lang,computation_lang',
    [(None, DEFAULT_LANGUAGE), (DEFAULT_LANGUAGE, DEFAULT_LANGUAGE), ('de', 'de'), ('aa', DEFAULT_LANGUAGE)],
)
def test_plugin_compute(
    mocked_client,
    default_plugin,
    general_uuid,
    default_aoi_feature_pure_dict,
    default_backend_db,
    request_lang,
    computation_lang,
):
    params = dict()
    if request_lang:
        params = params | {'lang': request_lang}

    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        response = mocked_client.post(
            '/plugin/test_plugin', json={'aoi': default_aoi_feature_pure_dict, 'params': dict()}, params=params
        )

        assert response.status_code == 200
        assert response.json() == {'correlation_uuid': str(general_uuid)}

    with Session(default_backend_db.engine) as session:
        language = session.scalar(
            select(ComputationTable.language)
            .join(ComputationLookupTable)
            .where(ComputationLookupTable.user_correlation_uuid == general_uuid)
        )
        assert language == computation_lang


@pytest.mark.parametrize(
    'request_lang,computation_lang',
    [(None, DEFAULT_LANGUAGE), (DEFAULT_LANGUAGE, DEFAULT_LANGUAGE), ('de', 'de'), ('aa', DEFAULT_LANGUAGE)],
)
def test_plugin_compute_demo(
    mocked_client, default_backend_db, default_plugin, general_uuid, request_lang, computation_lang
):
    params = dict()
    if request_lang:
        params = params | {'lang': request_lang}

    with patch('api_gateway.app.route.plugin.uuid.uuid4', return_value=general_uuid):
        response = mocked_client.get('/plugin/test_plugin/demo', params=params)

        assert response.status_code == 200
        assert response.json() == {'correlation_uuid': str(general_uuid)}

        with Session(default_backend_db.engine) as session:
            demo_atts = session.execute(
                select(ComputationTable.language, ComputationLookupTable.is_demo)
                .join(ComputationLookupTable)
                .where(ComputationLookupTable.user_correlation_uuid == general_uuid)
            ).all()

            assert demo_atts == [(computation_lang, True)]
