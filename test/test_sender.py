import uuid
from typing import List
from unittest.mock import ANY, Mock, patch

import pytest
import shapely
from celery.exceptions import TaskRevokedError
from celery.result import AsyncResult
from climatoology.app.plugin import _create_plugin
from climatoology.base.artifact import _Artifact
from climatoology.base.baseoperator import AoiProperties, BaseOperator
from climatoology.base.computation import ComputationResources
from climatoology.base.info import _Info
from climatoology.store.object_store import ComputationInfo
from climatoology.utility.exception import (
    ClimatoologyUserError,
    InputValidationError,
    VersionMismatchError,
)
from semver import Version

from api_gateway.sender import EXCHANGE_NAME, CacheOverrides, CelerySender
from test.conftest import TestModel


def test_sender_has_storage(default_sender):
    assert default_sender.storage


def test_list_default_active_plugins(default_sender, celery_worker):
    computed_plugins = default_sender.list_active_plugins()
    assert computed_plugins == set()


def test_list_no_active_plugins(default_sender):
    computed_plugins = default_sender.list_active_plugins()
    assert computed_plugins == set()


def test_list_active_plugins(default_sender, celery_worker, default_plugin):
    computed_plugins = default_sender.list_active_plugins()

    expected_plugins = {celery_worker.hostname.split('@')[0]}

    assert computed_plugins == expected_plugins


def test_request_info(default_sender, default_info_final, default_plugin, celery_worker):
    computed_info = default_sender.request_info(plugin_id='test_plugin')
    assert computed_info == default_info_final


@patch('climatoology.__version__', Version(1, 0, 0))
def test_request_info_plugin_version_assert(default_sender, default_info, default_plugin, celery_worker):
    with pytest.raises(VersionMismatchError, match='Refusing to register plugin.*'):
        default_sender.request_info(plugin_id='test_plugin')


def test_send_compute(
    default_sender,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    general_uuid,
    default_artifact,
    celery_app,
):
    mocked_app = Mock(side_effect=celery_app)
    default_sender.celery_app = mocked_app

    _ = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1, 'name': 'John Doe'},
        correlation_uuid=general_uuid,
    )

    mocked_app.send_task.assert_called_once_with(
        name='compute',
        kwargs={
            'aoi': {
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
            },
            'params': {'id': 1, 'name': 'John Doe'},
        },
        task_id=str(general_uuid),
        routing_key='test_plugin@_',
        exchange=EXCHANGE_NAME,
        time_limit=None,
        expires=None,
    )


def test_send_compute_writes_to_backend(
    default_sender,
    default_aoi_feature_geojson_pydantic,
    general_uuid,
    default_plugin,
):
    pre_compute = default_sender.backend_db.read_computation(correlation_uuid=general_uuid)
    assert pre_compute is None

    _ = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={},
        correlation_uuid=general_uuid,
    )

    stored_computation = default_sender.backend_db.read_computation(correlation_uuid=general_uuid)
    assert stored_computation.correlation_uuid == general_uuid


def test_send_compute_produces_result(
    default_sender,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    general_uuid,
    default_computation_info,
    frozen_time,
):
    expected_computation_info = default_computation_info.model_copy(deep=True)
    # TODO: discuss this
    # We no longer set the status to success in the computation info response sent as the task result, because we are
    # relying on the celery states instead. But, even though we aren't recording this status in our tables anymore, it
    # might make sense to still return success in the object returned from the task?
    expected_computation_info.status = ANY

    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1},
        correlation_uuid=general_uuid,
    )

    assert isinstance(result, AsyncResult)
    computation_info = result.get(timeout=5)
    computation_info = ComputationInfo.model_validate(computation_info)

    assert computation_info == expected_computation_info


def test_send_compute_unless_deduplicated(
    default_sender,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    celery_worker,
    default_computation_info,
    celery_app,
    frozen_time,
):
    first_correlation_uuid = uuid.uuid4()
    second_correlation_uuid = uuid.uuid4()

    _ = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1},
        correlation_uuid=first_correlation_uuid,
    )
    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1},
        correlation_uuid=second_correlation_uuid,
    )

    assert isinstance(result, AsyncResult)
    computation_info = result.get(timeout=5)

    computation_info = ComputationInfo.model_validate(computation_info)
    assert computation_info.correlation_uuid == first_correlation_uuid


def test_send_compute_with_cache_override(
    default_sender,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    celery_worker,
    general_uuid,
    celery_app,
    frozen_time,
):
    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1},
        correlation_uuid=general_uuid,
        override_shelf_life=CacheOverrides.FOREVER,
    )

    computation_info = result.get(timeout=5)
    computation_info = ComputationInfo.model_validate(computation_info)

    assert computation_info.cache_epoch == 0


def test_send_compute_state_receives_input_validation_error(
    default_sender,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    celery_worker,
    general_uuid,
    default_artifact,
    celery_app,
):
    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 'test_invalid_id', 'name': 'John Doe'},
        correlation_uuid=general_uuid,
    )

    assert isinstance(result, AsyncResult)

    with pytest.raises(InputValidationError):
        _ = result.get(timeout=5)

    assert result.state == 'FAILURE'
    assert (
        str(result.info)
        == 'ID: Input should be a valid integer, unable to parse string as an integer. You provided: test_invalid_id.'
    )


def test_send_compute_input_validation_error_is_cached(
    default_sender,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    celery_worker,
    general_uuid,
    default_artifact,
    celery_app,
    default_backend_db,
):
    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 'test_invalid_id', 'name': 'John Doe'},
        correlation_uuid=general_uuid,
    )

    with pytest.raises(InputValidationError):
        _ = result.get(timeout=5)

    stored_computation_info = default_backend_db.read_computation(general_uuid)
    assert stored_computation_info.cache_epoch == 0


