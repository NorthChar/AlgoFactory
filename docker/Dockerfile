ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}
ARG WORKER_SHA256
ARG REQUIREMENTS_SHA256
LABEL org.algofactory.worker-sha256=${WORKER_SHA256}
LABEL org.algofactory.requirements-sha256=${REQUIREMENTS_SHA256}
COPY requirements.txt /opt/algofactory/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /opt/algofactory/requirements.txt
COPY worker.py /opt/algofactory/worker.py
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /tmp
CMD ["python", "-I", "/opt/algofactory/worker.py"]
