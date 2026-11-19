import uuid
from datetime import datetime, timedelta
from typing import Generator
from unittest.mock import patch

import pytest
from climatoology.store.database.database import BackendDatabase, ComputationInfo
from climatoology.store.database.models.computation import ComputationLookupTable, ComputationTable
from kombu import Exchange, Queue
from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from api_gateway.search_view import db_utc_now
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

    # This will run the `configure_dependencies` function of the `app` object
    with TestClient(app) as client:
        client.app.state.settings.stream_time_limit = 5
        client.app.state.settings.stream_poll_interval = 0
        yield client


@pytest.fixture
def deduplicated_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def deduplicated_computation_info(default_computation_info) -> ComputationInfo:
    info = default_computation_info.model_copy(deep=True)
    info.aoi.properties.name = 'deduplicated_aoi'
    return info


@pytest.fixture
def backend_with_computation_deduplicated(
    backend_with_computation_successful,
    deduplicated_computation_info,
    default_plugin_info_final,
    deduplicated_uuid,
    default_plugin_key,
) -> BackendDatabase:
    backend_with_computation_successful.register_computation(
        correlation_uuid=deduplicated_uuid,
        requested_params=deduplicated_computation_info.requested_params,
        aoi=deduplicated_computation_info.aoi,
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
def searchable_computations(backend_with_computation_successful, general_uuid, general_uuid_de):
    """
    This fixture makes the backend_with_computation_successful searchable.
    The table then contains:


    | plugin_id   | plugin_version | correlation_uuid                                    | successful | language | valid?                                       | request_ts                                        | original_type (AOI attribute) |
    |-------------|----------------|-----------------------------------------------------|------------|----------|----------------------------------------------|---------------------------------------------------|-------------------------------|
    | test_plugin | 3.1.0 (latest) | general_uuid (searchable_computations['first'])     | yes        | 'en'     | yes until current UTC time (not mocked) + 1h | 2018-01-01T02:00:00 (mocked datetime.now() - 10h) | Boundary                      |
    | test_plugin | 3.1.0 (latest) | general_uuid_de (searchable_computations['second']) | yes        | 'de'     | yes until current UTC time (not mocked) + 1h | 2018-01-01T07:00:00 (mocked datetime.now() - 5h)  | Boundary                      |

    returns: A dict of the first and second correlation UUID
    """
    with Session(backend_with_computation_successful.engine) as session:
        # Make all computations searchable
        ## Make computations valid
        session.execute(update(ComputationTable).values(valid_until=db_utc_now() + timedelta(hours=1)))
        # Make computations of original_type: Boundary
        session.execute(update(ComputationLookupTable).values(aoi_properties={'original_type': 'Boundary'}))

        session.execute(
            update(ComputationLookupTable)
            .where(ComputationLookupTable.user_correlation_uuid == general_uuid)
            .values(request_ts=datetime.now() - timedelta(hours=10))
        )
        session.execute(
            update(ComputationLookupTable)
            .where(ComputationLookupTable.user_correlation_uuid == general_uuid_de)
            .values(request_ts=datetime.now() - timedelta(hours=5))
        )

        session.commit()

    return {'first': general_uuid, 'second': general_uuid_de}
