import pytest
from climatoology.base.i18n import DEFAULT_LANGUAGE
from pydantic_extra_types.language_code import LanguageAlpha2


def test_search_basic(backend_with_searchable_computations, mocked_client, general_uuid_de):
    response = mocked_client.get('/computation/search')

    assert response.status_code == 200

    items = response.json()['items']
    assert len(items) == 3

    one_expected_item = {
        'correlation_uuid': str(general_uuid_de),
        'plugin_id': 'test_plugin',
        'aoi_name': 'test_aoi',
        'language': 'de',
        'request_ts': '2018-01-01T12:00:00',
    }
    assert one_expected_item in items


def test_search_all_params(backend_with_searchable_computations, mocked_client, default_plugin_info_final):
    response = mocked_client.get(
        '/computation/search', params={'plugin_id': default_plugin_info_final.id, 'lang': [DEFAULT_LANGUAGE]}
    )

    assert response.status_code == 200
    items = response.json()['items']
    assert len(items) == 2


def test_search_unknown_plugin(mocked_client):
    response = mocked_client.get('/computation/search', params={'plugin_id': 'nonexistent_plugin'})

    assert response.status_code == 404


def test_search_paginated(backend_with_searchable_computations, mocked_client, default_plugin_info_final):
    first = mocked_client.get('/computation/search', params={'plugin_id': default_plugin_info_final.id, 'page_size': 2})

    # Check first page
    assert first.status_code == 200

    first_page = first.json()
    assert first_page['total'] == 3
    assert len(first_page['items']) == 2

    # Use the cursor exacly as received - no decoding/re-encoding on the client side to get second page
    cursor = first_page['next_page']
    second = mocked_client.get(
        '/computation/search', params={'plugin_id': default_plugin_info_final.id, 'page_size': 2, 'cursor': cursor}
    )

    assert second.status_code == 200

    second_page = second.json()
    assert len(second_page['items']) == 1

    # Assert we get 3 unique results over two pages
    seen = {item['correlation_uuid'] for item in [*first_page['items'], *second_page['items']]}
    assert len(seen) == 3


def test_search_cursor_encoding(backend_with_searchable_computations, mocked_client, default_plugin_info_final):
    """
    Ensure that the next page cursor doesn't use any disallowed characters.

    The cursor is sent as a query parameter to the gateway.
    Query parameters are URL encoded when doing REST-requests.
    The stated chars cannot be URL-endcoded by the Angular front-end
    (https://github.com/angular/angular/issues/11058) and therefore are disallowed in cursors.
    """
    disallowed_chars = '%+'

    first = mocked_client.get('/computation/search', params={'plugin_id': default_plugin_info_final.id, 'page_size': 2})
    first_page = first.json()
    cursor = first_page['next_page']

    assert not any(char in cursor for char in disallowed_chars)


@pytest.mark.parametrize('cursor', ['____', '>!!!!', '>abc='])
def test_search_rejects_malformed_cursor(mocked_client, cursor):
    response = mocked_client.get(
        '/computation/search', params={'plugin_id': 'fake_plugin', 'size': 2, 'cursor': cursor}
    )

    assert response.status_code == 400
    assert response.json()['detail'] == 'Invalid cursor value'


def test_centroids(backend_with_searchable_computations, mocked_client, default_plugin_info_final):
    response = mocked_client.get('/computation/search/centroids', params={'plugin_id': default_plugin_info_final.id})

    assert response.status_code == 200

    collection = response.json()
    assert len(collection['features']) == 3


def test_centroids_returned_schema(
    backend_with_searchable_computations, mocked_client, default_plugin_info_final, general_uuid_de
):
    response = mocked_client.get(
        '/computation/search/centroids',
        params={'plugin_id': default_plugin_info_final.id, 'lang': [LanguageAlpha2('de')]},
    )

    assert response.status_code == 200

    collection = response.json()
    assert collection == {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [0.25, 0.5]},
                'properties': {
                    'correlation_uuid': str(general_uuid_de),
                    'aoi_name': 'test_aoi',
                    'min_zoom': 18,
                },
            }
        ],
    }
