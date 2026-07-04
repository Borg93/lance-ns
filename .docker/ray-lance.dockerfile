# syntax=docker/dockerfile:1.11
# A thin CPU Ray image for the medallion compute seam: official Ray + the lance-ray Data integration.
# Not rask's GPU ray.dockerfile (that's nvidia/cuda + PyTorch for HTR). This is the minimal real Ray runtime
# for a distributed Lance read→transform→write job submitted via `ray job submit` (see make ray-demo).
# Build context = repo root (RA/rask convention):
#   docker build $(BUILD_ARGS) -f .docker/ray-lance.dockerfile -t ray-lance:dev .
FROM rayproject/ray:2.56.0-py312-cpu@sha256:2951c07de396a8b746f9c678b52c6e2282e614e00f80e6846a9ccd12945ae6b0

# Fully pinned for reproducibility — this trio is version-sensitive (lance_ray's write_lance / index paths
# target specific pylance signatures; see docs/RAY.md). --no-cache-dir keeps the layer lean; the base
# already runs as the non-root `ray` user (UID 1000).
RUN pip install --no-cache-dir "lance-ray==0.4.2" "pylance==8.0.0" "pyarrow==19.0.1"

# Bake the job so `ray job submit -- python /home/ray/jobs/ray_lance_job.py` needs no working-dir upload.
COPY scripts/ray_lance_job.py /home/ray/jobs/ray_lance_job.py

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION
LABEL org.opencontainers.image.title="ray-lance" \
      org.opencontainers.image.description="CPU Ray + lance-ray for the medallion distributed-compute demo" \
      org.opencontainers.image.source="https://github.com/Borg93/lance-ns" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"
