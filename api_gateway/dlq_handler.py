import logging
from typing import Any

from celery import Celery
from celery.worker.consumer import Consumer
from climatoology.app.settings import CABaseSettings
from kombu import Exchange, Queue
from kombu.transport.pyamqp import Message

from api_gateway.app.settings import GatewaySettings

log = logging.getLogger(__name__)


class CeleryDLQHandler:
    def __init__(self):
        base_settings = CABaseSettings()
        gateway_settings = GatewaySettings()
        self.celery_app = self.create_dlq_app(base_settings, worker_concurrency=gateway_settings.dlq_worker_concurrency)

    @classmethod
    def create_dlq_app(cls, settings: CABaseSettings, worker_concurrency: int) -> Celery:
        app_name = 'dlq_handler'
        app = Celery(
            app_name,
            broker=settings.broker_connection_string,
            backend=settings.backend_connection_string,
            worker_concurrency=worker_concurrency,
        )

        cls.configure_celery_queue(settings=settings, app=app)
        Consumer.on_unknown_task = cls.handle_dead_messages

        return app

    @staticmethod
    def configure_celery_queue(settings: CABaseSettings, app: Celery) -> None:
        dlx = Exchange(settings.deadletter_exchange_name, type='direct')
        dlq = Queue(
            name=settings.deadletter_channel_name,
            exchange=dlx,
            routing_key=settings.deadletter_channel_name,
        )
        app.conf.task_queues = (dlq,)

    @staticmethod
    def handle_dead_messages(consumer: Consumer, body: Any, message: Message, exc: Exception) -> None:
        log.debug(
            f'Received dead task {message.headers["id"]} from {message.headers["task"]} '
            f'({message.headers["x-last-death-reason"]}) \n'
            f'Task sent with (args={message.payload[0]}, kwargs={message.payload[1]})'
        )

        consumer.app.backend.mark_as_revoked(
            task_id=message.headers['id'], reason=message.headers['x-last-death-reason']
        )
        message.ack()


if __name__ == '__main__':
    base_settings = CABaseSettings()
    logging.basicConfig(level=base_settings.log_level)

    dlq_handler = CeleryDLQHandler()
    dlq_handler.celery_app.start(['worker', '-n', f'{dlq_handler.celery_app.main}%h', '-l', base_settings.log_level])
