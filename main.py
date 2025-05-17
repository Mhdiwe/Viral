print("DEBUG: main.py starting to load - GCF - Step: Add Pexels Videos to Shotstack JSON")

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
except Exception as e_general: print(f"DEBUG: CRITICAL ERROR importing google.cloud.storage: {e_general}"); raise 
# Speech-to-Text client not strictly needed for this test as S2T is skipped
try:
    from google.cloud import speech_v1p1beta1 as speech
    print("DEBUG: imported google.cloud.speech_v1p1beta1 as speech (not used in this test)")
except Exception as e_general: print(f"DEBUG: ERROR importing google.cloud.speech (not critical for this test): {e_general}")
try:
    from mutagen.mp3 import MP3
    print("DEBUG: imported mutagen.mp3")
except Exception as e_general: print(f"DEBUG: CRITICAL ERROR importing mutagen.mp3: {e_general}"); raise

print("DEBUG: All top-level imports attempted.")

FISH_AUDIO_API_KEY_PARAM = "fish_audio_api_key"; SHOTSTACK_API_KEY_PARAM = "shotstack_api_key"; SHOTSTACK_ENV_PARAM = "shotstack_environment"
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
storage_client = None; # speech_client = None (not initialized as S2T is skipped)
try:
    if not GCS_BUCKET_NAME: raise ValueError("GCS_BUCKET_NAME environment variable not set.")
    storage_client = storage.Client(); print("DEBUG: google.cloud.storage.Client() initialized.")
except Exception as e: print(f"DEBUG: CRITICAL - FAILED to init storage.Client(): {e}"); raise

def map_shotstack_voice_py(vvc_voice_id): # For Fish.audio call
    voice_map = {'802e3bc2b27e49c2995d23ef70e6ac89': 'Amy', 'f8dfe9c83081432386f143e2fe9767ef': 'Brian', '3b7e2226b65941a4af6c3fc6609b8361': 'Emma', '728f6ff2240d49308e8137ffe66008e2': 'Matthew', '0b74ead073f2474a904f69033535b98e': 'Olivia', '16b2981936f34328886f4f230e7fe196': 'Joanna', '3ce4bfc65d0e483aa880073d2a589745': 'Salli', '9af2433a5d1d4d728fb4c9c82c565315': 'Kimberly', 'af8a334a68a44bb89e07d9865e55272a': 'Ivy', '00731df901a74de5b9b000713f14718c': 'Ruth', 'ef9c79b62ef34530bf452c0e50e3c260': 'Kendra', '6a735fd94f67467eb592567972ee0d51': 'Salli', 'ecf8af242b724e02ad6b549fa83d2e53': 'Joanna', '9352405796474d61af744235c352eba1': 'Joey',}
    default_shotstack_voice = 'Joanna'; selected_voice = voice_map.get(vvc_voice_id, default_shotstack_voice)
    # print(f"DEBUG GCF Voice Map: VVC ID '{vvc_voice_id}' mapped to SS Voice '{selected_voice}' (for Fish.audio)") # Less verbose
    return selected_voice

def map_color_py(color_theme_choice, element_type = 'text'):
    themes = { # Keep full themes for when we add subtitles/other elements back
        'vibrant': { 'text': '#FFFFFF', 'background': '#FF3D00', 'subtitle_bg_hex': '#1A1A1A' },
        'pastel': { 'text': '#3E2723', 'background': '#FFF9C4', 'subtitle_bg_hex': '#404040' },
        'monochrome': { 'text': '#FFFFFF', 'background': '#000000', 'subtitle_bg_hex': '#222222' },
        'dark_mode': { 'text': '#E0E0E0', 'background': '#121212', 'subtitle_bg_hex': '#050505' },
    }
    default_theme_key = 'monochrome'; chosen_theme_data = themes.get(color_theme_choice, themes[default_theme_key])
    if element_type == 'subtitle_bg_hex': return chosen_theme_data['subtitle_bg_hex']
    return chosen_theme_data.get(element_type, chosen_theme_data['text'])

