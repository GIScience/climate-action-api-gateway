import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Generator, List
from unittest.mock import patch

import geojson_pydantic
import pytest
import shapely
import sqlalchemy
from celery import Celery
from climatoology.app.plugin import _create_plugin
from climatoology.app.settings import CABaseSettings
from climatoology.base.artifact import (
    Artifact,
    ArtifactEnriched,
    ArtifactMetadata,
    ArtifactModality,
)
from climatoology.base.artifact_creators import create_markdown_artifact
from climatoology.base.baseoperator import AoiProperties, BaseOperator
from climatoology.base.computation import ComputationInfo, ComputationPluginInfo, ComputationResources
from climatoology.base.event import ComputationState
from climatoology.base.plugin_info import (
    Concern,
    PluginAuthor,
    PluginInfo,
    PluginInfoEnriched,
    generate_plugin_info,
)
from climatoology.store.database import migration
from climatoology.store.database.database import BackendDatabase
from climatoology.store.object_store import MinioStorage
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from freezegun import freeze_time
from kombu import Exchange, Queue
from pydantic import BaseModel, Field, HttpUrl
from pytest_alembic import Config
from pytest_postgresql.janitor import DatabaseJanitor
from semver import Version
from sqlalchemy import create_engine, text
from starlette.testclient import TestClient

from api_gateway.app.api import app
from api_gateway.app.settings import GatewaySettings
from api_gateway.sender import EXCHANGE_NAME, CelerySender

pytest_plugins = ('celery.contrib.pytest',)


@pytest.fixture
def set_basic_envs(monkeypatch):
    monkeypatch.setenv('minio_host', 'test_host')
    monkeypatch.setenv('minio_port', '1234')
    monkeypatch.setenv('minio_access_key', 'test_key')
    monkeypatch.setenv('minio_secret_key', 'test_secret')
    monkeypatch.setenv('minio_bucket', 'test_bucket')

    monkeypatch.setenv('rabbitmq_host', 'test_host')
    monkeypatch.setenv('rabbitmq_port', '1234')
    monkeypatch.setenv('rabbitmq_user', 'test_user')
    monkeypatch.setenv('rabbitmq_password', 'test_pw')

    monkeypatch.setenv('postgres_host', 'test_host')
    monkeypatch.setenv('postgres_port', '1234')
    monkeypatch.setenv('postgres_user', 'test_user')
    monkeypatch.setenv('postgres_password', 'test_password')
    monkeypatch.setenv('postgres_database', 'test_database')

    monkeypatch.setenv('deduplicate_computations', 'true')


@pytest.fixture
def default_settings(set_basic_envs) -> CABaseSettings:
    # the base settings are read from the env vars that are provided to this fixture
    # noinspection PyArgumentList
    return CABaseSettings()


@pytest.fixture
def general_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def deduplicated_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def frozen_time():
    with freeze_time(datetime(2018, 1, 1, 12, tzinfo=UTC), ignore=['celery']) as frozen_time:
        yield frozen_time


@pytest.fixture
def default_info() -> PluginInfo:
    info = generate_plugin_info(
        name='Test Plugin',
        authors=[
            PluginAuthor(
                name='John Doe',
                affiliation='HeiGIT gGmbH',
                website=HttpUrl('https://heigit.org/heigit-team/'),
            )
        ],
        icon=Path(__file__).parent / 'resources/test_icon.jpeg',
        concerns={Concern.CLIMATE_ACTION__GHG_EMISSION},
        teaser='This plugin does nothing and that is good.',
        purpose=Path(__file__).parent / 'resources/test_purpose.md',
        methodology=Path(__file__).parent / 'resources/test_methodology.md',
        sources_library=Path(__file__).parent / 'resources/test.bib',
        info_source_keys={'test2023'},
        demo_input_parameters=TestModel(id=1),
        computation_shelf_life=timedelta(days=1),
    )
    info.version = Version(3, 1, 0)
    return info


@pytest.fixture
def default_info_final(default_operator) -> PluginInfoEnriched:
    final_info = default_operator.info_enriched.model_copy(deep=True)
    final_info.assets.icon = 'assets/test_plugin/latest/ICON.png'
    return final_info


@pytest.fixture
def default_artifact(general_uuid) -> Artifact:
    return Artifact(
        name='test_name',
        modality=ArtifactModality.MARKDOWN,
        filename='test_artifact_file.md',
        summary='Test summary',
    )


@pytest.fixture
def default_artifact_enriched(default_artifact, general_uuid) -> ArtifactEnriched:
    return ArtifactEnriched(**default_artifact.model_dump(), rank=0, correlation_uuid=general_uuid)


class TestModel(BaseModel):
    id: int = Field(title='ID', description='A required integer parameter.', examples=[1])
    name: str = Field(
        title='Name', description='An optional name parameter.', examples=['John Doe'], default='John Doe'
    )
    execution_time: float = Field(
        title='Execution time',
        description='The time for the compute to run (in seconds)',
        examples=[10.0],
        default=0.0,
    )


