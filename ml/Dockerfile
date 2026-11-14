FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /service
ENV PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --create-home ml && mkdir -p artifacts && chown ml:ml artifacts
USER ml
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
