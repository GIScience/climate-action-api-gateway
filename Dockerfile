FROM python:3.13-bookworm

ENV PACKAGE_NAME="api_gateway"

RUN useradd -ms /bin/bash gateway
USER gateway
ENV WD=/home/gateway
WORKDIR $WD

ENV POETRY_HOME="$WD/.cache/poetry"

RUN python3 -m venv $POETRY_HOME &&\
    $POETRY_HOME/bin/pip install poetry==2.*


ENV PATH="$PATH:$POETRY_HOME/bin"

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-ansi --no-interaction --without dev,test --no-root

# installing script seems to not work https://github.com/python-poetry/poetry/issues/10664
COPY run-alembic.sh run-alembic.sh
COPY conf conf
COPY README.md ./README.md
COPY $PACKAGE_NAME $PACKAGE_NAME

RUN poetry install --no-ansi --no-interaction --only-root

SHELL ["/bin/bash", "-c"]
ENTRYPOINT exec poetry run python ./${PACKAGE_NAME}/app/api.py
EXPOSE 8000
