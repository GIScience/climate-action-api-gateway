from typing import Optional

from celery.backends.database import TaskExtended
from climatoology.app.plugin import PluginInfoTable
from climatoology.base.computation import ComputationState
from climatoology.store.database.database import ComputationLookupTable, ComputationTable
from climatoology.store.database.models.base import ClimatoologyViewBase
from pydantic_extra_types.language_code import LanguageAlpha2
from sqlalchemy import Select, select
from sqlalchemy.sql.functions import now as db_now


class SearchComputationsView(ClimatoologyViewBase):
    """
    A placeholder view of all valid, searchable computations. In the future, this may become a view which is served by
    climatoology directly, but until then it is defined here as a subquery.
    """

    select_statement = (
        select(
            ComputationTable.correlation_uuid,
            PluginInfoTable.id.label('plugin_id'),
            ComputationLookupTable.aoi_name,
            ComputationLookupTable.aoi_properties['min_zoom'].as_integer().label('min_zoom'),
            ComputationTable.aoi_centroid,
            ComputationLookupTable.request_ts,
            PluginInfoTable.language,
        )
        .join(PluginInfoTable, ComputationTable.plugin_key == PluginInfoTable.key)
        .join(TaskExtended, ComputationTable.correlation_uuid == TaskExtended.task_id)
        .join(ComputationLookupTable, ComputationLookupTable.computation_id == ComputationTable.correlation_uuid)
        .where(PluginInfoTable.latest)
        .where(ComputationTable.valid_until > db_now())
        .where(TaskExtended.status == ComputationState.SUCCESS)
        .where(ComputationLookupTable.aoi_properties['original_type'].as_string() == 'Boundary')
    )

    # Here we create the statements as a 'subquery' instead of an actual view, because climatoology is responsible for
    # the database schema and creation of views. If this moves to climatoology, we should create the view and set the
    # schema properly, as we do for all other views.
    __table__ = select_statement.subquery()

    @staticmethod
    def search_for(
        *, ordered: bool = True, plugin_id: Optional[str] = None, languages: Optional[list[LanguageAlpha2]] = None
    ) -> Select:
        """Create a select statement to search for valid computations that meet the given criteria."""
        search_query = select(SearchComputationsView)
        if plugin_id is not None:
            search_query = search_query.where(SearchComputationsView.plugin_id == plugin_id)
        if languages is not None:
            search_query = search_query.where(SearchComputationsView.language.in_(languages))

        if ordered:
            search_query = search_query.order_by(
                SearchComputationsView.request_ts, SearchComputationsView.correlation_uuid
            )

        return search_query
