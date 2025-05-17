print("DEBUG: main.py starting to load - GCF for Shotstack Assembly")

import functions_framework
print("DEBUG: imported functions_framework")
import os
print("DEBUG: imported os")
import requests # For Fish.audio and Shotstack API
print("DEBUG: imported requests")
import json
print("DEBUG: imported json")
import time
print("DEBUG: imported time")
# Removed: import io (was for DALL-E image bytes)

try:
    from google.cloud import storage
    print("DEBUG: imported google.cloud.storage")
except Exception as e_general:
    print(f"DEBUG: CRITICAL ERROR importing google.cloud.storage: {e_general}")
    raise

try:
    from google.cloud import speech_v1p1beta1 as speech
    print("DEBUG: imported google.cloud.speech_v1p1beta1 as speech")
except Exception as e_general:
    print(f"DEBUG: CRITICAL ERROR importing google.cloud.speech: {e_general}")
    raise

try:
    from mutagen.mp3 import MP3
    print("DEBUG: imported mutagen.mp3")
except Exception as e_general:
    print(f"DEBUG: CRITICAL ERROR importing mutagen.mp3: {e_general}")
    raise

print("DEBUG: All top-level imports attempted.")

# Configuration
FISH_AUDIO_API_KEY_PARAM = "fish_audio_api_key"
SHOTSTACK_API_KEY_PARAM = "shotstack_api_key"
SHOTSTACK_ENV_PARAM = "shotstack_environment"
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

storage_client = None
speech_client = None
try:
    storage_client = storage.Client()
    print("DEBUG: google.cloud.storage.Client() initialized successfully.")
except Exception as e:
    print(f"DEBUG: CRITICAL - FAILED to initialize google.cloud.storage.Client(): {e}")
    # This function cannot operate without storage client
    # In a real scenario, the GCF would fail to deploy/start if this is at global scope and fails

try:
    speech_client = speech.SpeechClient()
    print("DEBUG: google.cloud.speech.SpeechClient() initialized successfully.")
except Exception as e:
    print(f"DEBUG: CRITICAL - FAILED to initialize google.cloud.speech.SpeechClient(): {e}")

def format_time_srt(seconds_float):
    if not isinstance(seconds_float, (int, float)) or seconds_float < 0: seconds_float = 0.0
    millis = int(round((seconds_float - int(seconds_float)) * 1000))
    seconds_int = int(seconds_float); minutes = seconds_int // 60; hours = minutes // 60
    seconds_val = seconds_int % 60; minutes %= 60
    return f"{hours:02}:{minutes:02}:{seconds_val:02},{millis:03}"

# --- Helper functions from WordPress PHP, adapted for Python & Shotstack JSON ---
def map_shotstack_voice_py(vvc_voice_id): # Renamed to avoid conflict if ever in same env
    voice_map = {
        '802e3bc2b27e49c2995d23ef70e6ac89': 'Amy', 'f8dfe9c83081432386f143e2fe9767ef': 'Brian',
        '3b7e2226b65941a4af6c3fc6609b8361': 'Emma', '728f6ff2240d49308e8137ffe66008e2': 'Matthew',
        '0b74ead073f2474a904f69033535b98e': 'Olivia', '16b2981936f34328886f4f230e7fe196': 'Joanna',
        '3ce4bfc65d0e483aa880073d2a589745': 'Salli', '9af2433a5d1d4d728fb4c9c82c565315': 'Kimberly',
        'af8a334a68a44bb89e07d9865e55272a': 'Ivy', '00731df901a74de5b9b000713f14718c': 'Ruth',
        'ef9c79b62ef34530bf452c0e50e3c260': 'Kendra', '6a735fd94f67467eb592567972ee0d51': 'Salli',
        'ecf8af242b724e02ad6b549fa83d2e53': 'Joanna', '9352405796474d61af744235c352eba1': 'Joey',
    }
    default_shotstack_voice = 'Joanna'
    selected_voice = voice_map.get(vvc_voice_id, default_shotstack_voice)
    print(f"DEBUG Voice Map: VVC ID '{vvc_voice_id}' mapped to Shotstack Voice '{selected_voice}'")
    return selected_voice

