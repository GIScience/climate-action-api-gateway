import pytest
from climatoology.base.i18n import DEFAULT_LANGUAGE
from climatoology.store.database.models.computation import ComputationLookupTable
from pydantic_extra_types.language_code import LanguageAlpha2
from sqlalchemy import update
from sqlalchemy.orm import Session


def test_search_basic(mocked_client, searchable_computations):
    response = mocked_client.get('/computation/search')

    assert response.status_code == 200

    items = response.json()['items']
    assert len(items) == 2

    one_expected_item = {
        'correlation_uuid': str(searchable_computations['first']),
        'plugin_id': 'test_plugin',
        'aoi_name': 'test_aoi',
        'language': 'en',
        'request_ts': '2018-01-01T02:00:00Z',
    }
    assert one_expected_item in items


def test_search_all_params(mocked_client, searchable_computations, default_plugin_info_final):
    response = mocked_client.get(
        '/computation/search', params={'plugin_id': default_plugin_info_final.id, 'lang': [DEFAULT_LANGUAGE]}
    )

    assert response.status_code == 200
    items = response.json()['items']
    assert len(items) == 1


def test_search_unknown_plugin(mocked_client):
    response = mocked_client.get('/computation/search', params={'plugin_id': 'nonexistent_plugin'})

    assert response.status_code == 404


def test_search_paginated(mocked_client, searchable_computations, default_plugin_info_final):
    search_params = {'plugin_id': default_plugin_info_final.id, 'page_size': 1}
    first = mocked_client.get('/computation/search', params=search_params)

    # Check first page
    assert first.status_code == 200

    first_page = first.json()
    assert first_page['total'] == 2
    assert len(first_page['items']) == 1

    # Use the cursor exacly as received - no decoding/re-encoding on the client side to get second page
    cursor = first_page['next_page']
    second = mocked_client.get('/computation/search', params=search_params | {'cursor': cursor})

    assert second.status_code == 200

    second_page = second.json()
    assert len(second_page['items']) == 1

    # Assert we get 3 unique results over two pages
    seen = {item['correlation_uuid'] for item in [*first_page['items'], *second_page['items']]}
    assert len(seen) == 2


def test_search_cursor_encoding(mocked_client, searchable_computations, default_plugin_info_final):
    """
    Ensure that the next page cursor doesn't use any disallowed characters.

    The cursor is sent as a query parameter to the gateway.
    Query parameters are URL encoded when doing REST-requests.
    The stated chars cannot be URL-endcoded by the Angular front-end
    (https://github.com/angular/angular/issues/11058) and therefore are disallowed in cursors.
    """
    disallowed_chars = '%+'

    first = mocked_client.get('/computation/search', params={'plugin_id': default_plugin_info_final.id, 'page_size': 1})
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


def test_centroids(mocked_client, searchable_computations, default_plugin_info_final):
    response = mocked_client.get('/computation/search/centroids', params={'plugin_id': default_plugin_info_final.id})

    assert response.status_code == 200

    collection = response.json()
    assert len(collection['features']) == 2


def test_centroids_returned_schema(
    mocked_client, default_backend_db, searchable_computations, default_plugin_info_final
):
    # Test with default min_zoom
    response = mocked_client.get(
        '/computation/search/centroids',
        params={'plugin_id': default_plugin_info_final.id, 'lang': [LanguageAlpha2('en')]},
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
                    'correlation_uuid': str(searchable_computations['first']),
                    'aoi_name': 'test_aoi',
                    'min_zoom': 10,
                },
            }
        ],
    }

    # Test with adapted min_zoom
    with Session(default_backend_db.engine) as session:
        session.execute(
            update(ComputationLookupTable)
            .where(ComputationLookupTable.user_correlation_uuid == searchable_computations['first'])
            .values(aoi_properties={'original_type': 'Boundary', 'min_zoom': 18})
        )
        session.commit()

    response = mocked_client.get(
        '/computation/search/centroids',
        params={'plugin_id': default_plugin_info_final.id, 'lang': [LanguageAlpha2('en')]},
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
                    'correlation_uuid': str(searchable_computations['first']),
                    'aoi_name': 'test_aoi',
                    'min_zoom': 18,
                },
            }
        ],
    }
