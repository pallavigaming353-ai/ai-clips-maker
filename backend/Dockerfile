FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-core fonts-noto-extra && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --create-home --uid 10001 clipper && mkdir -p /srv/clipper-data && chown -R clipper:clipper /srv/clipper-data
USER clipper
ENV CLIPPER_DATA_DIR=/srv/clipper-data
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]
