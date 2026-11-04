# Pinned, replayable GreenBench environment for Linux hosts.
#
#   docker build -t greenbench .
#   docker run --rm --privileged -v /sys/class/powercap:/sys/class/powercap:ro \
#              -v "$PWD/results:/data/results" greenbench run --preset standard
#   docker run --rm -p 8000:8000 -v "$PWD/results:/data/results" greenbench serve --host 0.0.0.0
#
# RAPL counters are only visible on bare-metal Linux hosts. Under Docker Desktop (Windows/macOS)
# or in a VM, GreenBench falls back to its software model and records that it did.
FROM python:3.11.9-slim

WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY docs ./docs
RUN pip install --no-cache-dir --no-deps .

ENV GREENBENCH_HOME=/data \
    GREENBENCH_RESULTS=/data/results \
    GREENBENCH_DOCS=/app/docs \
    PYTHONHASHSEED=0
VOLUME /data
EXPOSE 8000
ENTRYPOINT ["greenbench"]
CMD ["serve", "--host", "0.0.0.0"]
