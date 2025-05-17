print("DEBUG: main.py starting - GCF for FFmpeg Video Assembly")
import functions_framework
import os
import requests
import json
import time
import subprocess # For running FFmpeg
import shutil # For cleaning up /tmp
import uuid # For unique filenames

try:
    from google.cloud import storage
    print("DEBUG: imported google.cloud.storage")
except Exception as e: print(f"DEBUG: CRITICAL ERROR importing google.cloud.storage: {e}"); raise
try:
    from google.cloud import speech_v1p1beta1 as speech
    print("DEBUG: imported google.cloud.speech")
except Exception as e: print(f"DEBUG: CRITICAL ERROR importing google.cloud.speech: {e}"); raise
try:
    from mutagen.mp3 import MP3
    print("DEBUG: imported mutagen.mp3")
except Exception as e: print(f"DEBUG: CRITICAL ERROR importing mutagen.mp3: {e}"); raise
try:
    from openai import OpenAI # For DALL-E
    print("DEBUG: imported openai")
except Exception as e: print(f"DEBUG: CRITICAL ERROR importing openai: {e}"); raise


print("DEBUG: All top-level imports attempted.")

# --- ENV VARS & API KEYS ---
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME") # For intermediate audio/images
GCS_FINAL_VIDEO_BUCKET_NAME = os.environ.get("GCS_FINAL_VIDEO_BUCKET_NAME") # For final MP4s
# API keys expected from WordPress request payload
FISH_AUDIO_API_KEY_PARAM = "fish_audio_api_key"
OPENAI_API_KEY_PARAM = "openai_api_key"

storage_client = None; speech_client = None; openai_client = None
try:
    if not GCS_BUCKET_NAME: raise ValueError("GCS_BUCKET_NAME missing")
    if not GCS_FINAL_VIDEO_BUCKET_NAME: raise ValueError("GCS_FINAL_VIDEO_BUCKET_NAME missing")
    storage_client = storage.Client(); print("DEBUG: Storage client OK.")
    speech_client = speech.SpeechClient(); print("DEBUG: Speech client OK.")
    # OpenAI client will be initialized with key from request
except Exception as e: print(f"DEBUG: CRITICAL - Client init error: {e}"); raise

def format_srt_time(seconds_float):
    # ... (same as before) ...
    if not isinstance(seconds_float, (int, float)) or seconds_float < 0: seconds_float = 0.0
    millis = int(round((seconds_float - int(seconds_float)) * 1000)); seconds_int = int(seconds_float); minutes = seconds_int // 60; hours = minutes // 60
    seconds_val = seconds_int % 60; minutes %= 60; return f"{hours:02}:{minutes:02}:{seconds_val:02},{millis:03}"

def generate_srt_content(srt_segments):
    srt_content = []
    for i, seg in enumerate(srt_segments):
        srt_content.append(str(i + 1))
        start_srt = format_srt_time(seg['start_seconds'])
        end_srt = format_srt_time(seg['end_seconds'])
        srt_content.append(f"{start_srt} --> {end_srt}")
        srt_content.append(seg['text'])
        srt_content.append("") # Blank line separator
    return "\n".join(srt_content)

