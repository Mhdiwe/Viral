# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /workspace

# Copy only requirements.txt first to leverage Docker cache
COPY requirements.txt .

# Install dependencies, including functions-framework
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set the PORT environment variable that Cloud Run will use
ENV PORT 8080

# Explicitly define the command to run the application using Functions Framework
# This tells Functions Framework to find 'orchestrate_video_with_ffmpeg' in 'main.py'
CMD ["functions-framework", "--target=orchestrate_video_with_ffmpeg", "--source=main.py", "--port=$PORT"]
