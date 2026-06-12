#!/bin/sh
set -e

# Render mounts a persistent disk at /model. On first boot (or after the disk
# is wiped) it will be empty, so seed it from the model artifacts baked into
# the Docker image.
if [ -z "$(ls -A /model 2>/dev/null)" ]; then
  echo "Seeding /model from /app/seed-model ..."
  mkdir -p /model
  cp -r /app/seed-model/* /model/
fi

exec uvicorn backend:app --host 0.0.0.0 --port 8000