@functions_framework.http
def orchestrate_video_creation(request):
    print("DEBUG GCF: orchestrate_video_creation function started (Pexels Test).")
    start_time_total_gcf = time.time()

    if not all([storage_client, GCS_BUCKET_NAME]):
        err_msg = "GCF critical component not initialized."; print(f"DEBUG GCF ERROR: {err_msg}"); return (json.dumps({"success": False, "error": err_msg}), 500, {'Content-Type': 'application/json'})

    request_json = request.get_json(silent=True)
    if not request_json: return (json.dumps({"success": False, "error": "Invalid JSON body"}), 400, {'Content-Type': 'application/json'})
    print(f"DEBUG GCF: Received request (first 300): {str(request_json)[:300]}...")

    script_text = request_json.get("script_text")
    fish_audio_voice_id = request_json.get("fish_audio_voice_id")
    fish_audio_api_key = request_json.get(FISH_AUDIO_API_KEY_PARAM)
    shotstack_api_key = request_json.get(SHOTSTACK_API_KEY_PARAM)
    shotstack_env = request_json.get(SHOTSTACK_ENV_PARAM, "stage")
    
    pexels_urls = request_json.get("pexels_urls", []) # Received from WordPress
    color_theme_choice = request_json.get("color_theme", "monochrome") # For background
    # music_url_from_wp, font_style_choice, estimated_visual_duration are not used in this specific test version

    required_params = {"script_text": script_text, "fish_audio_voice_id": fish_audio_voice_id, FISH_AUDIO_API_KEY_PARAM: fish_audio_api_key, SHOTSTACK_API_KEY_PARAM: shotstack_api_key}
    missing_params = [k for k, v in required_params.items() if not v]
    if missing_params: return (json.dumps({"success": False, "error": f"Missing params: {', '.join(missing_params)}"}), 400, {'Content-Type': 'application/json'})

    # --- 1. Fish.audio Voiceover & Duration ---
    print("DEBUG GCF: Processing Fish.audio VO...")
    # ... (Fish.audio call, GCS upload, Mutagen logic - VERBATIM from previous full main.py) ...
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

    # --- S2T and SRT generation is SKIPPED for this test ---
    print("DEBUG GCF: Skipping S2T and SRT generation for Pexels test.")
    if audio_duration_seconds <= 0.1: return (json.dumps({"success": False, "error": "Failed to determine valid audio duration for Pexels test."}), 500, {'Content-Type': 'application/json'})

    # --- Assemble Shotstack JSON with Pexels and Voiceover ---
    print("DEBUG GCF: Assembling Shotstack JSON (Pexels + VO Test)...")
    shotstack_video_clips = []
    num_visual_clips = len(pexels_urls)
    visual_start_time = 0
    visual_total_duration = audio_duration_seconds # Pexels clips will span the voiceover duration

    if num_visual_clips > 0:
        visual_clip_len = round(visual_total_duration / num_visual_clips, 2) if num_visual_clips > 0 else visual_total_duration
        for i, p_url in enumerate(pexels_urls):
            current_len = visual_clip_len
            if i == num_visual_clips - 1: current_len = round(visual_total_duration - visual_start_time, 2)
            if current_len <= 0.1: continue
            shotstack_video_clips.append({
                "asset": {"type": "video", "src": p_url, "volume": 0},
                "start": round(visual_start_time, 2), "length": current_len,
                "transition": {"in": "fade" if i > 0 else "none"}, "fit": "cover"
            })
            visual_start_time += current_len
    else: # Fallback if no Pexels URLs from WordPress
        shotstack_video_clips.append({
            "asset": {"type": "html", "html": f"<body style='background-color:{map_color_py(color_theme_choice, 'background')};'></body>", "width": 576, "height": 1024},
            "start": 0, "length": visual_total_duration
        })
        print("DEBUG GCF JSON Assembly: No Pexels URLs provided by WP, using fallback color background.")
    print(f"DEBUG GCF JSON Assembly: Prepared {len(shotstack_video_clips)} video clips.")

    shotstack_timeline = {
        "background": map_color_py(color_theme_choice, 'background'),
        "tracks": [
            {"clips": shotstack_video_clips}, # Track 0: Pexels Videos or Fallback
            {"clips": [{"asset": {"type": "audio", "src": fish_audio_public_url, "volume": 1}, "start": 0, "length": audio_duration_seconds }]} # Track 1: Fish.audio VO
            // No Subtitles, No Music for this test
        ]
    }
    shotstack_render_payload = { "timeline": shotstack_timeline, "output": { "format": "mp4", "resolution": "sd", "aspectRatio": "9:16", "fps": 30, "quality": "medium"}}
    print("DEBUG GCF JSON Assembly: Final payload for Pexels test created.")
    try:
        full_json_string = json.dumps(shotstack_render_payload, indent=2)
        print("DEBUG GCF: FULL Shotstack JSON Payload (Pexels Test): " + full_json_string)
    except Exception as e_json_dump: print(f"DEBUG GCF ERROR: Failed to dump payload to JSON: {e_json_dump}"); return (json.dumps({"success": False, "error": "Internal error: Failed to serialize for Shotstack.", "details": str(e_json_dump)}), 500, {'Content-Type': 'application/json'})

    # --- Submit to Shotstack API ---
    shotstack_stage_url = 'https://api.shotstack.io/stage/render'; shotstack_prod_url = 'https://api.shotstack.io/v1/render'; shotstack_api_endpoint = shotstack_stage_url if shotstack_env == 'stage' else shotstack_prod_url; shotstack_headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'x-api-key': shotstack_api_key}
    print(f"DEBUG GCF: Submitting Pexels Test JSON to Shotstack: {shotstack_api_endpoint}")
    try:
        ss_response = requests.post(shotstack_api_endpoint, json=shotstack_render_payload, headers=shotstack_headers, timeout=75); ss_response.raise_for_status(); ss_data = ss_response.json()
        if ss_data.get("success") and ss_data.get("response", {}).get("id"):
            render_id = ss_data["response"]["id"]; print(f"DEBUG GCF: Submitted to Shotstack. Render ID: {render_id}"); final_duration_for_wp = audio_duration_seconds; end_time_total_gcf = time.time(); print(f"DEBUG GCF: Total GCF execution time: {round(end_time_total_gcf - start_time_total_gcf, 2)}s")
            return (json.dumps({ "success": True, "shotstack_render_id": render_id, "message": "Video (Pexels Test) submitted.", "final_audio_duration": round(final_duration_for_wp,3) }), 200, {'Content-Type': 'application/json'})
        else: error_detail = f"Shotstack API no success/ID. Resp: {str(ss_data)[:500]}"; print(f"DEBUG GCF ERROR: {error_detail}"); return (json.dumps({"success": False, "error": "Shotstack submission issue (Pexels Test).", "details": error_detail}), 500, {'Content-Type': 'application/json'})
    except requests.exceptions.HTTPError as http_err: error_detail = f"Shotstack HTTP error (Pexels Test): {http_err}. Resp: {http_err.response.text[:500] if http_err.response else 'No resp text'}"; print(f"DEBUG GCF ERROR: {error_detail}"); return (json.dumps({"success": False, "error": "Shotstack API error (Pexels Test).", "details": error_detail}), (http_err.response.status_code if http_err.response else 500) , {'Content-Type': 'application/json'})
    except requests.exceptions.RequestException as e: error_detail = f"Shotstack req fail (Pexels Test): {e}."; print(f"DEBUG GCF ERROR: {error_detail}"); return (json.dumps({"success": False, "error": "Shotstack API comms error (Pexels Test).", "details": error_detail}), 500, {'Content-Type': 'application/json'})

print("DEBUG: main.py loaded and orchestrate_video_creation function defined.")
