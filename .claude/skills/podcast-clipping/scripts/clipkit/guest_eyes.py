#!/usr/bin/env python3
"""Per-frame check of Guest's eyes in every Guest cutaway / split of a rendered clip (24 fps, on the rendered frames).
usage: guest_eyes_v2.py <clip.mp4> [...]
Prints, per shot: eye-openness ratio at the first and last 3 frames, and every run of 'shut' frames (ratio < 0.6 of
his median in the clip's Guest shots) with its length; also writes <base>_eyes.jpg with enlarged eye-strip crops of the
first/last 3 frames and of each flagged run, for a visual check."""
import json, math, os, subprocess, sys
import numpy as np
import cv2
from PIL import Image, ImageDraw

from common import POD, FPS, YUNET


def frames(mp4, f0, n):
    """exact frames f0 .. f0+n-1 (by frame number, not by seek time)"""
    w, h = 720, 1280
    t = 0.0
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', f'{t:.4f}', '-i', mp4, '-vf',
                        f"setpts=PTS-STARTPTS,select='gte(n\\,{f0 - round(t * FPS)})',scale=720:1280", '-frames:v', str(n),
                        '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
    a = np.frombuffer(r.stdout, np.uint8)
    k = len(a) // (w * h * 3)
    return a[:k * w * h * 3].reshape(k, h, w, 3)


def eye_ratio(img, fc):
    g = img.mean(2)
    d = max(1.0, math.hypot(fc[6] - fc[4], fc[7] - fc[5]))
    vals = []
    for ex, ey in ((fc[4], fc[5]), (fc[6], fc[7])):
        hx, hy = max(2, int(0.22 * d)), max(2, int(0.12 * d))
        x0, x1, y0, y1 = int(ex - hx), int(ex + hx), int(ey - hy), int(ey + hy)
        cy = int(ey + 0.55 * d)
        if x0 < 0 or y0 < 0 or x1 >= g.shape[1] or cy + hy >= g.shape[0]: return np.nan, None
        skin = np.median(g[cy - hy:cy + hy, x0:x1])
        vals.append(float((g[y0:y1, x0:x1] < 0.5 * skin).mean()))
    ex, ey = (fc[4] + fc[6]) / 2, (fc[5] + fc[7]) / 2
    box = (int(ex - 1.0 * d), int(ey - 0.45 * d), int(ex + 1.0 * d), int(ey + 0.45 * d))
    return float(np.mean(vals)), box


def main():
    det = None
    for mp4 in sys.argv[1:]:
        det = None
        base = mp4[:-4]; name = os.path.basename(base)
        edl_p = base + '.edl.json'
        if not os.path.exists(edl_p): edl_p = os.path.join(os.path.dirname(os.path.dirname(mp4)), name + '.edl.json')
        edl = json.load(open(edl_p))
        shots = [s for s in edl['shots'] if s['kind'] in ('guest_cutaway', 'split')]
        data = []
        for s in shots:
            fr = frames(mp4, round(s['out_start'] * FPS), s['frames'])
            y0 = 640 if s['kind'] == 'split' else 0
            if det is None: det = cv2.FaceDetectorYN.create(YUNET, '', (720, 640), 0.5)
            vals, boxes, imgs = [], [], []
            for f in fr:
                reg = f[y0:y0 + 640] if s['kind'] == 'split' else f
                det.setInputSize((reg.shape[1], reg.shape[0]))
                _, faces = det.detect(reg)
                if faces is None or not len(faces):
                    vals.append(np.nan); boxes.append(None); imgs.append(reg); continue
                fc = max(faces, key=lambda z: z[-1])
                v, b = eye_ratio(reg, fc)
                vals.append(v); boxes.append(b); imgs.append(reg)
            data.append((s, np.array(vals), boxes, imgs))
        allv = np.concatenate([d[1] for d in data]) if data else np.array([])
        med = float(np.nanmedian(allv)) if len(allv) else 1
        tiles = []
        print(f'== {name}  median eye ratio {med:.3f}')
        for s, v, boxes, imgs in data:
            r = v / med
            shut = ~(r >= 0.6)
            runs, a = [], None
            for i, x in enumerate(list(shut) + [False]):
                if x and a is None: a = i
                if not x and a is not None: runs.append((a, i)); a = None
            t0 = s['out_start']
            head = ' '.join(f'{x:.2f}' for x in r[:3]); tail = ' '.join(f'{x:.2f}' for x in r[-3:])
            long = [(round(t0 + a / FPS, 2), round((b - a) / FPS, 2)) for a, b in runs if (b - a) / FPS > 0.3]
            edge = [(round(t0 + a / FPS, 2), round((b - a) / FPS, 2)) for a, b in runs if a < 3 or b > len(r) - 3]
            flag = 'FLAG' if long or edge else 'ok'
            print(f"  {s['kind']:15s} {t0:6.2f}-{s['out_end']:6.2f}  head [{head}] tail [{tail}]  long-shut {long}  edge-shut {edge}  {flag}")
            pick = [0, 1, 2] + [i for a, b in runs for i in range(a, b) if (b - a) / FPS > 0.3 or a < 3 or b > len(r) - 3] + [len(r) - 3, len(r) - 2, len(r) - 1]
            for i in sorted(set(i for i in pick if 0 <= i < len(r))):
                b = boxes[i]
                if b is None: continue
                c = imgs[i][max(0, b[1]):b[3], max(0, b[0]):b[2]]
                im = Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)).resize((240, 108))
                dr = ImageDraw.Draw(im)
                dr.text((3, 2), f"{t0 + i / FPS:.2f} r{r[i]:.2f}", fill=(255, 60, 60) if shut[i] else (255, 255, 0))
                tiles.append(im)
        if tiles:
            per = 8; rows = (len(tiles) + per - 1) // per
            sheet = Image.new('RGB', (per * 242, rows * 110), (20, 20, 20))
            for k, t in enumerate(tiles): sheet.paste(t, ((k % per) * 242, (k // per) * 110))
            sheet.save(base + '_eyes.jpg', quality=85)
            print('  sheet', base + '_eyes.jpg')


if __name__ == '__main__':
    main()
