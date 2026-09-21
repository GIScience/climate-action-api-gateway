# In the future, the SearchComputationsView may become a part of climatoology directly. Then, these tests would move too.

from datetime import datetime

from climatoology.store.database.database import ComputationLookupTable, row_to_dict
from shapely import Point
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api_gateway.search_view import SearchComputationsView


def test_search_computations_view(backend_with_searchable_computations, additional_computations):
    """Only returns valid computations."""
    expected_view = {
        'correlation_uuid': additional_computations[-1],
        'plugin_id': 'test_plugin',
        'aoi_name': 'test_aoi',
        'min_zoom': None,
        'aoi_centroid': Point(0.25, 0.5),
        'request_ts': datetime(2018, 1, 1, 12, 0),
        'language': 'en',
    }

    with Session(backend_with_searchable_computations.engine) as session:
        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 3

        result = results[-1]

    result_dict = row_to_dict(result)
    result_dict['aoi_centroid'] = result.aoi_centroid
    assert result_dict == expected_view


def test_search_computations_view_only_boundaries(backend_with_searchable_computations, general_uuid_de):
    """Doesn't return computations with an `original_type` other than `Boundary`."""
    with Session(backend_with_searchable_computations.engine) as session:
        session.execute(
            update(ComputationLookupTable)
            .where(ComputationLookupTable.user_correlation_uuid == general_uuid_de)
            .values(aoi_properties={'original_type': 'Circle'})
        )

        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2


def test_search_computations_view_search_for_language(backend_with_searchable_computations):
    """Search for language returns expected number of computations."""
    # Although we could parametrize this test, it's faster and not too messy to duplicate assertions
    with Session(backend_with_searchable_computations.engine) as session:
        valid_computation_select = SearchComputationsView.search_for(languages=['en'])
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

        valid_computation_select = SearchComputationsView.search_for(languages=['en', 'de'])
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 3

        valid_computation_select = SearchComputationsView.search_for(languages=['aa'])
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 0


def test_search_computations_view_search_for_plugin_id(backend_with_searchable_computations):
    """Search for plugin_id returns expected number of computations."""
    with Session(backend_with_searchable_computations.engine) as session:
        valid_computation_select = SearchComputationsView.search_for(plugin_id='test_plugin')
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 3

        valid_computation_select = SearchComputationsView.search_for(plugin_id='nonexistent_plugin')
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 0


def test_search_computations_view_search_for_everything(backend_with_searchable_computations):
    """Search by all filters returns expected number of computations."""
    with Session(backend_with_searchable_computations.engine) as session:
        valid_computation_select = SearchComputationsView.search_for(plugin_id='test_plugin', languages=['de'])
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 1