@pytest.fixture
def default_operator(default_info, default_artifact) -> Generator[BaseOperator, None, None]:
    class TestOperator(BaseOperator[TestModel]):
        def info(self) -> PluginInfo:
            return default_info.model_copy(deep=True)

        def compute(
            self,
            resources: ComputationResources,
            aoi: shapely.MultiPolygon,
            aoi_properties: AoiProperties,
            params: TestModel,
        ) -> List[Artifact]:
            time.sleep(params.execution_time)
            artifact_text = (Path(__file__).parent / 'resources/test_purpose.md').read_text()
            artifact_metadata = ArtifactMetadata(
                name=default_artifact.name,
                summary=default_artifact.summary,
                filename='test_artifact_file',
            )
            artifact = create_markdown_artifact(
                text=artifact_text,
                metadata=artifact_metadata,
                resources=resources,
            )
            return [artifact]

    yield TestOperator()


@pytest.fixture
def default_plugin(
    celery_app, celery_worker, default_operator, default_settings, mocked_object_store, default_backend_db
) -> Generator[Celery, None, None]:
    with (
        patch('climatoology.app.plugin.Celery', return_value=celery_app),
        patch('climatoology.app.plugin.BackendDatabase', return_value=default_backend_db),
    ):
        plugin = _create_plugin(operator=default_operator, settings=default_settings)

        celery_worker.reload()
        yield plugin


@pytest.fixture
def default_aoi_feature_geojson_pydantic(
    default_aoi_pure_dict,
) -> geojson_pydantic.Feature[geojson_pydantic.MultiPolygon, AoiProperties]:
    return geojson_pydantic.Feature[geojson_pydantic.MultiPolygon, AoiProperties](**default_aoi_pure_dict)


@pytest.fixture
def default_aoi_pure_dict() -> dict:
    return {
        'type': 'Feature',
        'properties': {'name': 'test_aoi', 'id': 'test_aoi_id'},
        'geometry': {
            'type': 'MultiPolygon',
            'coordinates': [
                [
                    [
                        [0.0, 0.0],
                        [0.0, 1.0],
                        [1.0, 1.0],
                        [0.0, 0.0],
                    ]
                ]
            ],
        },
    }


@pytest.fixture
def mocked_object_store() -> Generator[dict, None, None]:
    with patch('climatoology.store.object_store.Minio') as minio_client:
        minio_storage = MinioStorage(
            host='minio.test.org',
            port=9999,
            access_key='key',
            secret_key='secret',
            secure=True,
            bucket='test_bucket',
        )
        minio_client.return_value.presigned_get_object.return_value = 'test-presigned-url'
        yield {'minio_storage': minio_storage, 'minio_client': minio_client}


@pytest.fixture
def default_computation_info(
    general_uuid, default_aoi_feature_geojson_pydantic, default_artifact_enriched, default_info_final
) -> ComputationInfo:
    return ComputationInfo(
        correlation_uuid=general_uuid,
        request_ts=datetime(2018, 1, 1, 12),
        deduplication_key=uuid.UUID('24209215-3397-e96c-2bf2-084116c66532'),
        cache_epoch=17532,
        valid_until=datetime(2018, 1, 2),
        params={'id': 1, 'name': 'John Doe', 'execution_time': 0.0},
        requested_params={'id': 1},
        aoi=default_aoi_feature_geojson_pydantic,
        artifacts=[default_artifact_enriched],
        plugin_info=ComputationPluginInfo(id=default_info_final.id, version=default_info_final.version),
        status=ComputationState.SUCCESS,
    )


@pytest.fixture
def default_sender(
    celery_app, mocked_object_store, set_basic_envs, default_backend_db
) -> Generator[CelerySender, None, None]:
    with (
        patch('api_gateway.sender.CelerySender.construct_celery_app', return_value=celery_app),
        patch(
            'api_gateway.sender.CelerySender.construct_storage',
            return_value=mocked_object_store['minio_storage'],
        ),
        patch('api_gateway.sender.BackendDatabase', return_value=default_backend_db),
    ):
        yield CelerySender()


@pytest.fixture()
def celery_worker_parameters():
    return {'hostname': 'test_plugin@hostname'}


@pytest.fixture
def celery_app(celery_app):
    # Add queue to the base celery_app, so the platform also knows about it (because we aren't running rabbitmq for real)
    compute_queue = Queue('test_plugin', Exchange(EXCHANGE_NAME), 'test_plugin')
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
def default_plugin_key(default_info) -> str:
    return f'{default_info.id};{default_info.version}'


@pytest.fixture
def backend_with_computations(
    default_backend_db,
    default_computation_info,
    default_info_final,
    deduplicated_uuid,
    set_basic_envs,
    frozen_time,
    default_plugin_key,
) -> BackendDatabase:
    default_backend_db.write_info(info=default_info_final)
    default_backend_db.register_computation(
        correlation_uuid=default_computation_info.correlation_uuid,
        requested_params=default_computation_info.requested_params,
        aoi=default_computation_info.aoi,
        plugin_key=default_plugin_key,
        computation_shelf_life=default_info_final.computation_shelf_life,
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
        computation_shelf_life=default_info_final.computation_shelf_life,
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
    app.state.settings = GatewaySettings()
    app.state.platform = default_sender
    FastAPICache.init(InMemoryBackend())
    client = TestClient(app)

    yield client