@functions_framework.http
def orchestrate_video_with_ffmpeg(request): # New entry point name
    request_id = str(uuid.uuid4()) # Unique ID for this request's temp files
    print(f"DEBUG GCF ({request_id}): orchestrate_video_with_ffmpeg started.")
    start_time_total_gcf = time.time()
    temp_dir = f"/tmp/{request_id}" # Unique temp directory
    os.makedirs(temp_dir, exist_ok=True)
    print(f"DEBUG GCF ({request_id}): Created temp dir: {temp_dir}")

    # --- Essential Client Checks ---
    if not all([storage_client, speech_client, GCS_BUCKET_NAME, GCS_FINAL_VIDEO_BUCKET_NAME]):
        err_msg = "GCF critical component or GCS bucket env var not initialized."
        print(f"DEBUG GCF ERROR ({request_id}): {err_msg}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return (json.dumps({"success": False, "error": err_msg}), 500, {'Content-Type': 'application/json'})

    request_json = request.get_json(silent=True)
    if not request_json: shutil.rmtree(temp_dir, ignore_errors=True); return (json.dumps({"success": False, "error": "Invalid JSON body"}), 400, {'Content-Type': 'application/json'})
    print(f"DEBUG GCF ({request_id}): Received request: {str(request_json)[:200]}...")

    # --- Extract data from WordPress request ---
    script_text = request_json.get("script_text")
    fish_audio_voice_id = request_json.get("fish_audio_voice_id")
    fish_audio_api_key = request_json.get(FISH_AUDIO_API_KEY_PARAM)
    openai_api_key = request_json.get(OPENAI_API_KEY_PARAM) # For DALL-E
    dalle_prompts = request_json.get("dalle_prompts", []) # List of prompts
    music_url_from_wp = request_json.get("music_url")
    # font_style_choice = request_json.get("font_style", "Arial") # For FFmpeg font
    # color_theme_choice = request_json.get("color_theme", "monochrome") # For FFmpeg colors

    required_params = {"script_text": script_text, "fish_audio_voice_id": fish_audio_voice_id,
                       FISH_AUDIO_API_KEY_PARAM: fish_audio_api_key, OPENAI_API_KEY_PARAM: openai_api_key}
    missing_params = [k for k, v in required_params.items() if not v]
    if missing_params: shutil.rmtree(temp_dir, ignore_errors=True); return (json.dumps({"success": False, "error": f"Missing params: {', '.join(missing_params)}"}), 400, {'Content-Type': 'application/json'})
    if not dalle_prompts: dalle_prompts = [f"Abstract background related to: {script_text[:50]}"] # Fallback DALL-E prompt

    # --- 1. Fish.audio Voiceover -> GCS -> Get Duration ---
    # ... (VERBATIM Fish.audio call, GCS upload, Mutagen logic from previous main.py that worked)
    # ... This section needs to robustly set:
    # fish_audio_gcs_uri (gs:// path)
    # audio_duration_seconds (float from Mutagen or S2T fallback)
    # local_fish_audio_mp3_path (path to downloaded MP3 in /tmp for FFmpeg)
    # mp3_blob (the GCS blob object for potential deletion on STT failure)
    # --- (Copy from previous successful main.py, ensuring it saves to temp_dir) ---
    print(f"DEBUG GCF ({request_id}): Processing Fish.audio VO...")
    # ... [Fish.audio processing and download to local_fish_audio_mp3_path in temp_dir] ...
    # ... [GCS Upload and Mutagen duration, set audio_duration_seconds] ...
    # For brevity, assuming this sets: local_fish_audio_mp3_path, audio_duration_seconds, fish_audio_gcs_uri, mp3_blob

    # --- 2. Google Speech-to-Text on GCS audio -> SRT Data (array of segments) ---
    print(f"DEBUG GCF ({request_id}): S2T for {fish_audio_gcs_uri} (dur: {audio_duration_seconds}s)...")
    # ... (VERBATIM S2T logic from previous main.py that worked to populate srt_segments) ...
    # --- (Copy from previous successful main.py) ---
    # This sets: srt_segments array and potentially refines audio_duration_seconds

    # --- 3. Generate Temporary SRT file for FFmpeg ---
    local_srt_path = os.path.join(temp_dir, "subtitles.srt")
    if srt_segments:
        srt_file_content = generate_srt_content(srt_segments)
        with open(local_srt_path, "w", encoding="utf-8") as f_srt:
            f_srt.write(srt_file_content)
        print(f"DEBUG GCF ({request_id}): Generated temporary SRT file at {local_srt_path}")
    else:
        print(f"DEBUG GCF ({request_id}): No SRT segments generated, no SRT file created.")
        local_srt_path = None # No subtitles if no segments

    # --- 4. DALL-E Image Generation ---
    # (Assuming openai_api_key is now passed and openai client is initialized)
    if openai_api_key: openai_client = OpenAI(api_key=openai_api_key)
    else: print(f"DEBUG GCF ({request_id}): OpenAI API Key missing, cannot generate DALL-E images."); shutil.rmtree(temp_dir, ignore_errors=True); return (json.dumps({"success": False, "error": "OpenAI API Key missing."}), 400, {'Content-Type': 'application/json'})

    dalle_image_paths = []
    num_dalle_images_to_generate = max(1, min(len(dalle_prompts), 5)) # Generate 1 to 5 images
    
    for i in range(num_dalle_images_to_generate):
        prompt = dalle_prompts[i % len(dalle_prompts)] # Cycle through prompts if fewer prompts than images
        print(f"DEBUG GCF ({request_id}): Generating DALL-E image {i+1} with prompt: {prompt[:50]}...")
        try:
            response = openai_client.images.generate(
                model="dall-e-2", # Or "dall-e-3" (DALL-E 3 is more expensive, higher quality, diff sizes)
                prompt=prompt,
                n=1,
                size="1024x1024", # For DALL-E 2; DALL-E 3 uses 1024x1792 for 9:16
                response_format="url" # Get temporary URL
            )
            image_url = response.data[0].url
            image_content = requests.get(image_url, timeout=60).content
            
            image_filename = f"dalle_image_{i}.png" # DALL-E often returns PNG
            local_image_path = os.path.join(temp_dir, image_filename)
            with open(local_image_path, "wb") as img_f:
                img_f.write(image_content)
            dalle_image_paths.append(local_image_path)
            print(f"DEBUG GCF ({request_id}): Downloaded DALL-E image to {local_image_path}")
        except Exception as e:
            print(f"DEBUG GCF ERROR ({request_id}): DALL-E image generation/download failed for prompt '{prompt[:50]}...': {e}")
            # Decide: continue without this image, or fail? For now, continue.
    
    if not dalle_image_paths: # Fallback if DALL-E fails completely
        print(f"DEBUG GCF ({request_id}): DALL-E failed to generate any images. Using fallback color slide.");
        # Create a placeholder image or use FFmpeg color source later
        # For now, we'll let FFmpeg use its default if no image inputs are specified, or error out.

    # --- 5. Download Music (if provided) ---
    local_music_path = None
    if music_url_from_wp:
        try:
            print(f"DEBUG GCF ({request_id}): Downloading music from {music_url_from_wp}")
            music_content = requests.get(music_url_from_wp, timeout=60).content
            local_music_path = os.path.join(temp_dir, "background_music.mp3")
            with open(local_music_path, "wb") as music_f:
                music_f.write(music_content)
            print(f"DEBUG GCF ({request_id}): Downloaded music to {local_music_path}")
        except Exception as e:
            print(f"DEBUG GCF WARNING ({request_id}): Failed to download music: {e}. Proceeding without music.")
            local_music_path = None

    # --- 6. Construct and Run FFmpeg Command ---
    output_video_path = os.path.join(temp_dir, f"final_video_{request_id}.mp4")
    ffmpeg_cmd = ["ffmpeg"]

    # --- FFmpeg Inputs (Images) ---
    if dalle_image_paths:
        image_duration_each = audio_duration_seconds / len(dalle_image_paths)
        for img_path in dalle_image_paths:
            ffmpeg_cmd.extend(["-loop", "1", "-t", str(image_duration_each), "-i", img_path])
    else: # Fallback: Create a color source if no images
        ffmpeg_cmd.extend(["-f", "lavfi", "-i", f"color=c=blue:s=720x1280:d={audio_duration_seconds}"])


    # --- FFmpeg Inputs (Audio) ---
    ffmpeg_cmd.extend(["-i", local_fish_audio_mp3_path]) # Main Voiceover
    audio_input_count = 1
    music_map_index = -1
    if local_music_path:
        ffmpeg_cmd.extend(["-i", local_music_path]) # Background Music
        audio_input_count += 1
        music_map_index = len(dalle_image_paths) + 1 if dalle_image_paths else 1 # Index of music input stream

    # --- FFmpeg Filter Complex for Visuals, Audio Mixing, Subtitles ---
    filter_complex_parts = []
    input_streams_for_concat = []

    # Visuals (Image sequence to video stream)
    if dalle_image_paths:
        for i in range(len(dalle_image_paths)):
            filter_complex_parts.append(f"[{i}:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]")
            input_streams_for_concat.append(f"[v{i}]")
        filter_complex_parts.append("".join(input_streams_for_concat) + f"concat=n={len(dalle_image_paths)}:v=1:a=0[vidout]")
        video_output_stream = "[vidout]"
    else: # Color source
         filter_complex_parts.append(f"[0:v]setsar=1[vidout]") # If color source is input 0
         video_output_stream = "[vidout]"


    # Audio Mixing
    if local_music_path:
        vo_stream_index = len(dalle_image_paths) if dalle_image_paths else 0 # VO is after images or is input 0
        music_stream_index = vo_stream_index + 1
        filter_complex_parts.append(f"[{vo_stream_index}:a]volume=1.0[a_vo]")
        filter_complex_parts.append(f"[{music_stream_index}:a]volume=0.15[a_music]")
        filter_complex_parts.append(f"[a_vo][a_music]amix=inputs=2:duration=first:dropout_transition=3[aout]")
        audio_output_stream = "[aout]"
    else: # Only Voiceover
        vo_stream_index = len(dalle_image_paths) if dalle_image_paths else 0
        filter_complex_parts.append(f"[{vo_stream_index}:a]volume=1.0[aout]")
        audio_output_stream = "[aout]"

    # Subtitles (if SRT file was created)
    if local_srt_path:
         # FFmpeg style: Font, Size, PrimaryColour (AABBGGRR), BackColour (AABBGGRR), Alignment (ASS style)
         # Alignment: 1=bottom-left, 2=bottom-center, 3=bottom-right, 4=mid-left, 5=mid-center, etc.
         # This styling is basic. More complex styling often requires libass and specific font configurations.
         font_file_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" # Example, check available fonts in container
         # A safer bet might be to use a very common font like Arial if available, or bundle one.
         # For now, let's try a common path. If it fails, we need to ensure a font file is in the container.
         # Or use a simpler FFmpeg text draw filter if full SRT styling is an issue.
         subtitle_style = f"FontName=Arial,FontSize=22,PrimaryColour=&H00FFFF&,BackColour=&H99000000&,Alignment=2,MarginV=25"
         filter_complex_parts.append(f"{video_output_stream}subtitles=filename='{local_srt_path}':force_style='{subtitle_style}'[vout]")
         final_video_stream_for_map = "[vout]"
    else:
         final_video_stream_for_map = video_output_stream # Pass through if no subtitles

    if filter_complex_parts:
        ffmpeg_cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
    
    ffmpeg_cmd.extend(["-map", final_video_stream_for_map])
    ffmpeg_cmd.extend(["-map", audio_output_stream])
    
    ffmpeg_cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-aspect", "9:16", "-s", "720x1280", # Output size
        "-fps_mode", "cfr", "-r", "30", # Force constant frame rate
        "-t", str(audio_duration_seconds), # Set total duration
        "-y", output_video_path
    ])

    print(f"DEBUG GCF ({request_id}): FFmpeg command to run: {' '.join(ffmpeg_cmd)}")
    try:
        process = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=True, timeout=240) # 4 min timeout for FFmpeg
        print(f"DEBUG GCF ({request_id}): FFmpeg stdout: {process.stdout}")
        print(f"DEBUG GCF ({request_id}): FFmpeg stderr: {process.stderr}")
        print(f"DEBUG GCF ({request_id}): FFmpeg completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"DEBUG GCF ERROR ({request_id}): FFmpeg failed with exit code {e.returncode}")
        print(f"DEBUG GCF ERROR ({request_id}): FFmpeg stdout: {e.stdout}")
        print(f"DEBUG GCF ERROR ({request_id}): FFmpeg stderr: {e.stderr}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return (json.dumps({"success": False, "error": "FFmpeg processing failed.", "details": e.stderr[:500]}), 500, {'Content-Type': 'application/json'})
    except subprocess.TimeoutExpired:
        print(f"DEBUG GCF ERROR ({request_id}): FFmpeg timed out.")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return (json.dumps({"success": False, "error": "FFmpeg processing timed out."}), 500, {'Content-Type': 'application/json'})


    # --- 7. Upload Final Video to GCS ---
    final_video_gcs_blob_name = f"final-videos/viral_video_{request_id}.mp4"
    final_bucket = storage_client.bucket(GCS_FINAL_VIDEO_BUCKET_NAME)
    final_blob = final_bucket.blob(final_video_gcs_blob_name)
    try:
        print(f"DEBUG GCF ({request_id}): Uploading final video {output_video_path} to gs://{GCS_FINAL_VIDEO_BUCKET_NAME}/{final_video_gcs_blob_name}")
        final_blob.upload_from_filename(output_video_path, content_type='video/mp4')
        # Make the final video publicly readable (adjust permissions as needed for production)
        final_blob.make_public()
        final_video_public_url = final_blob.public_url
        print(f"DEBUG GCF ({request_id}): Final video uploaded. Public URL: {final_video_public_url}")
    except Exception as e:
        print(f"DEBUG GCF ERROR ({request_id}): Failed to upload final video to GCS: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return (json.dumps({"success": False, "error": f"Failed to upload final video to GCS: {str(e)[:200]}"}), 500, {'Content-Type': 'application/json'})

    # --- 8. Cleanup and Return ---
    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"DEBUG GCF ({request_id}): Cleaned up temp directory: {temp_dir}")
    
    end_time_total_gcf = time.time()
    print(f"DEBUG GCF ({request_id}): Total GCF execution time: {round(end_time_total_gcf - start_time_total_gcf, 2)}s")
    
    return (json.dumps({
        "success": True,
        "message": "Video generated successfully by GCF with FFmpeg.",
        "final_video_url": final_video_public_url,
        "final_audio_duration": round(audio_duration_seconds, 3) # For WP to know
    }), 200, {'Content-Type': 'application/json'})

print("DEBUG: main.py loaded and orchestrate_video_with_ffmpeg function defined.")
