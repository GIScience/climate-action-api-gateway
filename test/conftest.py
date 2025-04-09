import uuid
from pathlib import Path
from typing import Generator, List
from unittest.mock import patch

import pytest
import shapely
from celery import Celery
from climatoology.app.platform import CeleryPlatform
from climatoology.app.plugin import _create_plugin
from climatoology.app.settings import CABaseSettings
from climatoology.base.artifact import ArtifactModality, _Artifact
from climatoology.base.baseoperator import AoiProperties, BaseOperator
from climatoology.base.computation import ComputationResources
from climatoology.base.info import Assets, Concern, PluginAuthor, _Info, generate_plugin_info
from climatoology.store.object_store import MinioStorage
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from pydantic import BaseModel, Field, HttpUrl
from semver import Version
from starlette.testclient import TestClient

from api_gateway.app.api import app

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


@pytest.fixture
def general_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def celery_config():
    return {'worker_direct': True}


@pytest.fixture(scope='session')
def celery_worker_parameters():
    return {'hostname': 'test_plugin@_'}


@pytest.fixture
def default_settings(set_basic_envs) -> CABaseSettings:
    # the base settings are read from the env vars that are provided to this fixture
    # noinspection PyArgumentList
    return CABaseSettings()


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


class TestModel(BaseModel):
    id: int = Field(title='ID', description='A required integer parameter.', examples=[1])
    name: str = Field(
        title='Name', description='An optional name parameter.', examples=['John Doe'], default='John Doe'
    )


@pytest.fixture
def default_info() -> _Info:
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
        version=Version.parse('3.1.0'),
        concerns={Concern.CLIMATE_ACTION__GHG_EMISSION},
        purpose=Path(__file__).parent / 'resources/test_purpose.md',
        methodology=Path(__file__).parent / 'resources/test_methodology.md',
        sources=Path(__file__).parent / 'resources/test.bib',
        demo_input_parameters=TestModel(id=1),
        demo_aoi=Path(__file__).parent / 'resources/test_aoi.geojson',
    )
    return info


@pytest.fixture
def default_info_final(default_info) -> _Info:
    default_info_final = default_info.model_copy()
    default_info_final.assets = Assets(icon='assets/test_plugin/latest/ICON.jpeg')
    default_info_final.operator_schema = {
        'properties': {
            'id': {'description': 'A required integer parameter.', 'examples': [1], 'title': 'ID', 'type': 'integer'},
            'name': {
                'default': 'John Doe',
                'description': 'An optional name parameter.',
                'examples': ['John Doe'],
                'title': 'Name',
                'type': 'string',
            },
        },
        'required': ['id'],
        'title': 'TestModel',
        'type': 'object',
    }

    return default_info_final


@pytest.fixture
def default_artifact(general_uuid) -> _Artifact:
    return _Artifact(
        name='test_name',
        modality=ArtifactModality.MAP_LAYER_GEOJSON,
        file_path=Path(__file__).parent / 'test_file.tiff',
        summary='Test summary',
        description='Test description',
        correlation_uuid=general_uuid,
        store_id=f'{general_uuid}_test_file.tiff',
    )


@pytest.fixture
def default_operator(default_info, default_artifact) -> Generator[BaseOperator, None, None]:
    class TestOperator(BaseOperator[TestModel]):
        def info(self) -> _Info:
            return default_info.model_copy()

        def compute(
            self,
            resources: ComputationResources,
            aoi: shapely.MultiPolygon,
            aoi_properties: AoiProperties,
            params: TestModel,
        ) -> List[_Artifact]:
            return [default_artifact]

    yield TestOperator()


@pytest.fixture
def default_plugin(
    celery_app, celery_worker, default_operator, default_settings, mocked_object_store
) -> Generator[Celery, None, None]:
    with patch('climatoology.app.plugin.Celery', return_value=celery_app):
        plugin = _create_plugin(operator=default_operator, settings=default_settings)

        celery_worker.reload()
        yield plugin


@pytest.fixture
def default_platform_connection(
    celery_app, mocked_object_store, set_basic_envs
) -> Generator[CeleryPlatform, None, None]:
    with (
        patch('climatoology.app.platform.CeleryPlatform.construct_celery_app', return_value=celery_app),
        patch(
            'climatoology.app.platform.CeleryPlatform.construct_storage',
            return_value=mocked_object_store['minio_storage'],
        ),
    ):
        yield CeleryPlatform()


@pytest.fixture
def mocked_client(default_platform_connection) -> Generator[TestClient, None, None]:
    FastAPICache.init(InMemoryBackend())
    app.state.platform = default_platform_connection
    client = TestClient(app)

    yield client


@pytest.fixture
def default_aoi() -> dict:
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
