import uuid
from unittest.mock import Mock, patch

import pytest
from amqp import basic_message
from celery import Celery
from celery.exceptions import TaskRevokedError
from celery.result import AsyncResult
from climatoology.app.plugin import EXCHANGE_NAME, _create_plugin
from kombu.transport.pyamqp import Message

from api_gateway.dlq_handler import CeleryDLQHandler


@pytest.fixture
def default_dlq_handler(db_with_tables):
    # Don't use the default celery_app fixture, because we don't want to mess with its configuration (e.g. queues)

    # Use the pytest-postgresql as backend so that task states can be updated (to revoked)
    dlq_celery_app = Celery('test_dlq_app', backend=f'db+{db_with_tables}')
    with patch('api_gateway.dlq_handler.Celery', return_value=dlq_celery_app):
        dlq_handler = CeleryDLQHandler()

    yield dlq_handler


# An 'ideal' test would be to send three compute requests to the default_plugin. The first would be started
# immediately, the second would be acknowledged by default_plugin (and then revoked after the q_time), and the third
# would be redirected to the dead letter queue. We would then test that the task gets handled by the dlq handler,
# which should mark it as revoked.

# However, rabbitmq is the one that redirects the expired task to the dead letter queue, and we aren't running a
# rabbitmq server in our tests. In this test environment, the task actually stays in the queue and is marked as
# revoked by default_plugin when it reaches the front of the queue.


def test_dlq_config_matches(
    default_dlq_handler, default_operator, default_settings, default_backend_db, mocked_object_store
):
    """Assert that the dead letter configuration for the plugin matches the queue of the dead letter handler."""

    expected_dlq = default_dlq_handler.celery_app.conf.task_queues[0]
    expected_dlx = expected_dlq.exchange.name
    expected_dlq_routing_key = expected_dlq.routing_key

    # Don't use the default plugin, which has its queue set from a pytest fixture
    with patch('climatoology.app.plugin.BackendDatabase', return_value=default_backend_db):
        plugin_with_queue = _create_plugin(default_operator, default_settings)

    plugin_queue_args = plugin_with_queue.conf.task_queues[0].queue_arguments
    plugin_dlx = plugin_queue_args['x-dead-letter-exchange']
    plugin_dlq_routing_key = plugin_queue_args['x-dead-letter-routing-key']

    assert plugin_dlx == expected_dlx
    assert plugin_dlq_routing_key == expected_dlq_routing_key


def test_dlq_handler_marks_task_revoked(default_dlq_handler):
    """Assert that tasks that arrive in the DLQ get marked as revoked"""

    correlation_uuid = str(uuid.uuid4())
    plugin_id = 'test_plugin'
    args_str = '[]'
    kwargs_str = """
        {
            'aoi': {
                'type': 'Feature',
                'geometry': {'type': 'MultiPolygon', 'coordinates': [[[]]]},
                'properties': {'name': 'name', 'id': 'id'}
            },
            'params': {}
        }
    """

    task_message = Message(
        basic_message.Message(
            body=f'[{args_str},{kwargs_str},{{"callbacks": null, "errbacks": null, "chain": null, "chord": null}},]',
            delivery_info={
                'redelivered': True,
                'exchange': 'dlx',
                'routing_key': 'deadletter',
            },
            delivery_tag=2,
            application_headers={
                'id': correlation_uuid,
                'kwargsrepr': kwargs_str,
                'lang': 'py',
                'root_id': correlation_uuid,
                'task': 'compute',
                'x-death': [
                    {
                        'reason': 'expired',
                        'queue': plugin_id,
                        'exchange': 'climatoology',
                        'routing-keys': [plugin_id],
                    }
                ],
                'x-first-death-exchange': EXCHANGE_NAME,
                'x-first-death-queue': plugin_id,
                'x-first-death-reason': 'expired',
                'x-last-death-exchange': EXCHANGE_NAME,
                'x-last-death-queue': plugin_id,
                'x-last-death-reason': 'expired',
            },
        ),
    )
    task_message.ack = Mock()

    consumer = default_dlq_handler.celery_app.amqp
    default_dlq_handler.handle_dead_messages(
        consumer=consumer, body=None, message=task_message, exc=KeyError('compute')
    )

    with pytest.raises(TaskRevokedError):
        AsyncResult(id=correlation_uuid).get(timeout=5)
