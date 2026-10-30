FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY farmwatch ./farmwatch
COPY tools ./tools
COPY config.yaml .
VOLUME ["/app/data"]
EXPOSE 8080
CMD ["python", "-m", "farmwatch.main", "--config", "config.yaml", "--dashboard", "--port", "8080"]
