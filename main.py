print("DEBUG: main.py starting to load - TOP OF FILE") # New debug line

import functions_framework
print("DEBUG: imported functions_framework")
import os
print("DEBUG: imported os")
import requests
print("DEBUG: imported requests")
import json
print("DEBUG: imported json")
import time
print("DEBUG: imported time")

try:
    from google.cloud import storage
    print("DEBUG: imported google.cloud.storage")
except ImportError as e:
    print(f"DEBUG: FAILED to import google.cloud.storage: {e}")
    # If a critical import fails, you might want the function to not even try to deploy further,
    # but for now, raising helps see the error in logs.
    # Consider if you want to raise or just log and let it fail later. For debugging, raise is good.
    raise
except Exception as e_general:
    print(f"DEBUG: UNEXPECTED ERROR importing google.cloud.storage: {e_general}")
    raise


try:
    from google.cloud import speech_v1p1beta1 as speech
    # If you were using speech.SpeechClient(), it might be from google.cloud.speech directly for v1
    # from google.cloud import speech 
    print("DEBUG: imported google.cloud.speech_v1p1beta1 as speech (or google.cloud.speech)")
except ImportError as e:
    print(f"DEBUG: FAILED to import google.cloud.speech_v1p1beta1 (or google.cloud.speech): {e}")
    raise
except Exception as e_general:
    print(f"DEBUG: UNEXPECTED ERROR importing google.cloud.speech: {e_general}")
    raise

try:
    from mutagen.mp3 import MP3
    print("DEBUG: imported mutagen.mp3")
except ImportError as e:
    print(f"DEBUG: FAILED to import mutagen.mp3: {e}")
    raise
except Exception as e_general:
    print(f"DEBUG: UNEXPECTED ERROR importing mutagen.mp3: {e_general}")
    raise

print("DEBUG: All top-level imports attempted.")

# Configuration (use environment variables in GCF for sensitive data or bucket names)
FISH_AUDIO_API_KEY_PARAM = "fish_audio_api_key" # Expect this in request JSON
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME") # Read from environment variable

if GCS_BUCKET_NAME is None:
    print("DEBUG: ERROR - GCS_BUCKET_NAME environment variable is not set!")
    # This will likely cause issues later, but let the function try to proceed to see other logs.
    # In a production setting, you might want to raise an error here.

# Initialize clients globally - this happens when the GCF instance starts/scales up.
# If any of these fail, it will prevent the function from serving requests.
try:
    storage_client = storage.Client()
    print("DEBUG: google.cloud.storage.Client() initialized successfully.")
except Exception as e:
    print(f"DEBUG: FAILED to initialize google.cloud.storage.Client(): {e}")
    storage_client = None # Set to None so later checks can see it failed
    # Depending on how critical this is for ALL paths, you might raise here.

try:
    speech_client = speech.SpeechClient()
    print("DEBUG: google.cloud.speech.SpeechClient() initialized successfully.")
except Exception as e:
    print(f"DEBUG: FAILED to initialize google.cloud.speech.SpeechClient(): {e}")
    speech_client = None
    # Depending on how critical this is for ALL paths, you might raise here.


def format_time_srt(seconds_float):
    # Converts float seconds to SRT time format HH:MM:SS,mmm
    if not isinstance(seconds_float, (int, float)) or seconds_float < 0:
        print(f"DEBUG SRT Time Format: Invalid input seconds_float: {seconds_float}")
        seconds_float = 0.0 # Default to 0 to avoid further errors

    millis = int(round((seconds_float - int(seconds_float)) * 1000))
    seconds_int = int(seconds_float) # Use a different variable name
    minutes = seconds_int // 60
    hours = minutes // 60
    seconds_val = seconds_int % 60 # Use a different variable name
    minutes %= 60
    return f"{hours:02}:{minutes:02}:{seconds_val:02},{millis:03}"

