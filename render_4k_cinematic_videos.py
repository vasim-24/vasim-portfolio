import os
import sys
import math
import shutil
import subprocess
import time
import numpy as np
from PIL import Image
import imageio_ffmpeg

def main():
    start_time = time.time()
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    raw_dir = 'temp_raw_frames'
    audio_path = 'test_audio.wav'
    has_audio = os.path.exists(audio_path)
    
    print("==========================================================")
    print("=== RENDERING CINEMATIC 4K UHD (3840x2160) VIDEO SUITE ===")
    print("==========================================================")
    print(f"FFmpeg executable: {ffmpeg_exe}")
    print(f"Audio track: {audio_path} (exists={has_audio})")

    # 1. Load source frames
    print("Loading 240 raw source PNG frames into RAM...")
    t_load = time.time()
    source_frames = []
    for i in range(1, 241):
        fpath = os.path.join(raw_dir, f"frame_{i:04d}.png")
        img = Image.open(fpath).convert('RGB')
        source_frames.append(np.array(img, dtype=np.uint8))
    
    num_src = len(source_frames)
    max_src_idx = num_src - 1 # 239
    print(f"Loaded {num_src} frames in {time.time() - t_load:.2f}s.")

    # Helper function for smooth sub-frame interpolation
    def sample_frame(pos):
        pos = max(0.0, min(float(max_src_idx), float(pos)))
        idx0 = int(pos)
        idx1 = min(max_src_idx, idx0 + 1)
        alpha = pos - idx0
        if alpha < 0.005:
            return source_frames[idx0]
        elif alpha > 0.995:
            return source_frames[idx1]
        else:
            blended = (1.0 - alpha) * source_frames[idx0].astype(np.float32) + alpha * source_frames[idx1].astype(np.float32)
            return blended.astype(np.uint8)

    TOTAL_OUT_FRAMES = 300 # 10.0 seconds at 30 fps

    # 4K Video Restoration & Mastering Filter:
    # 1. deblock=filter=weak:block=4 (destroys blockiness from source)
    # 2. gradfun=radius=20:strength=1.4 (debands sunset gradients)
    # 3. scale=3840:2160:flags=lanczos+accurate_rnd+full_chroma_int+full_chroma_inp (True 4K UHD Sinc-Lanczos scaling)
    # 4. cas=0.45 (AMD Contrast Adaptive Sharpening on hair, facial details, motorcycle)
    vfilter_4k = "deblock=filter=weak:block=4,gradfun=radius=20:strength=1.4,scale=3840:2160:flags=lanczos+accurate_rnd+full_chroma_int+full_chroma_inp,cas=0.45"

    def render_4k_video(output_filename, frame_generator_func):
        print(f"\nRendering 4K UHD Video: {output_filename} (3840x2160 @ 30 FPS)...")
        t_render = time.time()

        cmd = [
            ffmpeg_exe, '-y',
            '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', '1280x720', '-pix_fmt', 'rgb24', '-r', '30',
            '-i', '-',
        ]
        if has_audio:
            cmd += [
                '-i', audio_path,
                '-filter_complex', f'[0:v]{vfilter_4k}[v];[1:a]afade=t=in:ss=0:d=0.2,afade=t=out:st=9.8:d=0.2[a]',
                '-map', '[v]', '-map', '[a]',
                '-c:a', 'aac', '-b:a', '320k'
            ]
        else:
            cmd += [
                '-vf', vfilter_4k,
            ]

        cmd += [
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '15',
            '-profile:v', 'high', '-level', '5.2',
            '-pix_fmt', 'yuv420p',
            '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
            '-movflags', '+faststart',
            output_filename
        ]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for i in range(TOTAL_OUT_FRAMES):
            frame = frame_generator_func(i, TOTAL_OUT_FRAMES, max_src_idx)
            proc.stdin.write(frame.tobytes())
            if (i + 1) % 50 == 0 or i == TOTAL_OUT_FRAMES - 1:
                print(f"  Frame {i+1}/{TOTAL_OUT_FRAMES} ({(i+1)/TOTAL_OUT_FRAMES*100:.0f}%) encoded...")

        proc.stdin.close()
        proc.wait()
        
        file_size_mb = os.path.getsize(output_filename) / (1024 * 1024)
        elapsed = time.time() - t_render
        fps = TOTAL_OUT_FRAMES / elapsed
        print(f"Finished {output_filename} in {elapsed:.2f}s ({fps:.1f} fps)! File size: {file_size_mb:.2f} MB (Exit code: {proc.returncode})")
        return proc.returncode == 0

    # 1. Seamless Boomerang Loop: multi-portrait -> close-up -> multi-portrait (4K)
    def gen_seamless_loop(i, total, max_idx):
        phase = (i / float(total)) * 2.0 * math.pi
        weight = 0.5 * (1.0 - math.cos(phase))
        return sample_frame(weight * max_idx)

    render_4k_video('cinematic_background_video.mp4', gen_seamless_loop)
    shutil.copyfile('cinematic_background_video.mp4', 'cinematic_background_loop_4k.mp4')

    # 2. Linear Forward Zoom (4K)
    def gen_linear_forward(i, total, max_idx):
        src_pos = (i / float(total - 1)) * max_idx
        return sample_frame(src_pos)

    render_4k_video('cinematic_background_forward_4k.mp4', gen_linear_forward)

    # 3. Crossfade Loop with 1.5s smooth dissolve back to frame 0 (4K)
    fade_len = 45 # 1.5s at 30 fps
    f_start = source_frames[0].astype(np.float32)
    def gen_crossfade(i, total, max_idx):
        src_pos = (i / float(total - 1)) * max_idx
        curr = sample_frame(src_pos)
        if i >= total - fade_len:
            blend_factor = (i - (total - fade_len)) / float(fade_len)
            blended = (1.0 - blend_factor) * curr.astype(np.float32) + blend_factor * f_start
            return np.clip(blended, 0, 255).astype(np.uint8)
        return curr

    render_4k_video('cinematic_background_crossfade_4k.mp4', gen_crossfade)

    # Copy all 4K video outputs to Downloads directory and Artifacts directory
    target_dirs = [
        os.path.abspath('..'), # C:\Users\Preethi\Downloads
        r'C:\Users\Preethi\.gemini\antigravity-ide\brain\9631f4ff-11c0-44e4-bc90-6241cba77fb5',
        r'C:\Users\Preethi\.gemini\antigravity-ide\brain\2a2443dd-316b-4909-98b5-2508e890c957'
    ]

    files_to_copy = [
        'cinematic_background_video.mp4',
        'cinematic_background_loop_4k.mp4',
        'cinematic_background_forward_4k.mp4',
        'cinematic_background_crossfade_4k.mp4'
    ]

    print("\nCopying 4K masters to user Downloads and Artifact directories...")
    for tdir in target_dirs:
        if os.path.exists(tdir):
            for fname in files_to_copy:
                dst = os.path.join(tdir, fname)
                shutil.copyfile(fname, dst)
                print(f"  Copied {fname} -> {dst}")

    print(f"\nAll 4K video rendering tasks completed in {time.time() - start_time:.2f}s!")

if __name__ == '__main__':
    main()
