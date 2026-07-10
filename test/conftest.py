import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
import sqlalchemy
from climatoology.store.database import migration
from climatoology.store.database.database import BackendDatabase
from climatoology.test.fixtures.database import connection_to_string
from kombu import Exchange, Queue
from pytest_alembic import Config
from starlette.testclient import TestClient

from api_gateway.app.settings import GatewaySettings
from api_gateway.sender import EXCHANGE_NAME, CelerySender, PluginInfoResponse

pytest_plugins = (
    'celery.contrib.pytest',
    'climatoology.test.fixtures.base',
    # 'climatoology.test.fixtures.alembic',
    'climatoology.test.fixtures.aoi',
    'climatoology.test.fixtures.artifact',
    'climatoology.test.fixtures.computation',
    'climatoology.test.fixtures.database',
    'climatoology.test.fixtures.plugin',
    'climatoology.test.fixtures.plugin_info',
)


@pytest.fixture
def deduplicated_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def default_info_response(default_plugin_info_final) -> PluginInfoResponse:
    response_info = default_plugin_info_final.model_copy()
    response_info.operator_schema['$defs']['Option']['x-translation'] = {'OPT1': 'OPT1', 'OPT2': 'OPT2'}
    return PluginInfoResponse(**response_info.model_dump(mode='json'), online=True)


@pytest.fixture
def default_sender(
    celery_app, mocked_object_store, set_basic_envs, default_backend_db
) -> Generator[CelerySender, None, None]:
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
def alembic_config() -> Config:
    return Config(config_options={'script_location': str(Path(migration.__file__).parent)})


@pytest.fixture
def alembic_engine(db_fixture_basic, set_basic_envs):
    conn_str = connection_to_string(db_fixture_basic)
    return sqlalchemy.create_engine(conn_str)


@pytest.fixture
def mocked_client(default_sender) -> Generator[TestClient, None, None]:
    with patch('fastapi_cache.decorator.cache', lambda *args, **kwargs: lambda f: f):
        from api_gateway.app.api import app
    app.state.settings = GatewaySettings()
    app.state.platform = default_sender
    client = TestClient(app)

    yield client
