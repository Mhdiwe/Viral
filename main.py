import functions_framework
import os
import requests # For Fish.audio
from google.cloud import storage
from google.cloud import speech_v1p1beta1 as speech # Or v1, v1p1beta1 has more features sometimes
import json
import time
from mutagen.mp3 import MP3 # For getting MP3 duration if S2T doesn't provide total

# Configuration (use environment variables in GCF)
FISH_AUDIO_API_KEY_PARAM = "fish_audio_api_key" # Expect this in request
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "your-gcs-bucket-for-vvc")

# Initialize clients (globally or within function)
storage_client = storage.Client()
speech_client = speech.SpeechClient()

def format_time_srt(seconds_float):
    # Converts float seconds to SRT time format HH:MM:SS,mmm
    millis = int(round((seconds_float - int(seconds_float)) * 1000))
    seconds = int(seconds_float)
    minutes = seconds // 60
    hours = minutes // 60
    seconds %= 60
    minutes %= 60
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

@functions_framework.http
def process_audio_for_subtitles(request):
    request_json = request.get_json(silent=True)
    if not request_json:
        return (json.dumps({"success": False, "error": "Invalid JSON body"}), 400, {'Content-Type': 'application/json'})

    script_text = request_json.get("script_text")
    fish_audio_voice_id = request_json.get("fish_audio_voice_id")
    fish_audio_api_key = request_json.get(FISH_AUDIO_API_KEY_PARAM) # Get from request for now

    if not all([script_text, fish_audio_voice_id, fish_audio_api_key]):
        return (json.dumps({"success": False, "error": "Missing script_text, fish_audio_voice_id, or fish_audio_api_key"}), 400, {'Content-Type': 'application/json'})

    # --- 1. Call Fish.audio ---
    fish_audio_url = 'https://api.fish.audio/v1/tts'
    fish_payload = {"text": script_text, "format": "mp3", "reference_id": fish_audio_voice_id}
    headers = {'Authorization': f'Bearer {fish_audio_api_key}', 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'}
    
    try:
        fish_response = requests.post(fish_audio_url, json=fish_payload, headers=headers, timeout=120)
        fish_response.raise_for_status() # Raise HTTPError for bad responses (4XX or 5XX)
        if 'audio/mpeg' not in fish_response.headers.get('Content-Type', '').lower():
            raise ValueError(f"Fish.audio did not return MP3. Content-Type: {fish_response.headers.get('Content-Type','')}. Response: {fish_response.text[:200]}")
        mp3_content = fish_response.content
        print(f"Successfully fetched MP3 from Fish.audio, size: {len(mp3_content)}")
    except requests.exceptions.RequestException as e:
        print(f"Fish.audio API request failed: {e}")
        return (json.dumps({"success": False, "error": f"Fish.audio API request failed: {e}"}), 500, {'Content-Type': 'application/json'})
    except ValueError as e:
        print(f"Fish.audio content error: {e}")
        return (json.dumps({"success": False, "error": f"Fish.audio content error: {e}"}), 500, {'Content-Type': 'application/json'})


    # --- 2. Upload MP3 to GCS ---
    timestamp = int(time.time())
    gcs_blob_name = f"fish-audio-vo/vo_{timestamp}.mp3"
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(gcs_blob_name)
    try:
        blob.upload_from_string(mp3_content, content_type='audio/mpeg')
        fish_audio_gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_blob_name}"
        fish_audio_public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_blob_name}" # Assumes public bucket or signed URL needed later
        print(f"Uploaded Fish.audio MP3 to {fish_audio_gcs_uri}")
    except Exception as e:
        print(f"Failed to upload to GCS: {e}")
        return (json.dumps({"success": False, "error": f"Failed to upload audio to GCS: {e}"}), 500, {'Content-Type': 'application/json'})

    # --- Get Audio Duration ---
    audio_duration_seconds = 0
    try:
        # Download to /tmp for mutagen to analyze (or use GCS path if library supports it)
        temp_mp3_path = f"/tmp/temp_vo_{timestamp}.mp3"
        blob.download_to_filename(temp_mp3_path)
        audio_file_for_duration = MP3(temp_mp3_path)
        audio_duration_seconds = float(audio_file_for_duration.info.length)
        os.remove(temp_mp3_path)
        print(f"Audio duration from mutagen: {audio_duration_seconds}s")
    except Exception as e:
        print(f"Could not get audio duration using mutagen: {e}. Speech-to-Text might provide it.")
        # Fallback if mutagen fails, STT response might have total billed time
        
    # --- 3. Call Google Cloud Speech-to-Text ---
    recognition_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MP3, # If MP3, otherwise LINEAR16 for WAV
        sample_rate_hertz=16000, # Common for MP3s from TTS, but verify Fish.audio output. For MP3, STT often infers.
        language_code="en-US",  # Or make this a parameter
        enable_word_time_offsets=True,
        # model="video", # or "phone_call" or default. "video" is good for clearer audio.
    )
    audio_source = speech.RecognitionAudio(uri=fish_audio_gcs_uri)

    try:
        print(f"Sending {fish_audio_gcs_uri} to Speech-to-Text API...")
        operation = speech_client.long_running_recognize(config=recognition_config, audio=audio_source)
        print("Waiting for Speech-to-Text operation to complete...")
        response = operation.result(timeout=300) # Adjust timeout as needed
        print("Speech-to-Text operation completed.")
    except Exception as e:
        print(f"Speech-to-Text API request failed: {e}")
        return (json.dumps({"success": False, "error": f"Speech-to-Text API request failed: {e}"}), 500, {'Content-Type': 'application/json'})

    # --- 4. Process Speech-to-Text Result & Generate SRT Data ---
    srt_segments = []
    current_line = ""
    line_start_time = -1
    max_chars_per_line = 42 # Typical subtitle character limit
    max_duration_per_line_seconds = 7.0 # Max duration for a single subtitle line

    for result in response.results:
        if not result.alternatives:
            continue
        
        alternative = result.alternatives[0]
        if not alternative.words:
            continue

        for word_info in alternative.words:
            word = word_info.word
            start_time = word_info.start_time.total_seconds()
            end_time = word_info.end_time.total_seconds()

            if line_start_time == -1: # Start of a new line
                line_start_time = start_time

            # Check if adding word exceeds char limit or if current line duration is too long
            if current_line and \
               (len(current_line + " " + word) > max_chars_per_line or \
                (start_time - line_start_time) > max_duration_per_line_seconds):
                # Finalize current line
                line_end_time = prev_word_end_time # Use end time of previous word
                srt_segments.append({
                    "text": current_line.strip(),
                    "start_seconds": round(line_start_time, 3),
                    "end_seconds": round(line_end_time, 3),
                    "duration_seconds": round(line_end_time - line_start_time, 3)
                })
                # Start new line with current word
                current_line = word
                line_start_time = start_time
            else:
                current_line += (" " + word) if current_line else word
            
            prev_word_end_time = end_time

    # Add any remaining line
    if current_line:
        srt_segments.append({
            "text": current_line.strip(),
            "start_seconds": round(line_start_time, 3),
            "end_seconds": round(prev_word_end_time, 3), # Use the end time of the very last word
            "duration_seconds": round(prev_word_end_time - line_start_time, 3)
        })
    
    if not srt_segments and response.results and response.results[0].alternatives: # Handle case of single very long utterance
        full_transcript = response.results[0].alternatives[0].transcript
        if full_transcript:
             # If audio_duration_seconds wasn't set by mutagen, try to get total duration from STT results
             if audio_duration_seconds == 0 and response.results[-1].alternatives[0].words:
                audio_duration_seconds = response.results[-1].alternatives[0].words[-1].end_time.total_seconds()

             srt_segments.append({
                "text": full_transcript.strip(),
                "start_seconds": 0.0,
                "end_seconds": round(audio_duration_seconds, 3),
                "duration_seconds": round(audio_duration_seconds, 3)
            })


    print(f"Generated {len(srt_segments)} SRT segments.")
    if audio_duration_seconds == 0 and srt_segments: # Final attempt to get duration if mutagen failed
        audio_duration_seconds = srt_segments[-1]['end_seconds']


    return (json.dumps({
        "success": True,
        "fish_audio_gcs_uri": fish_audio_gcs_uri,
        "fish_audio_public_url": fish_audio_public_url,
        "audio_duration_seconds": round(audio_duration_seconds, 3),
        "srt_segments": srt_segments
    }), 200, {'Content-Type': 'application/json'})
