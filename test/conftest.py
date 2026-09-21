import uuid
from datetime import timedelta
from typing import Generator
from unittest.mock import patch

import pytest
from climatoology.store.database.database import BackendDatabase
from climatoology.store.database.models.computation import ComputationLookupTable, ComputationTable
from kombu import Exchange, Queue
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import now as db_now
from starlette.testclient import TestClient

from api_gateway.sender import EXCHANGE_NAME, CelerySender, PluginInfoResponse

with patch('fastapi_cache.decorator.cache', lambda *args, **kwargs: lambda f: f):
    from api_gateway.app.api import app

pytest_plugins = (
    'celery.contrib.pytest',
    'climatoology.test.fixtures.base',
    'climatoology.test.fixtures.aoi',
    'climatoology.test.fixtures.artifact',
    'climatoology.test.fixtures.computation',
    'climatoology.test.fixtures.database',
    'climatoology.test.fixtures.plugin',
    'climatoology.test.fixtures.plugin_info',
)


@pytest.fixture
def mocked_client(default_sender) -> Generator[TestClient, None, None]:
    # Adding the default_sender fixture to this text correctly mocks away all backend connections
    with TestClient(app) as client:
        # This will run the `configure_dependencies` function of the `app` object
        yield client


@pytest.fixture
def deduplicated_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def backend_with_computation_deduplicated(
    backend_with_computation_successful,
    default_computation_info,
    default_plugin_info_final,
    deduplicated_uuid,
    default_plugin_key,
) -> BackendDatabase:
    backend_with_computation_successful.register_computation(
        correlation_uuid=deduplicated_uuid,
        requested_params=default_computation_info.requested_params,
        aoi=default_computation_info.aoi,
        plugin_key=default_plugin_key,
        computation_shelf_life=default_plugin_info_final.computation_shelf_life,
    )
    return backend_with_computation_successful


@pytest.fixture
def celery_app(celery_app, default_settings):
    # Add queue to the base celery_app, so the platform also knows about it (because we aren't running rabbitmq for real)
    compute_queue = Queue(
        name='test_plugin',
        exchange=Exchange(EXCHANGE_NAME),
        routing_key='test_plugin',
        queue_arguments={
            'x-dead-letter-exchange': default_settings.deadletter_exchange_name,
            'x-dead-letter-routing-key': default_settings.deadletter_channel_name,
        },
    )
    celery_app.amqp.queues.select_add(compute_queue)
    yield celery_app


@pytest.fixture
def default_sender(
    celery_app, mocked_object_store, default_backend_db, set_basic_envs, monkeypatch
) -> Generator[CelerySender, None, None]:
    monkeypatch.setenv('deduplicate_computations', 'true')

    with (
        patch('api_gateway.sender.Celery', return_value=celery_app),
        patch(
            'api_gateway.sender.CelerySender.construct_storage',
            return_value=mocked_object_store,
        ),
        patch('api_gateway.sender.BackendDatabase', return_value=default_backend_db),
    ):
        yield CelerySender()


@pytest.fixture
def default_info_response(default_plugin_info_final) -> PluginInfoResponse:
    response_info = default_plugin_info_final.model_copy()
    response_info.operator_schema['$defs']['Option']['x-translation'] = {'OPT1': 'OPT1', 'OPT2': 'OPT2'}
    return PluginInfoResponse(**response_info.model_dump(mode='json'), online=True)


@pytest.fixture
def additional_computations(
    default_plugin_info_final,
    default_aoi_feature_geojson_pydantic,
    default_plugin,
    backend_with_computation_successful,
    default_sender,
) -> list[uuid.UUID]:
    """Create additional computations for the search tests."""
    corr_uuids = []
    for param_id in [2, 3]:
        corr_id = uuid.uuid4()
        corr_uuids.append(corr_id)

        result = default_sender.send_compute_request(
            plugin_id=default_plugin_info_final.id,
            aoi=default_aoi_feature_geojson_pydantic,
            params={'id': param_id},
            correlation_uuid=corr_id,
        )

        _ = result.get(timeout=5)

    with Session(backend_with_computation_successful.engine) as session:
        session.execute(update(ComputationTable).values(valid_until=db_now() + timedelta(hours=1)))
        session.execute(update(ComputationLookupTable).values(aoi_properties={'original_type': 'Boundary'}))
        session.commit()

    return corr_uuids


@pytest.fixture
def backend_with_searchable_computations(
    backend_with_computation_successful, general_uuid, general_uuid_de, additional_computations
):
    """
    This fixture returns a database with the following computations:

    | plugin_id   | plugin_version | correlation_uuid           | requested_params | language | min_zoom | valid? |
    |-------------|----------------|----------------------------|------------------|----------|----------|--------|
    | test_plugin | 3.1.0          | general_uuid               | {'id': 1}        | 'en'     | -        | no     |
    | test_plugin | 3.1.0          | general_uuid_de            | {'id': 1}        | 'de'     | 18       | yes    |
    | test_plugin | 3.1.0          | additional_computations[0] | {'id': 2}        | 'en'     | -        | yes    |
    | test_plugin | 3.1.0          | additional_computations[1] | {'id': 3}        | 'en'     | -        | yes    |
    """
    modified_backend = backend_with_computation_successful
    with Session(modified_backend.engine) as session:
        session.execute(update(ComputationLookupTable).values(aoi_properties={'original_type': 'Boundary'}))

        # Invalidate the general_uuid
        session.execute(
            update(ComputationTable)
            .where(ComputationTable.correlation_uuid == general_uuid)
            .values(valid_until=db_now() - timedelta(hours=1))
        )

        # Set the min_zoom level for general_uuid_de so we can check that it was actually set
        session.execute(
            update(ComputationLookupTable)
            .where(ComputationLookupTable.user_correlation_uuid == general_uuid_de)
            .values(aoi_properties={'original_type': 'Boundary', 'min_zoom': 18})
        )

        session.commit()

    return modified_backend
