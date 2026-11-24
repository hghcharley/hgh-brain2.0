#!/usr/bin/env python3
"""Contact sheet of a CAPTIONED clip: frame 0, frame at 1.5 s, the middle of every shot, and the last frame.
Library for render_v2.py and scripts/check.py sheet."""
import json, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw

from common import FPS
KIND = {'host': 'host', 'guest_speaking': 'guest-talk', 'guest_cutaway': 'guest-cutaway', 'split': 'SPLIT'}


def sheet(mp4, edl, dst, cw=270):
    N = edl['frames']
    picks = [(0, 'frame 0'), (min(N - 1, round(1.5 * FPS)), '1.5 s')]
    for i, s in enumerate(edl['shots']):
        f0 = round(s['out_start'] * FPS)
        picks.append((f0 + s['frames'] // 2, f"#{i} {KIND.get(s['kind'], s['kind'])} {s['look']}  {s['out_start']:.1f}-{s['out_end']:.1f}s"))
    picks.append((N - 1, 'last frame'))
    ch = cw * 16 // 9
    fs = sorted(set(f for f, _ in picks))
    sel = '+'.join(f'eq(n\\,{f})' for f in fs)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', mp4, '-vf', f'select={sel},scale={cw}:{ch}', '-fps_mode', 'passthrough',
                        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, ch, cw, 3)
    idx = {f: i for i, f in enumerate(fs)}
    n = len(picks); cols = min(n, 8); rows = (n + cols - 1) // cols
    lab = 18
    im = Image.new('RGB', (cols * (cw + 4), rows * (ch + lab + 4)), (25, 25, 25))
    d = ImageDraw.Draw(im)
    for k, (f, txt) in enumerate(picks):
        x, y = (k % cols) * (cw + 4), (k // cols) * (ch + lab + 4)
        d.text((x + 2, y + 3), f'{txt}', fill=(255, 220, 120))
        if idx[f] < len(fr): im.paste(Image.fromarray(fr[idx[f]]), (x, y + lab))
    im.save(dst, quality=86)
    return dst


