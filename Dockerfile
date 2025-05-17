# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /workspace

# Set environment variables for Functions Framework
# PORT will be provided by Cloud Run.
ENV PORT 8080

# Install FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /workspace
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container at /workspace
# This includes main.py
COPY . .

# Make port $PORT available to the world outside this container
# Cloud Run sets $PORT, typically 8080.
EXPOSE $PORT

# Define the command to run the application using Functions Framework.
# This is critical. Ensure --target is correct.
CMD ["functions-framework", "--target=orchestrate_video_with_ffmpeg", "--port=$PORT"]
