import os
import math
import subprocess
import numpy as np
from PIL import Image
import imageio_ffmpeg

def create_cinematic_videos():
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    raw_dir = 'temp_raw_frames'
    
    # 1. Load all 240 source frames into memory
    print("Loading 240 source frames...")
    source_frames = []
    for i in range(1, 241):
        fpath = os.path.join(raw_dir, f"frame_{i:04d}.png")
        img = Image.open(fpath).convert('RGB')
        source_frames.append(np.array(img, dtype=np.float32))
    
    num_src = len(source_frames)
    max_src_idx = num_src - 1 # 239
    print(f"Loaded {num_src} frames into RAM.")

    # Audio file preparation
    audio_path = 'test_audio.wav'
    has_audio = os.path.exists(audio_path)

    # Helper function to interpolate between source frames
    def sample_frame(pos):
        pos = max(0.0, min(float(max_src_idx), pos))
        idx0 = int(pos)
        idx1 = min(max_src_idx, idx0 + 1)
        alpha = pos - idx0
        if alpha <= 0.0001:
            return source_frames[idx0].astype(np.uint8)
        elif alpha >= 0.9999:
            return source_frames[idx1].astype(np.uint8)
        else:
            blended = (1.0 - alpha) * source_frames[idx0] + alpha * source_frames[idx1]
            return np.clip(blended, 0, 255).astype(np.uint8)

    # -------------------------------------------------------------
    # 1. Master Video: Seamless Looping Video (10s, 30fps = 300 frames)
    # Starts at multi-portrait, zooms in smoothly, returns smoothly to multi-portrait
    # -------------------------------------------------------------
    output_master = 'cinematic_background_video.mp4'
    print(f"\n--- Generating Master Seamless Looping Video: {output_master} ---")
    
    # Build ffmpeg command with audio looped/faded
    cmd_master = [
        ffmpeg_exe, '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', '1280x720', '-pix_fmt', 'rgb24', '-r', '30',
        '-i', '-', # video from stdin
    ]
    if has_audio:
        cmd_master += [
            '-i', audio_path,
            '-filter_complex', '[0:v]scale=1920:1080:flags=lanczos,cas=0.35[v];[1:a]afade=t=in:ss=0:d=0.2,afade=t=out:st=9.8:d=0.2[a]',
            '-map', '[v]', '-map', '[a]',
            '-c:a', 'aac', '-b:a', '192k'
        ]
    else:
        cmd_master += [
            '-vf', 'scale=1920:1080:flags=lanczos,cas=0.35',
            '-c:v', 'libx264'
        ]

    cmd_master += [
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
        '-pix_fmt', 'yuv420p',
        '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
        '-movflags', '+faststart',
        output_master
    ]

    TOTAL_OUT_FRAMES = 300 # Exactly 10.0 seconds at 30 fps
    proc = subprocess.Popen(cmd_master, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    
    for i in range(TOTAL_OUT_FRAMES):
        # Cosine smoothstep curve: 0 -> 1 -> 0
        # Phase goes from 0 to 2*pi
        phase = (i / float(TOTAL_OUT_FRAMES)) * 2.0 * math.pi
        weight = 0.5 * (1.0 - math.cos(phase))
        src_pos = weight * max_src_idx
        
        frame = sample_frame(src_pos)
        proc.stdin.write(frame.tobytes())
        
        if (i + 1) % 50 == 0:
            print(f"Master loop: rendered {i+1}/{TOTAL_OUT_FRAMES} frames...")
            
    proc.stdin.close()
    proc.wait()
    print(f"Master video finished with exit code {proc.returncode}")

    # -------------------------------------------------------------
    # 2. Linear Forward Video (10s, 30fps = 300 frames)
    # Plays full reference sequence from multi-portrait to close-up at 1080p 30fps
    # -------------------------------------------------------------
    output_linear = 'cinematic_background_forward_1080p.mp4'
    print(f"\n--- Generating Forward Video: {output_linear} ---")
    
    cmd_linear = [
        ffmpeg_exe, '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', '1280x720', '-pix_fmt', 'rgb24', '-r', '30',
        '-i', '-',
    ]
    if has_audio:
        cmd_linear += [
            '-i', audio_path,
            '-filter_complex', '[0:v]scale=1920:1080:flags=lanczos,cas=0.35[v];[1:a]afade=t=in:ss=0:d=0.2,afade=t=out:st=9.8:d=0.2[a]',
            '-map', '[v]', '-map', '[a]',
            '-c:a', 'aac', '-b:a', '192k'
        ]
    else:
        cmd_linear += [
            '-vf', 'scale=1920:1080:flags=lanczos,cas=0.35',
            '-c:v', 'libx264'
        ]

    cmd_linear += [
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
        '-pix_fmt', 'yuv420p',
        '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
        '-movflags', '+faststart',
        output_linear
    ]

    proc2 = subprocess.Popen(cmd_linear, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for i in range(TOTAL_OUT_FRAMES):
        src_pos = (i / float(TOTAL_OUT_FRAMES - 1)) * max_src_idx
        frame = sample_frame(src_pos)
        proc2.stdin.write(frame.tobytes())
        if (i + 1) % 50 == 0:
            print(f"Forward: rendered {i+1}/{TOTAL_OUT_FRAMES} frames...")
            
    proc2.stdin.close()
    proc2.wait()
    print(f"Forward video finished with exit code {proc2.returncode}")

    # -------------------------------------------------------------
    # 3. Crossfade Loop Video (10s, 30fps = 300 frames)
    # Plays forward, with smooth dissolve at the end back into frame 1
    # -------------------------------------------------------------
    output_crossfade = 'cinematic_background_crossfade_1080p.mp4'
    print(f"\n--- Generating Crossfade Loop Video: {output_crossfade} ---")
    
    cmd_cf = [
        ffmpeg_exe, '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', '1280x720', '-pix_fmt', 'rgb24', '-r', '30',
        '-i', '-',
    ]
    if has_audio:
        cmd_cf += [
            '-i', audio_path,
            '-filter_complex', '[0:v]scale=1920:1080:flags=lanczos,cas=0.35[v];[1:a]afade=t=in:ss=0:d=0.2,afade=t=out:st=9.8:d=0.2[a]',
            '-map', '[v]', '-map', '[a]',
            '-c:a', 'aac', '-b:a', '192k'
        ]
    else:
        cmd_cf += [
            '-vf', 'scale=1920:1080:flags=lanczos,cas=0.35',
            '-c:v', 'libx264'
        ]

    cmd_cf += [
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '16',
        '-pix_fmt', 'yuv420p',
        '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
        '-movflags', '+faststart',
        output_crossfade
    ]

    proc3 = subprocess.Popen(cmd_cf, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    # Dissolve over the last 45 frames (1.5 seconds) back to frame 0
    fade_len = 45
    for i in range(TOTAL_OUT_FRAMES):
        src_pos = (i / float(TOTAL_OUT_FRAMES - 1)) * max_src_idx
        f_current = sample_frame(src_pos)
        
        if i >= TOTAL_OUT_FRAMES - fade_len:
            blend_factor = (i - (TOTAL_OUT_FRAMES - fade_len)) / float(fade_len)
            f_start = source_frames[0].astype(np.float32)
            f_cur_float = f_current.astype(np.float32)
            f_blended = np.clip((1.0 - blend_factor) * f_cur_float + blend_factor * f_start, 0, 255).astype(np.uint8)
            proc3.stdin.write(f_blended.tobytes())
        else:
            proc3.stdin.write(f_current.tobytes())
            
        if (i + 1) % 50 == 0:
            print(f"Crossfade: rendered {i+1}/{TOTAL_OUT_FRAMES} frames...")
            
    proc3.stdin.close()
    proc3.wait()
    print(f"Crossfade video finished with exit code {proc3.returncode}")

    print("\nAll video generations completed successfully!")

if __name__ == '__main__':
    create_cinematic_videos()
