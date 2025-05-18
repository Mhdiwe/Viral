FROM python:3.11-slim
WORKDIR /workspace

# Install FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT, but functions-framework needs it too
# ENV PORT 8080 # You can set this if needed, or rely on $PORT from CMD/entrypoint args
EXPOSE 8080 # Or $PORT if you consistently use that. 8080 is fine.

# NO CMD or ENTRYPOINT here - we will set it in cloudbuild.yaml
