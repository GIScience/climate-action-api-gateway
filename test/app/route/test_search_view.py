# In the future, the SearchComputationsView may become a part of climatoology directly. Then, these tests would move too.

from datetime import UTC, datetime, timedelta

from celery.backends.database import TaskExtended
from climatoology.base.computation import ComputationState
from climatoology.store.database.database import ComputationLookupTable, row_to_dict
from climatoology.store.database.models.computation import ComputationTable
from climatoology.store.database.models.plugin_info import PluginInfoTable
from pydantic_extra_types.language_code import LanguageAlpha2
from shapely import Point
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api_gateway.search_view import SearchComputationsView, db_utc_now


def test_search_computations_view(default_backend_db, searchable_computations):
    """Only returns valid computations."""
    expected_view = {
        'correlation_uuid': searchable_computations['first'],
        'plugin_id': 'test_plugin',
        'aoi_name': 'test_aoi',
        'min_zoom': None,
        'aoi_centroid': Point(0.25, 0.5),
        'request_ts': datetime(2018, 1, 1, 2, tzinfo=UTC),
        'language': 'en',
    }

    with Session(default_backend_db.engine) as session:
        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

    result_dict = row_to_dict(results[0])
    assert result_dict == expected_view


def test_search_computations_view_ignore_outdated_plugin(default_backend_db, searchable_computations):
    """Doesn't return computations where the plugin is not the latest version."""
    with Session(default_backend_db.engine) as session:
        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

        # Outdate plugin
        session.execute(update(PluginInfoTable).values(latest=False))

        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 0


def test_search_computations_view_ignore_invalid(default_backend_db, searchable_computations):
    """Doesn't return computations which are not valid any more."""
    with Session(default_backend_db.engine) as session:
        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

        # Invalidate the first computation
        session.execute(
            update(ComputationTable)
            .where(ComputationTable.correlation_uuid == searchable_computations['first'])
            .values(valid_until=db_utc_now() - timedelta(hours=1))
        )

        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 1


def test_search_computations_view_ignore_failed(default_backend_db, searchable_computations):
    """Doesn't return computations that did not succeed."""
    with Session(default_backend_db.engine) as session:
        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

        # Fail the first computation
        session.execute(
            update(TaskExtended)
            .where(TaskExtended.task_id == str(searchable_computations['first']))
            .values(status=ComputationState.FAILURE)
        )

        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 1


def test_search_computations_view_only_boundaries(default_backend_db, searchable_computations):
    """Doesn't return computations with an `original_type` other than `Boundary`."""
    with Session(default_backend_db.engine) as session:
        session.execute(
            update(ComputationLookupTable)
            .where(ComputationLookupTable.user_correlation_uuid == searchable_computations['first'])
            .values(aoi_properties={'original_type': 'Circle'})
        )

        valid_computation_select = select(SearchComputationsView)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 1


def test_search_computations_view_search_for_language(default_backend_db, searchable_computations):
    """Search for language returns expected number of computations."""
    # Although we could parametrize this test, it's faster and not too messy to duplicate assertions
    en = LanguageAlpha2('en')
    de = LanguageAlpha2('de')
    with Session(default_backend_db.engine) as session:
        valid_computation_select = SearchComputationsView.search_for()
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

        valid_computation_select = SearchComputationsView.search_for(languages=[en])
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 1

        valid_computation_select = SearchComputationsView.search_for(languages=[en, de])
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

        valid_computation_select = SearchComputationsView.search_for(languages=[LanguageAlpha2('aa')])
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 0


def test_search_computations_view_search_for_plugin_id(default_backend_db, searchable_computations):
    """Search for plugin_id returns expected number of computations."""
    with Session(default_backend_db.engine) as session:
        valid_computation_select = SearchComputationsView.search_for(plugin_id='test_plugin')
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 2

        valid_computation_select = SearchComputationsView.search_for(plugin_id='nonexistent_plugin')
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 0


def test_search_computations_view_search_for_everything(default_backend_db, searchable_computations):
    """Search by all filters returns expected number of computations."""
    with Session(default_backend_db.engine) as session:
        valid_computation_select = SearchComputationsView.search_for(
            plugin_id='test_plugin', languages=[LanguageAlpha2('de')]
        )
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        assert len(results) == 1


def test_search_computations_view_search_for_is_ordered_latest_first(default_backend_db, searchable_computations):
    """Search results are ordered by descending `request_ts`."""
    with Session(default_backend_db.engine) as session:
        valid_computation_select = SearchComputationsView.search_for(ordered=False)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        timestamps = [result.request_ts for result in results]
        assert timestamps != sorted(timestamps, reverse=True)

        valid_computation_select = SearchComputationsView.search_for(ordered=True)
        result_scalars = session.scalars(valid_computation_select)
        results = result_scalars.fetchall()

        timestamps = [result.request_ts for result in results]
        assert timestamps == sorted(timestamps, reverse=True)
