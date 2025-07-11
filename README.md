## API Gateway

This package features a REST-API that serves as a gateway between the user realm and the backend of the climate action
architecture.
It provides endpoints to list available plugins, trigger computation tasks and retrieve computation results.
Each computation generates a correlation id that uniquely identifies a computation request.
Result retrieval is bound to these ids in a two-step procedure:

1. All results generated through a given id can be listed.
   The list remains empty as long as the computation is not finished or in case it failed.
2. The listed results (artifacts) provide a `store_uuid` which is a unique identifier for that element.
   The element can then be downloaded in a second API call.

For more information see the API swagger documentation.
Yet, the swagger documentation interface does not well display the `/computation/` endpoint which provides
a [WebSocket](https://en.wikipedia.org/wiki/WebSocket): `ws://localhost:8000/computation/` (trailing `/` is mandatory).
The websocket will provide status updates on computation tasks.
The optional `correlation_uuid` parameter allows you to filter events by a specific computation request.
A 3-second heartbeat is required.
To test the websocket you can use tools like [websockets-cli](https://pypi.org/project/websockets-cli/).

One example for a user realm application is
the [climate action frontend/web-app](https://gitlab.heigit.org/climate-action/web-app).

## Run

The API is embedded in a full event-driven architecture.
All interaction with that architecture is provided by
the [climatoology](https://gitlab.heigit.org/climate-action/climatoology) package.
It requires multiple services such as [minIO](https://min.io/) and [RabbitMQ](https://www.rabbitmq.com/) to be available
and the respective environment variables to be set.
The simplest way to do so, is using docker.
You can use the [infrastructure repository](https://gitlab.heigit.org/climate-action/infrastructure) to set up the
architecture.
Afterward copy [`.env.base_template`](.env.base_template) to `.env.base` and fill in the necessary environment
variables.

### Direct run

Start the api

```shell
 poetry run python api_gateway/app/api.py
```

and head to [localhost:8000](http://localhost:8000/docs) to check out the results.

Of course, you won't see much until you also launch a plugin that can answer your calls.
You can try the [plugin-blueprint](https://gitlab.heigit.org/climate-action/plugin-blueprint) or any other plugin listed
in the [infrastructure repository](https://gitlab.heigit.org/climate-action/infrastructure).

### Testing

We use [pytest](https://pytest.org) as a testing engine.
Ensure all tests are passing by running `poetry run pytest`.

#### Coverage

To get a coverage report of how much of your code is run during testing, execute
`poetry run pytest --cov`.

To get a more detailed report including which lines in each file are **not** tested,
run `poetry run pytest --cov --cov-report term-missing`


### Docker

The tool is also [Dockerised](Dockerfile).
Images are automatically built and deployed in the [CI-pipeline](.gitlab-ci.yml).

In case you want to manually build and run locally (e.g. to test a new feature in development), execute

```shell
docker build --secret id=CI_JOB_TOKEN . --tag repo.heigit.org/climate-action/api-gateway:devel
docker run --env-file .env.base --network=host repo.heigit.org/climate-action/api-gateway:devel
```

and head to the link above.

To run behind a proxy, you can configure the root path using the environment variable `ROOT_PATH`.

#### Deploy

Build the image as described above.
To push a new version to the [HeiGIT docker registry](https://repo.heigit.org) run

```shell
docker image push repo.heigit.org/climate-action/api-gateway:devel
```

### Further Optional Parameters

| env var                    | description                                    |
|----------------------------|------------------------------------------------|
| MINIO_BUCKET               | the minio bucket to use for storage            |
| MINIO_SECURE               | set to True to enable SSL in Minio connections |
| FILE_CACHE                 | location where files are temporarily stored    |
| API_GATEWAY_APP_CONFIG_DIR | The directory holding configuration files      |
| API_GATEWAY_API_PORT       | The port, the api should start under           |
| LOG_LEVEL                  | The api logging level                          |