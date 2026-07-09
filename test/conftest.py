import os
import uuid
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
import sqlalchemy
from climatoology.store.database import migration
from climatoology.store.database.database import BackendDatabase
from kombu import Exchange, Queue
from pytest_alembic import Config
from pytest_postgresql.janitor import DatabaseJanitor
from sqlalchemy import create_engine, text
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
def db_connection_params(request) -> dict:
    if os.getenv('CI', 'False').lower() == 'true':
        return {
            'host': os.getenv('POSTGRES_HOST'),
            'port': os.getenv('POSTGRES_PORT'),
            'database': os.getenv('POSTGRES_DB'),
            'user': os.getenv('POSTGRES_USER'),
            'password': os.getenv('POSTGRES_PASSWORD'),
        }
    else:
        postgresql = request.getfixturevalue('postgresql')
        return {
            'host': postgresql.info.host,
            'port': postgresql.info.port,
            'database': postgresql.info.dbname,
            'user': postgresql.info.user,
            'password': postgresql.info.password,
        }


@pytest.fixture
def db_connection_string(db_connection_params) -> str:
    host = db_connection_params['host']
    port = db_connection_params['port']
    dbname = db_connection_params['database']
    user = db_connection_params['user']
    password = db_connection_params['password']

    if os.getenv('CI', 'False').lower() == 'true':
        db_janitor = DatabaseJanitor(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            version=int(os.getenv('POSTGRES_VERSION')),
        )
        db_janitor.drop()
        db_janitor.init()

    return f'postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}'


@pytest.fixture
def db_with_postgis(db_connection_string) -> str:
    with create_engine(db_connection_string).connect() as con:
        con.execute(text('CREATE EXTENSION IF NOT EXISTS postgis;'))
        con.commit()
    return db_connection_string


@pytest.fixture
def db_with_tables(db_with_postgis, alembic_runner) -> str:
    alembic_runner.migrate_up_to('head')
    return db_with_postgis


@pytest.fixture
def default_backend_db(db_with_tables) -> BackendDatabase:
    return BackendDatabase(connection_string=db_with_tables, user_agent='Test Climatoology Backend')


@pytest.fixture
def backend_with_computations(
    default_backend_db,
    default_computation_info,
    default_plugin_info_final,
    deduplicated_uuid,
    set_basic_envs,
    frozen_time,
    default_plugin_key,
) -> BackendDatabase:
    default_backend_db.write_info(info=default_plugin_info_final)
    default_backend_db.register_computation(
        correlation_uuid=default_computation_info.correlation_uuid,
        requested_params=default_computation_info.requested_params,
        aoi=default_computation_info.aoi,
        plugin_key=default_plugin_key,
        computation_shelf_life=default_plugin_info_final.computation_shelf_life,
    )
    default_backend_db.add_validated_params(
        correlation_uuid=default_computation_info.correlation_uuid,
        params={'id': 1, 'name': 'John Doe', 'execution_time': 0.0},
    )
    default_backend_db.update_successful_computation(computation_info=default_computation_info)
    default_backend_db.register_computation(
        correlation_uuid=deduplicated_uuid,
        requested_params=default_computation_info.requested_params,
        aoi=default_computation_info.aoi,
        plugin_key=default_plugin_key,
        computation_shelf_life=default_plugin_info_final.computation_shelf_life,
    )
    return default_backend_db


@pytest.fixture
def alembic_config() -> Config:
    return Config(config_options={'script_location': str(Path(migration.__file__).parent)})


@pytest.fixture
def alembic_engine(db_with_postgis, set_basic_envs):
    return sqlalchemy.create_engine(db_with_postgis)


@pytest.fixture
def mocked_client(default_sender) -> Generator[TestClient, None, None]:
    with patch('fastapi_cache.decorator.cache', lambda *args, **kwargs: lambda f: f):
        from api_gateway.app.api import app
    app.state.settings = GatewaySettings()
    app.state.platform = default_sender
    client = TestClient(app)

    yield client
