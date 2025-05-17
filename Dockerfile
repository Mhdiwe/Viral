# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install FFmpeg and other OS-level dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    # Add any other OS packages FFmpeg or your Python libs might need
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
COPY main.py .

# Set the entry point for the functions-framework
# The Functions Framework will respect the PORT environment variable set by Cloud Run.
# The Procfile (if still present) would also work, but CMD is more direct for Docker.
CMD ["functions-framework", "--target=orchestrate_video_with_ffmpeg", "--port=8080"]
