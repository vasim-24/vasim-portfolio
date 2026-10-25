import os
import sys
import math
import shutil
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import numpy as np
from PIL import Image
import imageio_ffmpeg

def main():
    start_time = time.time()
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    raw_dir = 'temp_raw_frames'
    backup_dir = 'ezgif_backup_720p'
    os.makedirs(backup_dir, exist_ok=True)

    print("=== REMASTERING LIVE WEB FRAME ASSETS (1080P RESTORATION) ===")

    # 1. Back up existing low-res ezgif frames if not already backed up
    first_backup = os.path.join(backup_dir, 'ezgif-frame-001.jpg')
    if not os.path.exists(first_backup):
        print(f"Backing up original low-res 720p ezgif frames to {backup_dir}...")
        for i in range(1, 301):
            src = f"ezgif-frame-{i:03d}.jpg"
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(backup_dir, src))
        print("Backup complete.")

    # 2. Load 240 raw source PNG frames
    print("Loading 240 raw uncompressed source PNG frames into RAM...")
    t_load = time.time()
    source_frames = []
    for i in range(1, 241):
        fpath = os.path.join(raw_dir, f"frame_{i:04d}.png")
        img = Image.open(fpath).convert('RGB')
        source_frames.append(np.array(img, dtype=np.uint8))
    
    max_src_idx = len(source_frames) - 1 # 239
    print(f"Loaded {len(source_frames)} source frames in {time.time() - t_load:.2f}s.")

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

    # Cosine smoothstep for seamless loop
    TOTAL_OUT_FRAMES = 300

    def process_and_save_frame(frame_idx):
        # 1-indexed: 1 to 300
        # Phase from 0 to 2*pi
        phase = ((frame_idx - 1) / float(TOTAL_OUT_FRAMES)) * 2.0 * math.pi
        weight = 0.5 * (1.0 - math.cos(phase))
        src_pos = weight * max_src_idx
        
        frame_rgb = sample_frame(src_pos)
        out_filename = f"ezgif-frame-{frame_idx:03d}.jpg"

        # Apply multi-pass cinema restoration filter via FFmpeg:
        # 1. deblock=filter=weak:block=4 (eliminates DCT blocks)
        # 2. gradfun=radius=16:strength=1.2 (debands reddish-orange sunset gradients)
        # 3. scale=1920:1080:flags=lanczos+accurate_rnd (pristine sinc-lanczos upscale)
        # 4. cas=0.40 (AMD Contrast Adaptive Sharpening on hair, facial features, motorcycle)
        # 5. high quality JPEG encoding (-q:v 4)
        cmd = [
            ffmpeg_exe, '-y',
            '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', '1280x720', '-pix_fmt', 'rgb24',
            '-i', '-',
            '-vf', 'deblock=filter=weak:block=4,gradfun=radius=16:strength=1.2,scale=1920:1080:flags=lanczos+accurate_rnd,cas=0.40',
            '-q:v', '4',
            out_filename
        ]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.stdin.write(frame_rgb.tobytes())
        proc.stdin.close()
        proc.wait()
        return frame_idx

    print(f"\nProcessing all {TOTAL_OUT_FRAMES} frames in parallel (1920x1080, Lanczos + CAS + Deblock + Gradfun)...")
    t_process = time.time()
    
    # Run in parallel using 8 worker threads
    completed = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        for idx in executor.map(process_and_save_frame, range(1, TOTAL_OUT_FRAMES + 1)):
            completed += 1
            if completed % 50 == 0 or completed == TOTAL_OUT_FRAMES:
                print(f"  Remastered {completed}/{TOTAL_OUT_FRAMES} frames ({completed/TOTAL_OUT_FRAMES*100:.0f}%)...")

    total_time = time.time() - t_process
    print(f"\nAll {TOTAL_OUT_FRAMES} web frames remastered successfully in {total_time:.2f}s ({TOTAL_OUT_FRAMES/total_time:.1f} fps)!")

    # Verify frame 1 and 150
    im1 = Image.open('ezgif-frame-001.jpg')
    print(f"Verified ezgif-frame-001.jpg: {im1.size}, size: {os.path.getsize('ezgif-frame-001.jpg')} bytes")

if __name__ == '__main__':
    main()