def map_font_for_shotstack_py(vvc_font_style):
    font_map = { 'Roboto': 'Roboto', 'Lato': 'Lato', 'Montserrat': 'Montserrat', 'Georgia': 'Georgia', }
    return font_map.get(vvc_font_style, 'Roboto')

def map_color_py(color_theme_choice, element_type = 'text'):
    themes = {
        'vibrant': { 'text': '#FFFFFF', 'background': '#FF3D00', 'subtitle_bg_hex': '#1A1A1A' },
        'pastel': { 'text': '#3E2723', 'background': '#FFF9C4', 'subtitle_bg_hex': '#404040' },
        'monochrome': { 'text': '#FFFFFF', 'background': '#000000', 'subtitle_bg_hex': '#222222' },
        'dark_mode': { 'text': '#E0E0E0', 'background': '#121212', 'subtitle_bg_hex': '#050505' },
    }
    default_theme_key = 'monochrome'
    chosen_theme_data = themes.get(color_theme_choice, themes[default_theme_key])
    if element_type == 'subtitle_bg_hex': return chosen_theme_data['subtitle_bg_hex']
    return chosen_theme_data.get(element_type, chosen_theme_data['text'])


@functions_framework.http
def orchestrate_video_creation(request): # Renamed main GCF function
    print("DEBUG GCF: orchestrate_video_creation function started.")
    start_time_total_gcf = time.time()

    if not all([storage_client, speech_client, GCS_BUCKET_NAME]):
        err_msg = "GCF critical component (Storage/Speech client or GCS_BUCKET_NAME) not initialized."
        print(f"DEBUG GCF ERROR: {err_msg}")
        return (json.dumps({"success": False, "error": err_msg}), 500, {'Content-Type': 'application/json'})

    request_json = request.get_json(silent=True)
    if not request_json:
        return (json.dumps({"success": False, "error": "Invalid JSON body"}), 400, {'Content-Type': 'application/json'})

    print(f"DEBUG GCF: Received request: {str(request_json)[:300]}...") # Log more of request

    # --- Extract data from WordPress request ---
    script_text = request_json.get("script_text")
    fish_audio_voice_id = request_json.get("fish_audio_voice_id")
    fish_audio_api_key = request_json.get(FISH_AUDIO_API_KEY_PARAM)
    shotstack_api_key = request_json.get(SHOTSTACK_API_KEY_PARAM)
    shotstack_env = request_json.get(SHOTSTACK_ENV_PARAM, "stage")
    
    # Assets/Choices from WordPress
    pexels_urls = request_json.get("pexels_urls", []) # Expects a list of strings
    music_url_from_wp = request_json.get("music_url") # Publicly accessible URL of music from WP
    font_style_choice = request_json.get("font_style", "Roboto")
    color_theme_choice = request_json.get("color_theme", "monochrome")
    # This estimated duration is mainly for timing Pexels clips if their count drives overall visual length
    # The actual VO duration from Fish/S2T will determine audio/subtitle length.
    estimated_script_duration = float(request_json.get("estimated_script_duration", 30.0))


    if not all([script_text, fish_audio_voice_id, fish_audio_api_key, shotstack_api_key]):
        return (json.dumps({"success": False, "error": "Missing critical API keys or script data"}), 400, {'Content-Type': 'application/json'})

    # --- 1. Fish.audio Voiceover ---
    print("DEBUG GCF: Calling Fish.audio API...")
    # ... (Copy the exact Fish.audio call, GCS upload, and Mutagen duration logic from the previous main.py here)
    # This section needs to robustly set:
    # fish_audio_gcs_uri (gs:// path)
    # fish_audio_public_url (https:// path to GCS object, assuming public or needs signing)
    # audio_duration_seconds (float from Mutagen or S2T fallback)
    # mp3_blob (the GCS blob object for potential deletion on STT failure)
    # --- Start of Fish Audio Section (Copied & Adapted from previous GCF main.py) ---
    fish_audio_api_endpoint = 'https://api.fish.audio/v1/tts'
    fish_payload = {"text": script_text, "format": "mp3", "reference_id": fish_audio_voice_id}
    fish_headers = {'Authorization': f'Bearer {fish_audio_api_key}', 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'}
    mp3_content = None
    try:
        fish_response = requests.post(fish_audio_api_endpoint, json=fish_payload, headers=fish_headers, timeout=120)
        fish_response.raise_for_status()
        if 'audio/mpeg' not in fish_response.headers.get('Content-Type', '').lower():
            raise ValueError(f"Fish.audio did not return MP3. CT: {fish_response.headers.get('Content-Type','')}. Status: {fish_response.status_code}.")
        mp3_content = fish_response.content
        print(f"DEBUG GCF: Fetched MP3 from Fish.audio, size: {len(mp3_content)}")
    except Exception as e: # Catch all request/value errors
        print(f"DEBUG GCF: Fish.audio API request failed: {e}")
        return (json.dumps({"success": False, "error": f"Fish.audio API request failed: {e}"}), 500, {'Content-Type': 'application/json'})

    timestamp = int(time.time())
    gcs_blob_name = f"fish-audio-vo/vo_{timestamp}_{fish_audio_voice_id}.mp3"
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    mp3_blob = bucket.blob(gcs_blob_name) # Keep blob object reference
    try:
        mp3_blob.upload_from_string(mp3_content, content_type='audio/mpeg')
        fish_audio_gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_blob_name}"
        fish_audio_public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_blob_name}"
        print(f"DEBUG GCF: Uploaded Fish.audio MP3 to {fish_audio_gcs_uri}")
    except Exception as e:
        print(f"DEBUG GCF: Failed to upload to GCS: {e}")
        return (json.dumps({"success": False, "error": f"Failed to upload audio to GCS: {e}"}), 500, {'Content-Type': 'application/json'})
    
    audio_duration_seconds = 0.0; temp_mp3_path = f"/tmp/temp_vo_{timestamp}.mp3"
    try:
        with open(temp_mp3_path, 'wb') as f: f.write(mp3_content)
        audio_file_for_duration = MP3(temp_mp3_path)
        if audio_file_for_duration.info: audio_duration_seconds = float(audio_file_for_duration.info.length)
        else: print("DEBUG GCF Mutagen: MP3.info was None.")
        os.remove(temp_mp3_path)
        print(f"DEBUG GCF: Audio duration from mutagen: {audio_duration_seconds}s")
    except Exception as e:
        print(f"DEBUG GCF: Mutagen error: {e}. Will rely on S2T or estimate.")
        if os.path.exists(temp_mp3_path): os.remove(temp_mp3_path)
    # --- End of Fish Audio Section ---


    # --- 2. Google Speech-to-Text ---
    print(f"DEBUG GCF: Sending {fish_audio_gcs_uri} to Speech-to-Text API...")
    # ... (Copy the exact Google Speech-to-Text call and SRT Data Generation logic here from the previous main.py)
    # This section should robustly set:
    # srt_segments (list of dicts: {'text': ..., 'start_seconds': ..., 'end_seconds': ..., 'duration_seconds': ...})
    # And potentially update audio_duration_seconds if mutagen failed and S2T provided a total.
    # --- Start of S2T Section (Copied & Adapted) ---
    recognition_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MP3,
        language_code="en-US", enable_word_time_offsets=True, model="video"
    )
    audio_source = speech.RecognitionAudio(uri=fish_audio_gcs_uri)
    srt_segments = []
    last_word_end_time_for_duration_calc = 0.0
    try:
        operation = speech_client.long_running_recognize(config=recognition_config, audio=audio_source)
        print("DEBUG GCF: Waiting for Speech-to-Text...")
        stt_response = operation.result(timeout=300)
        print("DEBUG GCF: Speech-to-Text completed.")

        current_line_text = ""; current_line_start_time = -1.0; max_chars_per_line = 40; max_duration_per_line_seconds = 6.0; min_duration_per_line_seconds = 0.5
        for result in stt_response.results:
            if not result.alternatives or not result.alternatives[0].words: continue
            for word_info in result.alternatives[0].words:
                word = word_info.word; start_time = word_info.start_time.total_seconds(); end_time = word_info.end_time.total_seconds()
                if current_line_start_time < 0: current_line_start_time = start_time
                force_break = (word.endswith(('.', '!', '?')) and len(current_line_text) > 10)
                if current_line_text and (len(current_line_text + " " + word) > max_chars_per_line or (end_time - current_line_start_time) > max_duration_per_line_seconds or force_break):
                    line_actual_end_time = last_word_end_time_for_duration_calc
                    line_duration = line_actual_end_time - current_line_start_time
                    if line_duration >= min_duration_per_line_seconds:
                        srt_segments.append({ "text": current_line_text.strip(), "start_seconds": round(current_line_start_time, 3), "end_seconds": round(line_actual_end_time, 3), "duration_seconds": round(line_duration, 3) })
                    current_line_text = word; current_line_start_time = start_time
                else:
                    current_line_text += (" " + word) if current_line_text else word
                last_word_end_time_for_duration_calc = end_time
        if current_line_text and current_line_start_time >= 0:
            line_duration = last_word_end_time_for_duration_calc - current_line_start_time
            if line_duration >= min_duration_per_line_seconds:
                 srt_segments.append({ "text": current_line_text.strip(), "start_seconds": round(current_line_start_time, 3), "end_seconds": round(last_word_end_time_for_duration_calc, 3), "duration_seconds": round(line_duration, 3) })
        if audio_duration_seconds <= 0.1 and last_word_end_time_for_duration_calc > 0: audio_duration_seconds = last_word_end_time_for_duration_calc
        elif audio_duration_seconds <= 0.1: audio_duration_seconds = 10.0 # Fallback
        print(f"DEBUG GCF: Generated {len(srt_segments)} SRT segments. Final audio duration: {audio_duration_seconds}s")

    except Exception as e:
        print(f"DEBUG GCF: Speech-to-Text processing failed: {e}")
        try: mp3_blob.delete(); print(f"DEBUG GCF: Deleted GCS object {gcs_blob_name} after STT failure.")
        except Exception as e_del: print(f"DEBUG GCF: Failed to delete GCS object {gcs_blob_name}: {e_del}")
        return (json.dumps({"success": False, "error": f"Speech-to-Text processing failed: {e}"}), 500, {'Content-Type': 'application/json'})
    # --- End of S2T Section ---


    # --- 3. Assemble Shotstack JSON (using Pexels URLs from WP, Fish.audio from GCS, SRT data for TitleAssets) ---
    print("DEBUG GCF: Assembling Shotstack JSON...")
    shotstack_video_clips = []
    num_pexels_clips = len(pexels_urls)
    pexels_start_time = 0
    # Use actual_vo_duration for timing visuals if available and sensible, else estimated.
    # The "length: auto" for TTS means its actual length drives the timeline.
    # So, Pexels clips should be timed against audio_duration_seconds.
    visual_track_duration = audio_duration_seconds
    
    if num_pexels_clips > 0:
        pexels_clip_len = round(visual_track_duration / num_pexels_clips, 2)
        for i, p_url in enumerate(pexels_urls):
            current_len = pexels_clip_len
            if i == num_pexels_clips - 1: # last clip fills
                current_len = round(visual_track_duration - pexels_start_time, 2)
            if current_len <= 0.1: continue
            shotstack_video_clips.append({
                "asset": {"type": "video", "src": p_url, "volume": 0},
                "start": round(pexels_start_time, 2), "length": current_len,
                "transition": {"in": "fade" if i > 0 else "none"}, "fit": "cover"
            })
            pexels_start_time += current_len
    else: # Fallback if no Pexels URLs
        shotstack_video_clips.append({
            "asset": {"type": "html", "html": f"<body style='background-color:{map_color_py(color_theme_choice, 'background')};'></body>", "width": 576, "height": 1024},
            "start": 0, "length": visual_track_duration
        })

    shotstack_title_assets = []
    if srt_segments:
        for seg in srt_segments:
            # Ensure title asset length does not exceed remaining video duration based on its start time
            title_len = seg['duration_seconds']
            if seg['start_seconds'] + title_len > audio_duration_seconds:
                title_len = max(0.2, audio_duration_seconds - seg['start_seconds'])

            if title_len > 0.1 : # Only add if it has some duration
                shotstack_title_assets.append({
                    "asset": {
                        "type": "title", "text": seg['text'], "style": "subtitle",
                        "position": "bottom", "size": "x-small", # Or "small"
                        "background": map_color_py(color_theme_choice, 'subtitle_bg_hex'),
                        "color": map_color_py(color_theme_choice, 'text'),
                        "font": map_font_for_shotstack_py(font_style_choice)
                        # "offset": {"y": -0.1} # Pushes up from edge
                    },
                    "start": seg['start_seconds'], "length": title_len
                })

    shotstack_timeline = {
        "background": map_color_py(color_theme_choice, 'background'),
        "tracks": [
            {"clips": shotstack_video_clips}, # Track 0: Visuals (Pexels/Fallback)
            { # Track 1: Fish.audio Voiceover (from GCS)
                "clips": [{"asset": {"type": "audio", "src": fish_audio_public_url, "volume": 1},
                           "start": 0, "length": audio_duration_seconds }]
            }
            # Subtitles and Music added next
        ]
    }
    if shotstack_title_assets:
        shotstack_timeline["tracks"].append({"clips": shotstack_title_assets}) # Track 2: Subtitles
        print(f"DEBUG GCF: Added {len(shotstack_title_assets)} subtitle TitleAssets to Shotstack JSON.")
    if music_url_from_wp:
        shotstack_timeline["tracks"].append({ # Track 3 (or 2 if no subs): Music
            "clips": [{"asset": {"type": "audio", "src": music_url_from_wp, "volume": 0.12},
                       "start": 0, "length": audio_duration_seconds }] # Sync music with VO
        })
        print("DEBUG GCF: Added music track to Shotstack JSON.")


    shotstack_render_payload = {
        "timeline": shotstack_timeline,
        "output": { "format": "mp4", "resolution": "sd", "aspectRatio": "9:16", "fps": 30, "quality": "medium"}
    }
    print("DEBUG GCF: Assembled Shotstack JSON. Snippet: " + json.dumps(shotstack_render_payload)[:300] + "...")

    # --- 4. Submit to Shotstack API ---
    shotstack_stage_url = 'https://api.shotstack.io/stage/render'
    shotstack_prod_url = 'https://api.shotstack.io/v1/render'
    shotstack_api_endpoint = shotstack_stage_url if shotstack_env == 'stage' else shotstack_prod_url
    shotstack_headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'x-api-key': shotstack_api_key}
    
    print(f"DEBUG GCF: Submitting to Shotstack endpoint: {shotstack_api_endpoint}")
    try:
        ss_response = requests.post(shotstack_api_endpoint, json=shotstack_render_payload, headers=shotstack_headers, timeout=75)
        ss_response.raise_for_status()
        ss_data = ss_response.json()
        if ss_data.get("success") and ss_data.get("response", {}).get("id"):
            render_id = ss_data["response"]["id"]
            print(f"DEBUG GCF: Successfully submitted to Shotstack. Render ID: {render_id}")
            # Also include the actual audio duration as determined by S2T/Mutagen
            final_duration_for_wp = audio_duration_seconds
            end_time_total_gcf = time.time()
            print(f"DEBUG GCF: Total GCF execution time: {round(end_time_total_gcf - start_time_total_gcf, 2)}s")
            return (json.dumps({
                "success": True,
                "shotstack_render_id": render_id,
                "message": "Video processing job submitted to Shotstack.",
                "final_audio_duration": final_duration_for_wp,
                "fish_audio_url_used": fish_audio_public_url # For potential reference
            }), 200, {'Content-Type': 'application/json'})
        else:
            error_detail = f"Shotstack API success was false or ID missing. Response: {ss_data}"
            print(f"DEBUG GCF ERROR: {error_detail}")
            return (json.dumps({"success": False, "error": "Shotstack submission failed after API call.", "details": error_detail}), 500, {'Content-Type': 'application/json'})

    except requests.exceptions.RequestException as e:
        error_detail = f"Shotstack API request failed: {e}. Response: {e.response.text if e.response else 'No response text'}"
        print(f"DEBUG GCF ERROR: {error_detail}")
        return (json.dumps({"success": False, "error": "Shotstack API communication error.", "details": error_detail}), 500, {'Content-Type': 'application/json'})
    except Exception as e_final: # Catch any other unexpected error during submission
        error_detail = f"Unexpected error during Shotstack submission phase: {e_final}"
        print(f"DEBUG GCF ERROR: {error_detail}")
        return (json.dumps({"success": False, "error": "Unexpected error during final processing.", "details": error_detail}), 500, {'Content-Type': 'application/json'})

print("DEBUG: main.py loaded and orchestrate_video_creation function defined.")
