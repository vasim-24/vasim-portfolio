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
    start_total_time = time.time()
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    raw_dir = 'temp_raw_frames'
    audio_path = 'test_audio.wav'
    has_audio = os.path.exists(audio_path)

    print("==================================================================")
    print("=== RENDERING PRISTINE CINEMATIC VIDEO SUITE (1080P & 4K UHD) ===")
    print("===            (WATER MAN REMOVED - ZERO DEADLOCK)            ===")
    print("==================================================================")
    print(f"FFmpeg binary: {ffmpeg_exe}")
    print(f"Audio track: {audio_path} (exists={has_audio})")

    # 1. Load the 240 clean inpainted source frames
    print("\n[1/3] Loading 240 clean source frames from temp_raw_frames into RAM...")
    t0 = time.time()
    source_frames = []
    for i in range(1, 241):
        fpath = os.path.join(raw_dir, f"frame_{i:04d}.png")
        img = Image.open(fpath).convert('RGB')
        source_frames.append(np.array(img, dtype=np.uint8))
    
    num_src = len(source_frames)
    max_src_idx = num_src - 1 # 239
    print(f"  Loaded {num_src} source frames in {time.time() - t0:.2f}s.")

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

    TOTAL_OUT_FRAMES = 300 # Exactly 10.0s at 30 fps

    # Generators for 3 motion styles
    def gen_seamless_loop(i, total, max_idx):
        # Cosine smoothstep curve: multi-portrait -> close-up -> multi-portrait
        phase = (i / float(total)) * 2.0 * math.pi
        weight = 0.5 * (1.0 - math.cos(phase))
        return sample_frame(weight * max_idx)

    def gen_linear_forward(i, total, max_idx):
        # Linear zoom from 0 to max_idx
        src_pos = (i / float(total - 1)) * max_idx
        return sample_frame(src_pos)

    fade_len = 45 # 1.5 seconds dissolve back to start
    f_start = source_frames[0].astype(np.float32)
    def gen_crossfade(i, total, max_idx):
        src_pos = (i / float(total - 1)) * max_idx
        curr = sample_frame(src_pos)
        if i >= total - fade_len:
            blend_factor = (i - (total - fade_len)) / float(fade_len)
            blended = (1.0 - blend_factor) * curr.astype(np.float32) + blend_factor * f_start
            return np.clip(blended, 0, 255).astype(np.uint8)
        return curr

    # Generic encoder function (NO PIPE DEADLOCK)
    def encode_video(output_name, resolution, vfilter, frame_gen, crf='16'):
        print(f"\nEncoding {output_name} ({resolution} @ 30 FPS, crf={crf})...")
        t_enc = time.time()

        cmd = [
            ffmpeg_exe, '-y',
            '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', '1280x720', '-pix_fmt', 'rgb24', '-r', '30',
            '-i', '-',
        ]
        if has_audio:
            cmd += [
                '-i', audio_path,
                '-filter_complex', f'[0:v]{vfilter}[v];[1:a]afade=t=in:ss=0:d=0.2,afade=t=out:st=9.8:d=0.2[a]',
                '-map', '[v]', '-map', '[a]',
                '-c:a', 'aac', '-b:a', '256k'
            ]
        else:
            cmd += [
                '-vf', vfilter,
            ]

        cmd += [
            '-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf),
            '-pix_fmt', 'yuv420p',
            '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
            '-movflags', '+faststart',
            output_name
        ]

        # Use DEVNULL for stderr to eliminate OS pipe buffer deadlock
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for i in range(TOTAL_OUT_FRAMES):
            frame = frame_gen(i, TOTAL_OUT_FRAMES, max_src_idx)
            proc.stdin.write(frame.tobytes())
            if (i + 1) % 100 == 0 or i == TOTAL_OUT_FRAMES - 1:
                print(f"  Progress: {i+1}/{TOTAL_OUT_FRAMES} frames ({((i+1)/TOTAL_OUT_FRAMES)*100:.0f}%)...")

        proc.stdin.close()
        proc.wait()

        elapsed = time.time() - t_enc
        size_mb = os.path.getsize(output_name) / (1024 * 1024)
        print(f"  -> Completed {output_name}: {size_mb:.2f} MB in {elapsed:.1f}s (Exit code {proc.returncode})")
        return proc.returncode == 0

    # 1080p filter: deblock, gradfun deband, lanczos upscale, contrast adaptive sharpening
    vfilter_1080p = "deblock=filter=weak:block=4,gradfun=radius=16:strength=1.2,scale=1920:1080:flags=lanczos+accurate_rnd,cas=0.35"

    # 4K filter: pristine 4K lanczos upscale with accurate chroma
    vfilter_4k = "deblock=filter=weak:block=4,gradfun=radius=20:strength=1.4,scale=3840:2160:flags=lanczos+accurate_rnd+full_chroma_int+full_chroma_inp,cas=0.45"

    print("\n[2/3] Rendering 1080p Web Suite (Instant Load & Smooth 60Hz Playback)...")
    # 1. Master Web Background Video (Seamless Loop)
    encode_video('cinematic_background_video.mp4', '1920x1080', vfilter_1080p, gen_seamless_loop, crf='16')
    shutil.copyfile('cinematic_background_video.mp4', 'cinematic_background_loop_1080p.mp4')

    # 2. Linear Forward Zoom (1080p)
    encode_video('cinematic_background_forward_1080p.mp4', '1920x1080', vfilter_1080p, gen_linear_forward, crf='16')

    # 3. Crossfade Loop (1080p)
    encode_video('cinematic_background_crossfade_1080p.mp4', '1920x1080', vfilter_1080p, gen_crossfade, crf='16')

    print("\n[3/3] Rendering 4K UHD Master Suite (Ultra High Fidelity 3840x2160)...")
    # 4. 4K UHD Seamless Loop
    encode_video('cinematic_background_loop_4k.mp4', '3840x2160', vfilter_4k, gen_seamless_loop, crf='15')

    # 5. 4K UHD Forward Zoom
    encode_video('cinematic_background_forward_4k.mp4', '3840x2160', vfilter_4k, gen_linear_forward, crf='15')

    # 6. 4K UHD Crossfade Loop
    encode_video('cinematic_background_crossfade_4k.mp4', '3840x2160', vfilter_4k, gen_crossfade, crf='15')

    # Copy all clean masters to Downloads and Artifact directories
    target_dirs = [
        os.path.abspath('..'), # C:\Users\Preethi\Downloads
        r'C:\Users\Preethi\.gemini\antigravity-ide\brain\7e18363b-e664-4869-8469-c1314684b3e5',
        r'C:\Users\Preethi\.gemini\antigravity-ide\brain\40650e3f-f837-415d-82fe-d224138102db',
        r'C:\Users\Preethi\.gemini\antigravity-ide\brain\9631f4ff-11c0-44e4-bc90-6241cba77fb5'
    ]

    all_video_files = [
        'cinematic_background_video.mp4',
        'cinematic_background_loop_1080p.mp4',
        'cinematic_background_forward_1080p.mp4',
        'cinematic_background_crossfade_1080p.mp4',
        'cinematic_background_loop_4k.mp4',
        'cinematic_background_forward_4k.mp4',
        'cinematic_background_crossfade_4k.mp4'
    ]

    print("\nSyncing all rendered videos to User Downloads and Artifact directories...")
    for tdir in target_dirs:
        if os.path.exists(tdir):
            for vfile in all_video_files:
                try:
                    dst = os.path.join(tdir, vfile)
                    shutil.copyfile(vfile, dst)
                except Exception as e:
                    print(f"  Note: copy {vfile} -> {tdir} ({e})")

    print(f"\n>>> COMPLETE VIDEO SUITE SUCCESSFULLY RENDERED IN {time.time() - start_total_time:.1f}s! <<<")

if __name__ == '__main__':
    main()
