# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /workspace

# Set environment variables for Functions Framework
# PORT will be provided by Cloud Run. Defaulting here for local testing convenience.
ENV PORT 8080
# Ensure the Functions Framework knows it's an HTTP function (though decorator should also handle)
# ENV GOOGLE_FUNCTION_SIGNATURE_TYPE http # Can be set here or in Cloud Run console
# Ensure the Functions Framework knows which function to target
# ENV GOOGLE_FUNCTION_TARGET orchestrate_video_with_ffmpeg # Can be set here or in Cloud Run console

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /workspace
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container at /workspace
COPY . .

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Define the command to run the application using Functions Framework
# This will be overridden by Cloud Run if GOOGLE_FUNCTION_TARGET env var is set there.
# Using $PORT which is an environment variable automatically set by Cloud Run.
CMD ["functions-framework", "--target=orchestrate_video_with_ffmpeg", "--port=$PORT"]
