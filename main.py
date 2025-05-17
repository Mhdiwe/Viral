print("DEBUG: main.py starting to load - GCF - ASSET GENERATION CORE")

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

print("DEBUG: All top-level imports attempted and hopefully succeeded.")

# Expected in request from WordPress
FISH_AUDIO_API_KEY_PARAM = "fish_audio_api_key"
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")

storage_client = None
speech_client = None
try:
    if not GCS_BUCKET_NAME:
        print("DEBUG: CRITICAL - GCS_BUCKET_NAME environment variable is NOT SET!")
        raise ValueError("GCS_BUCKET_NAME environment variable not set.")
    storage_client = storage.Client()
    print("DEBUG: google.cloud.storage.Client() initialized successfully.")
except Exception as e:
    print(f"DEBUG: CRITICAL - FAILED to initialize google.cloud.storage.Client(): {e}")
    raise 

try:
    speech_client = speech.SpeechClient()
    print("DEBUG: google.cloud.speech.SpeechClient() initialized successfully.")
except Exception as e:
    print(f"DEBUG: CRITICAL - FAILED to initialize google.cloud.speech.SpeechClient(): {e}")
    raise

def format_time_srt(seconds_float):
    if not isinstance(seconds_float, (int, float)) or seconds_float < 0: seconds_float = 0.0
    millis = int(round((seconds_float - int(seconds_float)) * 1000))
    seconds_int = int(seconds_float); minutes = seconds_int // 60; hours = minutes // 60
    seconds_val = seconds_int % 60; minutes %= 60
    return f"{hours:02}:{minutes:02}:{seconds_val:02},{millis:03}"

