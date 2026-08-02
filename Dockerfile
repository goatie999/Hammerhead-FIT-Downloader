FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir requests

COPY hammerhead_fit_downloader.py .

# /data holds token.json (refresh token) and state.json (backfill progress
# + last activity date) -- always mount this as a volume. FIT files land
# in /data/fit_files.
VOLUME ["/data"]

ENTRYPOINT ["python", "hammerhead_fit_downloader.py"]
CMD ["run", "--token-cache", "/data/token.json", \
     "--state-file", "/data/state.json", \
     "--out", "/data/fit_files"]
