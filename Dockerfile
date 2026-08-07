FROM python:3.12-slim

RUN pip install --no-cache-dir uv

# uv defaults to hardlinking/reflink-cloning packages from its cache, which
# fails with "Resource temporarily unavailable (os error 11)" on some
# overlay/ZFS-backed Docker storage setups (e.g. TrueNAS). Copying is a
# little slower but works everywhere.
ENV UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN uv pip install --system .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["run"]