def test_send_compute_state_receives_ClimatoologyUserError(  # noqa: N802 - allow capitalisation in function name
    default_info,
    celery_app,
    celery_worker,
    default_settings,
    default_aoi_feature_geojson_pydantic,
    default_sender,
    default_backend_db,
):
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
            raise ClimatoologyUserError('Error message to store for the user')

    operator = TestOperator()
    with (
        patch('climatoology.app.plugin.Celery', return_value=celery_app),
        patch('climatoology.app.plugin.BackendDatabase', return_value=default_backend_db),
    ):
        _ = _create_plugin(operator=operator, settings=default_settings)
        celery_worker.reload()

    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1, 'name': 'John Doe'},
        correlation_uuid=uuid.uuid4(),
    )

    assert isinstance(result, AsyncResult)
    with pytest.raises(ClimatoologyUserError):
        _ = result.get(timeout=5)

    assert result.state == 'FAILURE'
    assert str(result.info) == 'Error message to store for the user'


def test_send_compute_ClimatoologyUserError_is_not_cached(  # noqa: N802
    default_info,
    celery_app,
    celery_worker,
    default_settings,
    default_aoi_feature_geojson_pydantic,
    default_sender,
    default_backend_db,
):
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
            raise ClimatoologyUserError('Error message to store for the user')

    operator = TestOperator()
    with (
        patch('climatoology.app.plugin.Celery', return_value=celery_app),
        patch('climatoology.app.plugin.BackendDatabase', return_value=default_backend_db),
    ):
        _ = _create_plugin(operator=operator, settings=default_settings)
        celery_worker.reload()

    correlation_uuid = uuid.uuid4()
    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1, 'name': 'John Doe'},
        correlation_uuid=correlation_uuid,
    )

    with pytest.raises(ClimatoologyUserError):
        _ = result.get(timeout=5)

    stored_computation_info = default_backend_db.read_computation(correlation_uuid)
    assert stored_computation_info.cache_epoch is None


def test_send_compute_artifact_errors_invalidate_cache(
    default_info,
    default_artifact,
    celery_app,
    celery_worker,
    default_settings,
    default_aoi_feature_geojson_pydantic,
    default_sender,
    default_backend_db,
    general_uuid,
):
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
            with self.catch_exceptions('failing_indicator', resources):
                raise ClimatoologyUserError()

            return [default_artifact]

    operator = TestOperator()
    with (
        patch('climatoology.app.plugin.Celery', return_value=celery_app),
        patch('climatoology.app.plugin.BackendDatabase', return_value=default_backend_db),
    ):
        _ = _create_plugin(operator=operator, settings=default_settings)
        celery_worker.reload()

    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1, 'name': 'John Doe'},
        correlation_uuid=general_uuid,
    )
    _ = result.get(timeout=5)

    stored_computation_info = default_backend_db.read_computation(general_uuid)
    assert stored_computation_info.cache_epoch is None


def test_send_compute_uses_settings_deduplication_override(
    monkeypatch,
    celery_app,
    mocked_object_store,
    default_backend_db,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    general_uuid,
    frozen_time,
):
    monkeypatch.setenv('deduplicate_computations', 'false')
    with (
        patch('api_gateway.sender.CelerySender.construct_celery_app', return_value=celery_app),
        patch(
            'api_gateway.sender.CelerySender.construct_storage',
            return_value=mocked_object_store,
        ),
        patch('api_gateway.sender.BackendDatabase', return_value=default_backend_db),
    ):
        sender = CelerySender()

    result = sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1},
        correlation_uuid=general_uuid,
    )

    computation_info = result.get(timeout=5)
    computation_info = ComputationInfo.model_validate(computation_info)

    assert computation_info.cache_epoch is None


def test_send_compute_reaches_worker(
    default_sender,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    celery_worker,
    general_uuid,
    default_artifact,
    celery_app,
):
    previous_computations = celery_worker.stats()['total'].get('compute')

    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1, 'name': 'John Doe'},
        correlation_uuid=general_uuid,
    )

    _ = result.get(timeout=5)
    assert celery_worker.stats()['total'].get('compute') == (previous_computations + 1)


def test_send_compute_before_expiry_runs(
    default_backend_db,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    general_uuid,
    default_sender,
    default_artifact,
):
    result = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1, 'execution_time': 2},
        correlation_uuid=general_uuid,
        q_time=1,
    )

    _ = result.get(timeout=5)
    assert result.state == 'SUCCESS'

    # check db
    computation_info = default_backend_db.read_computation(general_uuid)
    assert len(computation_info.artifacts) == 1


def test_send_compute_expires_in_queue(
    default_backend_db,
    default_plugin,
    default_aoi_feature_geojson_pydantic,
    general_uuid,
    default_sender,
):
    blocker_uuid = uuid.uuid4()
    blocker_task = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 1, 'execution_time': 1},
        correlation_uuid=blocker_uuid,
    )
    waiter_task = default_sender.send_compute_request(
        plugin_id='test_plugin',
        aoi=default_aoi_feature_geojson_pydantic,
        params={'id': 2, 'execution_time': 0},
        correlation_uuid=general_uuid,
        q_time=0.5,
    )

    _ = blocker_task.get(timeout=5)
    with pytest.raises(TaskRevokedError):
        _ = waiter_task.get(timeout=5)

    # check db
    computation_info = default_backend_db.read_computation(general_uuid)
    assert computation_info.cache_epoch is None
