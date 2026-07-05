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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

EXPOSE 8080

CMD ["./entrypoint.sh"]
