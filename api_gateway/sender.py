import logging
from datetime import timedelta
from enum import StrEnum
from typing import Optional, Set
from uuid import UUID

import climatoology
import geojson_pydantic
from celery import Celery
from celery.result import AsyncResult
from climatoology.app.plugin import extract_plugin_id
from climatoology.app.settings import EXCHANGE_NAME, CABaseSettings
from climatoology.base.baseoperator import AoiProperties
from climatoology.base.info import _Info
from climatoology.store.database.database import BackendDatabase
from climatoology.store.object_store import MinioStorage, Storage
from climatoology.utility.exception import VersionMismatchError
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class CacheOverrides(StrEnum):
    FOREVER = 'forever-cache'
    NEVER = 'no-cache'


class SenderSettings(BaseSettings):
    assert_plugin_version: bool = True
    task_send_sent_event: bool = True
    result_expires: Optional[int] = None
    deduplicate_computations: bool = True

    model_config = SettingsConfigDict(env_file='.env.sender')


class CelerySender:
    def __init__(self):
        sender_config = SenderSettings()

        # we require the user to set the settings via a .env file or via env variables
        # noinspection PyArgumentList
        settings = CABaseSettings()

        self.celery_app = CelerySender.construct_celery_app(settings, sender_config)

        self.assert_plugin_version = sender_config.assert_plugin_version

        self.storage = CelerySender.construct_storage(settings)

        self.backend_db = BackendDatabase(
            connection_string=settings.db_connection_string,
            user_agent=f'CeleryPlatform/{climatoology.__version__}',
            assert_db_status=True,
        )
        self.deduplicate_computations = sender_config.deduplicate_computations

    @staticmethod
    def construct_celery_app(settings: CABaseSettings, sender_config: SenderSettings) -> Celery:
        celery_app = Celery(
            'sender',
            broker=settings.broker_connection_string,
            backend=settings.backend_connection_string,
        )

        celery_app.conf.update(**sender_config.model_dump(exclude={'assert_plugin_version'}))
        return celery_app

    @staticmethod
    def construct_storage(settings: CABaseSettings) -> Storage:
        return MinioStorage(
            host=settings.minio_host,
            port=settings.minio_port,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )

    def list_active_plugins(self) -> Set[str]:
        """Retrieve a list of active plugins.

        :return: List of plugin ids
        """
        available_tasks = self.celery_app.control.inspect().registered() or dict()
        plugins = {extract_plugin_id(k) for k, v in available_tasks.items() if 'compute' in v}

        log.debug(f'Active plugins: {plugins}.')

        return plugins

    def request_info(self, plugin_id: str, ttl: int = 3) -> _Info:
        log.debug(f"Requesting 'info' from {plugin_id}.")
        info_return = self.backend_db.read_info(plugin_id=plugin_id)

        if self.assert_plugin_version and not info_return.library_version.is_compatible(climatoology.__version__):
            raise VersionMismatchError(
                f'Refusing to register plugin '
                f'{info_return.name} in version {info_return.version} due to a climatoology library '
                f'version mismatch. '
                f'Local library version: {climatoology.__version__} <-> '
                f'Plugin library version: {info_return.library_version}'
            )

        return info_return

    def send_compute_request(
        self,
        plugin_id: str,
        aoi: geojson_pydantic.Feature[geojson_pydantic.MultiPolygon, AoiProperties],
        params: dict,
        correlation_uuid: UUID,
        override_shelf_life: Optional[CacheOverrides] = None,
        task_time_limit: float = None,
        q_time: float = None,
    ) -> AsyncResult:
        # Warning: task_time_limit is currently untested in the automated testing suite due to testing configuration
        # issues. It was interactively tested at the time of implementation. Note that time limits requires the gevent
        # or prefork pool: https://docs.celeryq.dev/en/stable/userguide/workers.html#time-limits

        assert aoi.properties is not None, 'AOI properties are required'

        plugin_info = self.request_info(plugin_id)

        match override_shelf_life:
            case CacheOverrides.FOREVER:
                computation_shelf_life = None
            case CacheOverrides.NEVER:
                computation_shelf_life = timedelta(0)
            case _:
                computation_shelf_life = (
                    plugin_info.computation_shelf_life if self.deduplicate_computations else timedelta(0)
                )

        # Register the task now, before it gets queued
        deduplicated_correlation_uuid = self.backend_db.register_computation(
            plugin_id=plugin_id,
            plugin_version=plugin_info.version,
            computation_shelf_life=computation_shelf_life,
            correlation_uuid=correlation_uuid,
            requested_params=params,
            aoi=aoi,
        )

        if deduplicated_correlation_uuid == correlation_uuid:
            return self.celery_app.send_task(
                name='compute',
                kwargs={
                    'aoi': aoi.model_dump(mode='json'),
                    'params': params,
                },
                task_id=str(correlation_uuid),
                routing_key=plugin_id,
                exchange=EXCHANGE_NAME,
                time_limit=task_time_limit,
                expires=q_time,
            )
        else:
            log.info(
                f'Computation request {correlation_uuid} is deduplicated with computation {deduplicated_correlation_uuid}'
            )
            return AsyncResult(id=str(deduplicated_correlation_uuid), app=self.celery_app)
