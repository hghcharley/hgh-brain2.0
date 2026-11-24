#!/usr/bin/env python3
"""Review sheet of Guest's face in every listening Guest shot (cutaways and splits): 8+ face crops per second.
usage: guest_faces_v2.py <clip.mp4> [dst.jpg] [fps]   (reads <name>.edl.json next to the mp4; works on clean or captioned)
One row per shot (wraps every 32 crops), each crop labelled with its output time. No face found = red frame."""
import json, subprocess, sys, os
import numpy as np
import cv2
from PIL import Image, ImageDraw

from common import POD, FPS, YUNET


def frames(mp4, t0, t1, fps):
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', mp4],
                       capture_output=True, text=True).stdout.strip().split(',')
    w, h = int(p[0]), int(p[1])
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', f'{t0:.3f}', '-i', mp4, '-t', f'{t1 - t0:.3f}', '-vf', f'fps={fps}',
                        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, h, w, 3), w, h


def main():
    mp4 = sys.argv[1]
    base = mp4[:-4]
    name = os.path.basename(base)
    d = os.path.dirname(mp4)
    edl_p = base + '.edl.json'
    if not os.path.exists(edl_p):
        edl_p = os.path.join(os.path.dirname(d), name + '.edl.json')
    edl = json.load(open(edl_p))
    dst = sys.argv[2] if len(sys.argv) > 2 else base + '_guest.jpg'
    fps = float(sys.argv[3]) if len(sys.argv) > 3 else 8
    det = None
    T = 120
    rows = []
    for i, s in enumerate(edl['shots']):
        if s['kind'] not in ('guest_cutaway', 'split'):
            continue
        t0, t1 = s['out_start'], s['out_end']
        fr, w, h = frames(mp4, t0, t1, fps)
        if det is None:
            det = cv2.FaceDetectorYN.create(YUNET, '', (w, h), 0.5)
        y0 = h // 2 if s['kind'] == 'split' else 0
        crops = []
        for k, f in enumerate(fr):
            reg = f[y0:]
            det.setInputSize((reg.shape[1], reg.shape[0]))
            _, faces = det.detect(reg)
            ok = faces is not None and len(faces)
            if ok:
                fc = max(faces, key=lambda z: z[-1])
                cx, cy, fw = fc[0] + fc[2] / 2, fc[1] + fc[3] / 2, max(fc[2], fc[3])
            else:
                cx, cy, fw = reg.shape[1] / 2, reg.shape[0] * 0.35, reg.shape[1] * 0.35
            hw = int(fw * 0.95)
            x0, yy0 = int(max(0, cx - hw)), int(max(0, cy - hw))
            c = reg[yy0:yy0 + 2 * hw, x0:x0 + 2 * hw]
            im = Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)).resize((T, T))
            dr = ImageDraw.Draw(im)
            if not ok:
                dr.rectangle([0, 0, T - 1, T - 1], outline=(255, 0, 0), width=3)
            dr.text((2, T - 11), f'{t0 + k / fps:.2f}', fill=(255, 255, 0))
            crops.append(im)
        rows.append((f"#{i} {s['kind']}  {t0:.2f}-{t1:.2f}s", crops))
    per = 16
    lines = sum(max(1, (len(c) + per - 1) // per) for _, c in rows)
    W = per * (T + 2) + 4
    img = Image.new('RGB', (W, max(1, lines) * (T + 16) + 4), (20, 20, 20))
    dr = ImageDraw.Draw(img)
    y = 2
    for lab, cs in rows:
        for j in range(0, max(1, len(cs)), per):
            dr.text((4, y), lab if j == 0 else '', fill=(255, 220, 120))
            for k, c in enumerate(cs[j:j + per]):
                img.paste(c, (2 + k * (T + 2), y + 14))
            y += T + 16
    img.save(dst, quality=88)
    print(dst, len(rows), 'shots')


if __name__ == '__main__':
    main()
