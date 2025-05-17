FROM python:3.11-slim
WORKDIR /workspace
ENV PORT 8080
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE $PORT
CMD ["functions-framework", "--target=orchestrate_video_with_ffmpeg", "--source=main.py", "--port=$PORT"]