@functions_framework.http
def process_audio_for_subtitles(request):
    print("DEBUG: process_audio_for_subtitles function started.") # Log function entry

    # Check if clients were initialized
    if not storage_client:
        print("DEBUG: storage_client not initialized. Aborting.")
        return (json.dumps({"success": False, "error": "Internal server error: Storage client failed to initialize."}), 500, {'Content-Type': 'application/json'})
    if not speech_client:
        print("DEBUG: speech_client not initialized. Aborting.")
        return (json.dumps({"success": False, "error": "Internal server error: Speech client failed to initialize."}), 500, {'Content-Type': 'application/json'})
    if not GCS_BUCKET_NAME: # Check if GCS_BUCKET_NAME was loaded from env
        print("DEBUG: GCS_BUCKET_NAME is not configured. Aborting.")
        return (json.dumps({"success": False, "error": "Internal server configuration error: GCS bucket not set."}), 500, {'Content-Type': 'application/json'})


    request_json = request.get_json(silent=True)
    if not request_json:
        print("DEBUG: Invalid JSON body received.")
        return (json.dumps({"success": False, "error": "Invalid JSON body"}), 400, {'Content-Type': 'application/json'})

    print(f"DEBUG: Received request_json: {str(request_json)[:200]}...") # Log snippet of request

    script_text = request_json.get("script_text")
    fish_audio_voice_id = request_json.get("fish_audio_voice_id")
    fish_audio_api_key = request_json.get(FISH_AUDIO_API_KEY_PARAM)

    if not all([script_text, fish_audio_voice_id, fish_audio_api_key]):
        print("DEBUG: Missing required parameters in request JSON.")
        return (json.dumps({"success": False, "error": "Missing script_text, fish_audio_voice_id, or fish_audio_api_key"}), 400, {'Content-Type': 'application/json'})

    # --- 1. Call Fish.audio ---
    print("DEBUG: Calling Fish.audio API...")
    fish_audio_url = 'https://api.fish.audio/v1/tts'
    fish_payload = {"text": script_text, "format": "mp3", "reference_id": fish_audio_voice_id}
    headers = {'Authorization': f'Bearer {fish_audio_api_key}', 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'}
    
    try:
        fish_response = requests.post(fish_audio_url, json=fish_payload, headers=headers, timeout=120)
        fish_response.raise_for_status()
        if 'audio/mpeg' not in fish_response.headers.get('Content-Type', '').lower():
            raise ValueError(f"Fish.audio did not return MP3. Content-Type: {fish_response.headers.get('Content-Type','')}. Status: {fish_response.status_code}. Response: {fish_response.text[:200]}")
        mp3_content = fish_response.content
        print(f"DEBUG: Successfully fetched MP3 from Fish.audio, size: {len(mp3_content)}")
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Fish.audio API request failed: {e}")
        return (json.dumps({"success": False, "error": f"Fish.audio API request failed: {e}"}), 500, {'Content-Type': 'application/json'})
    except ValueError as e:
        print(f"DEBUG: Fish.audio content error: {e}")
        return (json.dumps({"success": False, "error": f"Fish.audio content error: {e}"}), 500, {'Content-Type': 'application/json'})

    # --- 2. Upload MP3 to GCS ---
    timestamp = int(time.time())
    gcs_blob_name = f"fish-audio-vo/vo_{timestamp}_{fish_audio_voice_id}.mp3" # Added voice_id for uniqueness
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(gcs_blob_name)
    try:
        print(f"DEBUG: Uploading Fish.audio MP3 to GCS: gs://{GCS_BUCKET_NAME}/{gcs_blob_name}")
        blob.upload_from_string(mp3_content, content_type='audio/mpeg')
        fish_audio_gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_blob_name}"
        # For public URL, bucket/object needs to be public or use signed URL. Assuming public for now.
        fish_audio_public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_blob_name}"
        print(f"DEBUG: Uploaded Fish.audio MP3 to {fish_audio_gcs_uri}. Public URL (approx): {fish_audio_public_url}")
    except Exception as e:
        print(f"DEBUG: Failed to upload to GCS: {e}")
        return (json.dumps({"success": False, "error": f"Failed to upload audio to GCS: {e}"}), 500, {'Content-Type': 'application/json'})

    # --- Get Audio Duration using Mutagen ---
    audio_duration_seconds = 0.0
    temp_mp3_path = f"/tmp/temp_vo_{timestamp}.mp3" # GCFs have a writable /tmp directory
    try:
        with open(temp_mp3_path, 'wb') as f:
            f.write(mp3_content)
        audio_file_for_duration = MP3(temp_mp3_path)
        if audio_file_for_duration.info:
             audio_duration_seconds = float(audio_file_for_duration.info.length)
        else:
            print("DEBUG Mutagen: MP3.info was None.")
        os.remove(temp_mp3_path)
        print(f"DEBUG: Audio duration from mutagen: {audio_duration_seconds}s")
    except Exception as e:
        print(f"DEBUG: Could not get audio duration using mutagen: {e}. Will rely on Speech-to-Text if possible.")
        if os.path.exists(temp_mp3_path):
            os.remove(temp_mp3_path) # Clean up

    # --- 3. Call Google Cloud Speech-to-Text ---
    # Ensure sample_rate_hertz is appropriate or let API infer for MP3
    recognition_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MP3,
        # sample_rate_hertz=16000, # For MP3, often better to let API infer. If issues, specify.
        language_code="en-US",
        enable_word_time_offsets=True,
        model="video", # "video" model often good for clear audio; "default" is also an option
        # audio_channel_count=1, # Assuming mono audio from Fish.audio
    )
    audio_source = speech.RecognitionAudio(uri=fish_audio_gcs_uri)

    try:
        print(f"DEBUG: Sending {fish_audio_gcs_uri} to Speech-to-Text API...")
        # Using long_running_recognize for robustness, though for short clips sync might be okay
        operation = speech_client.long_running_recognize(config=recognition_config, audio=audio_source)
        print("DEBUG: Waiting for Speech-to-Text operation to complete...")
        stt_timeout = 300 # 5 minutes timeout for STT
        response = operation.result(timeout=stt_timeout)
        print("DEBUG: Speech-to-Text operation completed.")
    except Exception as e:
        print(f"DEBUG: Speech-to-Text API request failed: {e}")
        # Attempt to delete the GCS object if STT fails to avoid orphaned files
        try:
            blob.delete()
            print(f"DEBUG: Deleted GCS object {gcs_blob_name} after STT failure.")
        except Exception as e_del:
            print(f"DEBUG: Failed to delete GCS object {gcs_blob_name} after STT failure: {e_del}")
        return (json.dumps({"success": False, "error": f"Speech-to-Text API request failed: {e}"}), 500, {'Content-Type': 'application/json'})

    # --- 4. Process Speech-to-Text Result & Generate SRT Data ---
    srt_segments = []
    current_line_text = ""
    current_line_start_time = -1.0
    last_word_end_time = 0.0
    max_chars_per_line = 40
    max_duration_per_line_seconds = 5.0 # Slightly shorter max line duration
    min_duration_per_line_seconds = 0.5

    print(f"DEBUG: Processing {len(response.results)} STT results.")
    for result_index, result in enumerate(response.results):
        if not result.alternatives:
            print(f"DEBUG: STT Result {result_index} has no alternatives.")
            continue
        
        alternative = result.alternatives[0]
        if not alternative.words:
            print(f"DEBUG: STT Result {result_index}, Alternative 0 has no words.")
            continue
        
        print(f"DEBUG: Processing {len(alternative.words)} words in STT Result {result_index}.")
        for word_info_index, word_info in enumerate(alternative.words):
            word = word_info.word
            start_time = word_info.start_time.total_seconds()
            end_time = word_info.end_time.total_seconds()

            if current_line_start_time < 0: # Start of a new subtitle line
                current_line_start_time = start_time

            # Check if adding word exceeds char limit OR current line duration is too long OR natural sentence break
            # A more sophisticated approach might look for punctuation .!? to force a break.
            force_break = (word.endswith(('.', '!', '?')) and len(current_line_text) > 10) # Break after punctuation if line has some content

            if current_line_text and \
               (len(current_line_text + " " + word) > max_chars_per_line or \
                (end_time - current_line_start_time) > max_duration_per_line_seconds or \
                force_break):
                
                line_actual_end_time = last_word_end_time # End line at the end of the *previous* word
                line_duration = line_actual_end_time - current_line_start_time
                if line_duration >= min_duration_per_line_seconds:
                    srt_segments.append({
                        "text": current_line_text.strip(),
                        "start_seconds": round(current_line_start_time, 3),
                        "end_seconds": round(line_actual_end_time, 3),
                        "duration_seconds": round(line_duration, 3)
                    })
                # Start new line with current word
                current_line_text = word
                current_line_start_time = start_time
            else:
                current_line_text += (" " + word) if current_line_text else word
            
            last_word_end_time = end_time

    # Add any remaining line
    if current_line_text and current_line_start_time >= 0:
        line_duration = last_word_end_time - current_line_start_time
        if line_duration >= min_duration_per_line_seconds:
            srt_segments.append({
                "text": current_line_text.strip(),
                "start_seconds": round(current_line_start_time, 3),
                "end_seconds": round(last_word_end_time, 3),
                "duration_seconds": round(line_duration, 3)
            })
    
    # If audio_duration_seconds wasn't set reliably by mutagen, try to use last word's end time
    if audio_duration_seconds <= 0.1 and last_word_end_time > 0:
        audio_duration_seconds = last_word_end_time
        print(f"DEBUG: Updated audio_duration_seconds from STT last word end time: {audio_duration_seconds}s")
    elif audio_duration_seconds <= 0.1: # Absolute fallback if all else fails for duration
        audio_duration_seconds = 10.0 # Default to 10s if unknown
        print(f"DEBUG: Using fallback audio_duration_seconds: {audio_duration_seconds}s")


    print(f"DEBUG: Generated {len(srt_segments)} SRT segments.")
    final_response_data = {
        "success": True,
        "fish_audio_gcs_uri": fish_audio_gcs_uri,
        "fish_audio_public_url": fish_audio_public_url, # This assumes bucket is public or signed URL is generated later
        "audio_duration_seconds": round(audio_duration_seconds, 3),
        "srt_segments": srt_segments
    }
    print(f"DEBUG: Returning success response: {str(final_response_data)[:300]}...")
    return (json.dumps(final_response_data), 200, {'Content-Type': 'application/json'})

print("DEBUG: main.py loaded and process_audio_for_subtitles function defined.")
