FROM python:3.12-slim

WORKDIR /app

# Doppler CLI — installed from Doppler's GPG-signed apt repo (not curl|sh) and
# version-pinned for reproducible builds. entrypoint.sh uses it to inject
# secrets via `doppler run` when DOPPLER_TOKEN is set; without a token the image
# still boots on plain environment variables. Bump DOPPLER_CLI_VERSION to adopt
# a new CLI release (verify `doppler run` behaviour per docs/doppler-migration.md).
ARG DOPPLER_CLI_VERSION=3.76.0
RUN apt-get update && apt-get install -y --no-install-recommends \
        apt-transport-https ca-certificates curl gnupg && \
    curl -sLf --retry 3 --tlsv1.2 --proto '=https' \
        'https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key' \
        | gpg --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg && \
    echo 'deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main' \
        > /etc/apt/sources.list.d/doppler-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends "doppler=$DOPPLER_CLI_VERSION" && \
    apt-get purge -y --auto-remove curl gnupg && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies — installed by uv from the committed lock, so a build gets
# exactly the tested set rather than whatever PyPI resolves at push time.
# `--locked` fails the build if pyproject.toml and uv.lock disagree; `--no-dev`
# leaves the test tooling out. uv itself comes from PyPI (already a build
# dependency) at a pinned version, and stays in the image's system Python.
# UV_PYTHON_* make uv use the image's interpreter and fail loudly if it ever
# stops matching requires-python, instead of fetching another one.
ARG UV_VERSION=0.10.7
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir "uv==$UV_VERSION"
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-cache
# entrypoint.sh calls bare `flask` and `gunicorn` (also through `doppler run`,
# which inherits PATH), so the project environment goes first on PATH.
ENV PATH="/app/.venv/bin:$PATH"

COPY . .
RUN chmod +x entrypoint.sh

EXPOSE 8080

CMD ["./entrypoint.sh"]
