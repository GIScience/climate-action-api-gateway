from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

import geojson_pydantic
from fastapi import APIRouter, HTTPException, Query
from fastapi_pagination.ext.sqlalchemy import paginate
from pydantic import BaseModel, Field, model_validator
from pydantic_extra_types.language_code import LanguageAlpha2
from sqlakeyset import BadBookmark
from sqlalchemy import JSON, cast, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import func
from starlette.requests import Request

from api_gateway.app.route.plugin import get_plugin
from api_gateway.app.utils import GatewayCursorPage
from api_gateway.search_view import SearchComputationsView

router = APIRouter(prefix='/search', tags=['search'])


class SearchResponse(BaseModel):
    correlation_uuid: UUID
    plugin_id: str
    aoi_name: str
    language: LanguageAlpha2
    request_ts: datetime


@router.get('')
async def search(
    request: Request, plugin_id: Optional[str] = None, lang: Annotated[Optional[list[LanguageAlpha2]], Query()] = None
) -> GatewayCursorPage[SearchResponse]:
    with Session(request.app.state.platform.backend_db.engine) as session:
        search_query = SearchComputationsView.search_for(ordered=True, plugin_id=plugin_id, languages=lang)

        try:
            page = paginate(conn=session, query=search_query)
        except BadBookmark as e:
            raise HTTPException(status_code=400, detail='Invalid cursor value') from e

    if plugin_id is not None and page.total == 0:
        # Confirm if the plugin actually exists
        await get_plugin(plugin_id=plugin_id, request=request)

    return page


class AoiPropertiesClustering(BaseModel):
    correlation_uuid: UUID = Field(description='The unique identifier of the computation.')
    aoi_name: str = Field(description='The name of the area of interest i.e. a human readable description.')
    min_zoom: Annotated[
        # It should be required, but currently isn't in climatoology, so we should also accept here if it is missing
        Optional[int],
        Field(
            strict=True,
            ge=0,
            le=25,
            description='Up to which zoom level the computation should be displayed as a centroid.'
            'At higher zoom levels, the AOI geometry should be fetched from the map server and displayed in full.',
        ),
    ]

    @model_validator(mode='after')
    def set_default_min_zoom(self) -> 'AoiPropertiesClustering':
        if self.min_zoom is None:
            # If the zoom level at which to switch from centroids to shapes is unknown, we do it "somewhere in the
            # middle"
            self.min_zoom = 10
        return self


CentroidFeatureModel = geojson_pydantic.Feature[geojson_pydantic.Point, AoiPropertiesClustering]
CentroidsFeatureCollectionModel = geojson_pydantic.FeatureCollection[CentroidFeatureModel]


@router.get('/centroids')
async def get_centroids(
    request: Request, plugin_id: str, lang: Annotated[Optional[list[LanguageAlpha2]], Query()] = None
) -> CentroidsFeatureCollectionModel:
    with Session(request.app.state.platform.backend_db.engine) as session:
        centroids_query = SearchComputationsView.search_for(plugin_id=plugin_id, languages=lang)
        centroids_query = centroids_query.cte('centroid_query')

        feature_query = select(cast(func.ST_AsGeoJSON(centroids_query), JSON))

        features = list(session.execute(feature_query).scalars())

    if len(features) == 0:
        # Confirm if the plugin actually exists
        await get_plugin(plugin_id=plugin_id, request=request)

    fc = geojson_pydantic.FeatureCollection(type='FeatureCollection', features=features)
    return fc