@functions_framework.http
def orchestrate_video_creation(request): # Entry point name from Procfile
    print("DEBUG GCF: orchestrate_video_creation (Asset Gen Core) function started.")
    start_time_total_gcf = time.time()

    if not all([storage_client, speech_client, GCS_BUCKET_NAME]):
        err_msg = "GCF critical component (Storage/Speech client or GCS_BUCKET_NAME) not available/initialized."
        print(f"DEBUG GCF ERROR: {err_msg}"); return (json.dumps({"success": False, "error": err_msg}), 500, {'Content-Type': 'application/json'})

    request_json = request.get_json(silent=True)
    if not request_json: return (json.dumps({"success": False, "error": "Invalid JSON body"}), 400, {'Content-Type': 'application/json'})
    print(f"DEBUG GCF: Received request (first 300 chars): {str(request_json)[:300]}...")

    script_text = request_json.get("script_text")
    fish_audio_voice_id = request_json.get("fish_audio_voice_id")
    fish_audio_api_key = request_json.get(FISH_AUDIO_API_KEY_PARAM)
    # Parameters for later phases (DALL-E prompts, Pexels, Music, Styles) would be extracted here too.

    required_params = {"script_text": script_text, "fish_audio_voice_id": fish_audio_voice_id, FISH_AUDIO_API_KEY_PARAM: fish_audio_api_key}
    missing_params = [k for k, v in required_params.items() if not v]
    if missing_params: return (json.dumps({"success": False, "error": f"Missing params: {', '.join(missing_params)}"}), 400, {'Content-Type': 'application/json'})

    # --- 1. Fish.audio Voiceover & Duration ---
    print("DEBUG GCF: Processing Fish.audio VO...")
    fish_audio_api_endpoint = 'https://api.fish.audio/v1/tts'; fish_payload = {"text": script_text, "format": "mp3", "reference_id": fish_audio_voice_id}; fish_headers = {'Authorization': f'Bearer {fish_audio_api_key}', 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'}; mp3_content = None; fish_audio_gcs_uri = None; fish_audio_public_url = None
    try:
        fish_response = requests.post(fish_audio_api_endpoint, json=fish_payload, headers=fish_headers, timeout=120); fish_response.raise_for_status()
        if 'audio/mpeg' not in fish_response.headers.get('Content-Type', '').lower(): raise ValueError(f"Fish.audio no MP3. CT: {fish_response.headers.get('Content-Type','')}, Status: {fish_response.status_code}.")
        mp3_content = fish_response.content; print(f"DEBUG GCF: Fetched MP3 from Fish.audio, size: {len(mp3_content)}")
    except Exception as e: print(f"DEBUG GCF: Fish.audio API fail: {e}"); return (json.dumps({"success": False, "error": f"Fish.audio API fail: {str(e)[:200]}"}), 500, {'Content-Type': 'application/json'})
    timestamp = int(time.time()); gcs_blob_name = f"fish-audio-vo/vo_{timestamp}_{fish_audio_voice_id}.mp3"; bucket = storage_client.bucket(GCS_BUCKET_NAME); mp3_blob = bucket.blob(gcs_blob_name)
    try:
        mp3_blob.upload_from_string(mp3_content, content_type='audio/mpeg'); fish_audio_gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_blob_name}"; fish_audio_public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_blob_name}"; print(f"DEBUG GCF: Uploaded Fish MP3 to {fish_audio_gcs_uri}")
    except Exception as e: print(f"DEBUG GCF: GCS Upload fail: {e}"); return (json.dumps({"success": False, "error": f"GCS Upload fail: {str(e)[:200]}"}), 500, {'Content-Type': 'application/json'})
    audio_duration_seconds = 0.0; temp_mp3_path = f"/tmp/temp_vo_{timestamp}.mp3"
    try:
        with open(temp_mp3_path, 'wb') as f: f.write(mp3_content)
        audio_file_for_duration = MP3(temp_mp3_path)
        if audio_file_for_duration.info: audio_duration_seconds = float(audio_file_for_duration.info.length)
        else: print("DEBUG GCF Mutagen: MP3.info None.")
        os.remove(temp_mp3_path); print(f"DEBUG GCF: Duration(mutagen): {audio_duration_seconds}s")
    except Exception as e: print(f"DEBUG GCF: Mutagen error: {e}.");_ = os.path.exists(temp_mp3_path) and os.remove(temp_mp3_path)
    if audio_duration_seconds <= 0.1: audio_duration_seconds = len(script_text.split()) / 3.0; print(f"DEBUG GCF: Mutagen fail/invalid, script est. duration: {audio_duration_seconds}s"); audio_duration_seconds = max(5.0, audio_duration_seconds)

    # --- 2. Google Speech-to-Text & SRT Data Generation ---
    print(f"DEBUG GCF: S2T for {fish_audio_gcs_uri} (est. dur: {audio_duration_seconds}s)...")
    recognition_config = speech.RecognitionConfig(encoding=speech.RecognitionConfig.AudioEncoding.MP3, language_code="en-US", enable_word_time_offsets=True, model="video"); audio_source = speech.RecognitionAudio(uri=fish_audio_gcs_uri); srt_segments = []; last_word_end_time_for_duration_calc = 0.0
    try:
        operation = speech_client.long_running_recognize(config=recognition_config, audio=audio_source); print("DEBUG GCF: Waiting for S2T..."); stt_response = operation.result(timeout=300); print("DEBUG GCF: S2T completed.")
        current_line_text = ""; current_line_start_time = -1.0; max_chars_per_line = 40; max_duration_per_line_seconds = 6.0; min_duration_per_line_seconds = 0.5
        for result_idx, result in enumerate(stt_response.results):
            if not result.alternatives or not result.alternatives[0].words: print(f"DEBUG GCF S2T: Result {result_idx} no words/alts."); continue
            for word_idx, word_info in enumerate(result.alternatives[0].words):
                word = word_info.word; start_time = word_info.start_time.total_seconds(); end_time = word_info.end_time.total_seconds()
                if current_line_start_time < 0: current_line_start_time = start_time
                force_break = (word.endswith(('.', '!', '?')) and len(current_line_text) > 10)
                if current_line_text and (len(current_line_text + " " + word) > max_chars_per_line or (end_time - current_line_start_time) > max_duration_per_line_seconds or force_break):
                    line_actual_end_time = last_word_end_time_for_duration_calc; line_duration = line_actual_end_time - current_line_start_time
                    if line_duration >= min_duration_per_line_seconds: srt_segments.append({ "text": current_line_text.strip(), "start_seconds": round(current_line_start_time, 3), "end_seconds": round(line_actual_end_time, 3), "duration_seconds": round(line_duration, 3) })
                    current_line_text = word; current_line_start_time = start_time
                else: current_line_text += (" " + word) if current_line_text else word
                last_word_end_time_for_duration_calc = end_time
        if current_line_text and current_line_start_time >= 0:
            line_duration = last_word_end_time_for_duration_calc - current_line_start_time
            if line_duration >= min_duration_per_line_seconds: srt_segments.append({ "text": current_line_text.strip(), "start_seconds": round(current_line_start_time, 3), "end_seconds": round(last_word_end_time_for_duration_calc, 3), "duration_seconds": round(line_duration, 3) })
        if stt_response.results and stt_response.results[-1].alternatives and stt_response.results[-1].alternatives[0].words:
            s2t_end_time = stt_response.results[-1].alternatives[0].words[-1].end_time.total_seconds()
            if s2t_end_time > 0.1 : audio_duration_seconds = s2t_end_time; print(f"DEBUG GCF: Audio duration updated from S2T to {audio_duration_seconds}s")
        print(f"DEBUG GCF: Generated {len(srt_segments)} SRT segments. Final audio duration for timeline: {audio_duration_seconds}s")
    except Exception as e:
        print(f"DEBUG GCF: S2T processing fail: {e}");
        if 'mp3_blob' in locals() and mp3_blob is not None and hasattr(mp3_blob, 'delete'): # Ensure mp3_blob exists
            try: mp3_blob.delete(); print(f"DEBUG GCF: Deleted GCS object {gcs_blob_name} after STT failure.")
            except Exception as e_del: print(f"DEBUG GCF: Failed to delete GCS object {gcs_blob_name}: {e_del}")
        return (json.dumps({"success": False, "error": f"S2T processing fail: {str(e)[:200]}"}), 500, {'Content-Type': 'application/json'})
    
    if audio_duration_seconds <= 0.1: return (json.dumps({"success": False, "error": "Failed to determine valid audio duration."}), 500, {'Content-Type': 'application/json'})

    # --- GCF returns generated assets to WordPress ---
    final_response_data = {
        "success": True,
        "message": "GCF asset generation successful.",
        "fish_audio_gcs_uri": fish_audio_gcs_uri,
        "fish_audio_public_url": fish_audio_public_url,
        "audio_duration_seconds": round(audio_duration_seconds, 3),
        "srt_segments": srt_segments
        # Later, DALL-E URLs would be added here
    }
    end_time_total_gcf = time.time()
    print(f"DEBUG GCF: Total GCF execution time for asset generation: {round(end_time_total_gcf - start_time_total_gcf, 2)}s")
    print(f"DEBUG GCF: Returning asset data to WordPress: {str(final_response_data)[:300]}...")
    return (json.dumps(final_response_data), 200, {'Content-Type': 'application/json'})

print("DEBUG: main.py loaded and orchestrate_video_creation function defined.")
