#!/usr/bin/env python3
"""Stage (a): ingest the footage, sync every camera to the master audio clock, and write manifest.json.

  python scripts/ingest.py --work /path/work                 # reads /path/work/shoot.json
  python scripts/ingest.py --work W --only sync              # just measure and print the camera offsets
  python scripts/ingest.py --work W --check-sources          # also check proxy frame k == source frame k

Steps (each writes into W/work/ and is skipped when its output exists; --redo forces them):
  1. audio/   one 48 kHz mono WAV per mic role (a link when the file already is one; otherwise ffmpeg extracts it,
              e.g. from a camera file for "audio inside the video")
     proxies/ a 1920x1080 proxy per camera when shoot.json gives none (made from the source with ffmpeg)
  2. a16/     16 kHz mono copies of every mic and every camera's own (scratch) audio; 10 Hz level envelopes
  3. sync     coarse lag from whole-file level envelopes, then GCC-PHAT on 20 s windows across the recording against
              whichever mic is dominant there; robust linear fit -> offset_s and drift_ppm per camera
  4. faces    YuNet face detection every 30 s on each proxy (synced), face statistics per camera / wide side
  5. roles    wide vs close-up (faces per frame) and which person each close-up shows (mouth motion while each mic
              talks alone), unless shoot.json sets "role"
  6. manifest looks (crop boxes in 3840x2160 units), colour gains, speech levels, mic roles -> manifest.json
The master clock is the mic audio timeline: every time in every file is seconds on it.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot, add_work_arg
boot()
import argparse, json, math, shutil, subprocess, datetime
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt, fftconvolve, resample_poly

WORK = os.environ.get('CLIPKIT_WORK', '')
WK = f'{WORK}/work'
SR16 = 16000
LOG = lambda *a: print(*a, flush=True)


# ------------------------------------------------------------------ small helpers
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(' '.join(cmd[:8]) + ' ...\n' + r.stderr[-1500:])
    return r


def ffprobe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels:format=duration',
                        '-of', 'json', path], capture_output=True, text=True)
    return json.loads(r.stdout or '{}')


def even(v): return int(round(v / 2) * 2)


def resolve(p):
    """A path in shoot.json is relative to the work dir; a '.url' file holds a URL."""
    if p is None: return None
    if p.startswith(('http://', 'https://')): return p
    return p if os.path.isabs(p) else os.path.abspath(os.path.join(WORK, p))


def read_url(p):
    return open(p).read().strip() if p and p.endswith('.url') and os.path.exists(p) else p


# ------------------------------------------------------------------ 1. audio + proxies
def prepare_audio(cfg, redo):
    os.makedirs(f'{WORK}/audio', exist_ok=True)
    mics = cfg['mics']
    srcs = {}
    for role in ('host', 'guest'):
        m = mics[role] if isinstance(mics[role], dict) else {'file': mics[role]}
        key = (resolve(m['file']), m.get('stream'), m.get('channel'))
        srcs[role] = (key, m)
    roles, made = {}, {}
    for role, (key, m) in srcs.items():
        if key in made:                    # host and guest share one track: one mic id for both
            roles[role] = made[key]; continue
        mid = 'mic_shared' if srcs['host'][0] == srcs['guest'][0] else f'mic_{role}'
        dst = f'{WORK}/audio/{mid}.wav'
        made[key] = mid; roles[role] = mid
        if os.path.exists(dst) and not redo: continue
        src, stream, ch = key
        pr = ffprobe(src)
        a = [s for s in pr.get('streams', []) if s['codec_type'] == 'audio']
        if not a: raise SystemExit(f'{src}: no audio stream')
        is_wav48mono = src.lower().endswith('.wav') and a[0].get('sample_rate') == '48000' and a[0].get('channels') == 1 \
            and stream is None and ch is None
        if os.path.lexists(dst): os.remove(dst)
        if is_wav48mono:
            os.symlink(src, dst)
        else:
            amap = ['-map', f'0:a:{stream or 0}']
            af = ['-af', f'pan=mono|c0=c{ch}'] if ch is not None else ['-ac', '1']
            run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, *amap, *af, '-ar', '48000', '-c:a', 'pcm_s24le', dst])
        LOG(f'  audio {mid}: {"linked" if is_wav48mono else "extracted"} from {os.path.basename(src)}')
    return roles


def prepare_proxies(cfg, redo):
    cams = {}
    for cam, c in cfg['cameras'].items():
        src = resolve(c.get('source')); px = resolve(c.get('proxy'))
        srcu = read_url(src)
        if not px:
            if not src or srcu.startswith('http'):
                raise SystemExit(f'{cam}: give a local "proxy" (1920x1080) or a local "source" file')
            pr = ffprobe(srcu); v = [s for s in pr['streams'] if s['codec_type'] == 'video'][0]
            if (v['width'], v['height']) == (1920, 1080) and v['codec_name'] in ('h264',):
                px = srcu
            else:
                os.makedirs(f'{WORK}/proxies', exist_ok=True)
                px = f'{WORK}/proxies/{cam}.mp4'
                if redo or not os.path.exists(px):
                    LOG(f'  making 1920x1080 proxy for {cam} (this takes a while for long files)')
                    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', srcu, '-vf', 'scale=1920:1080:flags=lanczos',
                         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-g', '48', '-pix_fmt', 'yuv420p',
                         '-c:a', 'aac', '-b:a', '128k', px])
        pr = ffprobe(px); v = [s for s in pr['streams'] if s['codec_type'] == 'video'][0]
        if (v['width'], v['height']) != (1920, 1080):
            raise SystemExit(f'{cam}: proxy must be 1920x1080 (16:9), got {v["width"]}x{v["height"]}')
        ss = None
        if srcu:
            ps = ffprobe(srcu)
            vs = [s for s in ps.get('streams', []) if s['codec_type'] == 'video']
            if vs: ss = [int(vs[0]['width']), int(vs[0]['height'])]
            if ss and abs(ss[0] / ss[1] - 16 / 9) > 0.01:
                raise SystemExit(f'{cam}: source is {ss[0]}x{ss[1]}; only 16:9 cameras are supported')
        cams[cam] = {'proxy': px, 'source': src or px, 'source_size': ss or [1920, 1080], 'fps': v['r_frame_rate'],
                     'has_audio': any(s['codec_type'] == 'audio' for s in pr['streams'])}
    fpss = {c['fps'] for c in cams.values()}
    if len(fpss) != 1:
        raise SystemExit(f'cameras have different frame rates {fpss}: conform them to one rate first')
    return cams


# ------------------------------------------------------------------ 2. 16 kHz copies + envelopes
def a16(name, src, redo, stream_args=()):
    os.makedirs(f'{WK}/a16', exist_ok=True)
    dst = f'{WK}/a16/{name}.wav'
    if redo or not os.path.exists(dst):
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, *stream_args, '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', dst])
    return dst


def load16(name):
    return sf.read(f'{WK}/a16/{name}.wav', dtype='float32')[0]


def env10(x):
    """10 Hz dB level envelope (levels.py)."""
    m = len(x) // 1600 * 1600
    return 20 * np.log10(np.sqrt((x[:m].reshape(-1, 1600) ** 2).mean(1) + 1e-12))


# ------------------------------------------------------------------ 3. sync (sync.py)
def env(x, sr=SR16, out=100):
    sos = butter(4, [300, 3000], 'bandpass', fs=sr, output='sos')
    y = np.abs(sosfiltfilt(sos, x))
    y = resample_poly(y, 1, sr // out)
    y = np.log(np.maximum(y, 0) + 1e-4); y -= y.mean(); return y


def xcorr_lag(a, b):
    c = fftconvolve(a, b[::-1], mode='full')
    k = np.argmax(c); return k - (len(b) - 1), c


def gcc2(a, b, maxlag, beta=1.0):
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    A = np.fft.rfft(a, n); B = np.fft.rfft(b, n)
    R = A * np.conj(B); R /= (np.abs(R) + 1e-9) ** beta
    cc = np.fft.irfft(R, n); cc = np.concatenate([cc[-maxlag:], cc[:maxlag + 1]])
    k = int(np.argmax(cc)); y0, y1, y2 = cc[k - 1], cc[k], cc[k + 1]
    d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
    excl = cc.copy(); excl[max(0, k - 48):k + 49] = 0
    return (k - maxlag + d) / SR16, float(cc[k] / excl.max())


def robust_fit(t, o, mic):
    """offset = a_mic + b*t, iteratively dropping outliers (>2.5 ms)."""
    keep = np.ones(len(t), bool); mics = sorted(set(mic))
    for it in range(6):
        cols = [np.ones(len(t)) * (np.array(mic) == m) for m in mics] + [t]
        X = np.stack(cols, 1)
        p, *_ = np.linalg.lstsq(X[keep], o[keep], rcond=None)
        r = o - X @ p
        s = max(1.4826 * np.median(np.abs(r[keep])), 0.0004)
        keep = np.abs(r) < max(3 * s, 0.0015)
    return dict(zip(mics, p[:-1])), p[-1], r, keep


def measure_sync(cams, mic_ids, envs, npts=40, win=20):
    """Per camera: coarse lag from level envelopes against the sum of the mics, then GCC-PHAT on `npts` windows against
    the mic that is dominant in each window (per-talker intercepts: the two people sit at different distances)."""
    refs = {m: load16(m) for m in mic_ids}
    T = min(len(v) for v in refs.values()) / SR16
    mix = sum(refs.values())
    er = env(mix)
    sos = butter(4, [150, 4000], 'bandpass', fs=SR16, output='sos')
    res = {}
    for cam in cams:
        x = load16(cam)
        L, _ = xcorr_lag(env(x), er); coarse = L / 100
        pts = []
        for t0 in np.linspace(20, T - win - 20, npts):
            i, j = int(t0 * 10), int((t0 + win) * 10)
            if len(mic_ids) == 2:
                e2, e3 = envs[mic_ids[0]], envs[mic_ids[1]]
                d = e2[i:j] - e3[i:j]
                f2 = ((d > 8) & (e2[i:j] > -40)).mean(); f3 = ((d < -8) & (e3[i:j] > -40)).mean()
                mic = mic_ids[0] if f2 > f3 else mic_ids[1]
                if max(f2, f3) < 0.3: continue
            else:
                mic = mic_ids[0]
                if (envs[mic][i:j] > -40).mean() < 0.3: continue
            ref = refs[mic]; m = SR16 // 2
            seg = ref[int(t0 * SR16):int((t0 + win) * SR16)]
            i0 = int(round((t0 + coarse) * SR16)) - m
            if i0 < 0 or i0 + len(seg) + 2 * m > len(x): continue
            cs = x[i0:i0 + len(seg) + 2 * m]
            a = sosfiltfilt(sos, cs); b = sosfiltfilt(sos, np.pad(seg, (m, m)))
            lag, q = gcc2(a, b, int(0.3 * SR16))
            pts.append((t0 + win / 2, (i0 + m - int(t0 * SR16)) / SR16 + lag, mic, q))
        if len(pts) < 6:
            raise SystemExit(f'{cam}: only {len(pts)} usable sync windows (no camera audio?). Set "offset_s" for it in shoot.json')
        t = np.array([p[0] for p in pts]); o = np.array([p[1] for p in pts]); mic = [p[2] for p in pts]
        A, b, r, keep = robust_fit(t, o, mic)
        LOG(f'  {cam}: coarse {coarse:.2f} s, intercepts {({k: round(v, 5) for k, v in A.items()})}, drift {b * 1e6:.2f} ppm, '
            f'kept {keep.sum()}/{len(keep)}, resid rms {np.sqrt((r[keep] ** 2).mean()) * 1e3:.2f} ms max {np.abs(r[keep]).max() * 1e3:.2f} ms')
        res[cam] = dict(coarse=coarse, intercepts=A, drift=b,
                        points=[dict(t=float(a_), offset=float(c_), mic=d_, q=float(e_), resid_ms=float(rr * 1e3), kept=bool(k_))
                                for (a_, c_, d_, e_), rr, k_ in zip(pts, r, keep)],
                        resid_rms_ms=float(np.sqrt((r[keep] ** 2).mean()) * 1e3), resid_max_ms=float(np.abs(r[keep]).max() * 1e3))
    return res


# ------------------------------------------------------------------ 4. faces (faces.py)
def detect_faces(cams, sync, fps, step=30.0, T=None):
    import cv2
    from common import YUNET
    det = cv2.FaceDetectorYN.create(YUNET, '', (1920, 1080), 0.5)
    out = {}
    for cam, c in cams.items():
        a, b = sync[cam]['offset_s'], sync[cam]['drift_ppm'] * 1e-6
        out[cam] = []
        for t in np.arange(5, T - 5, step):
            tc = a + t * (1 + b)
            r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % tc, '-i', c['proxy'], '-frames:v', '1',
                                '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
            if len(r.stdout) < 1920 * 1080 * 3: continue
            f = np.frombuffer(r.stdout, np.uint8).reshape(1080, 1920, 3)
            _, faces = det.detect(f)
            fl = [] if faces is None else [[round(float(v) * 2, 1) for v in fc[:14]] + [round(float(fc[14]), 3)] for fc in faces]  # 4K coords
            out[cam].append({'t': round(float(t), 2), 'faces': fl})
        LOG(f'  faces {cam}: {len(out[cam])} samples')
    return out


# ------------------------------------------------------------------ 5. which close-up shows which mic (mouth.py)
def mouth_motion(cam, proxy_path, sync_res, envs, mic_ids, T, fps):
    import cv2
    from common import YUNET
    W, H = 960, 540
    det = cv2.FaceDetectorYN.create(YUNET, '', (W, H), 0.6)
    c = sync_res[cam]; off = float(np.mean(list(c['intercepts'].values()))); dr = c['drift']
    res = []
    for tmaster in np.linspace(0.075 * T, min(0.95 * T, T - 100), 6):
        tcam = off + tmaster * (1 + dr)
        p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(tcam), '-i', proxy_path, '-t', '90', '-vf', f'scale={W}:{H}',
                              '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
        mot = []; prev = None; box = None; i = 0
        while True:
            bb = p.stdout.read(W * H * 3)
            if len(bb) < W * H * 3: break
            f = np.frombuffer(bb, np.uint8).reshape(H, W, 3)
            if i % 12 == 0 or box is None:
                _, faces = det.detect(f)
                if faces is not None and len(faces):
                    box = faces[np.argmax(faces[:, 2] * faces[:, 3])]
            i += 1
            if box is None: mot.append(np.nan); continue
            x, y, w, h = box[:4]; mx = (box[10] + box[12]) / 2; my = (box[11] + box[13]) / 2
            x0, x1 = int(mx - 0.35 * w), int(mx + 0.35 * w); y0, y1 = int(my - 0.15 * h), int(my + 0.3 * h)
            g = cv2.cvtColor(f[max(0, y0):y1, max(0, x0):x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
            if g.size == 0: mot.append(np.nan); continue
            g = cv2.resize(g, (48, 32))
            mot.append(np.abs(g - prev).mean() if prev is not None and prev.shape == g.shape else np.nan); prev = g
        mot = np.array(mot); n = len(mot)
        tm = (tcam + np.arange(n) / fps - off) / (1 + dr)
        e = {m: np.interp(tm * 10, np.arange(len(envs[m])), envs[m]) for m in mic_ids}
        ok = ~np.isnan(mot)
        r = {}
        m0, m1 = mic_ids
        s0 = ok & (e[m0] > -38) & (e[m0] - e[m1] > 10); s1 = ok & (e[m1] > -38) & (e[m1] - e[m0] > 10)
        r[f'mot_when_{m0}_solo'] = float(np.median(mot[s0])) if s0.sum() > 20 else None
        r[f'mot_when_{m1}_solo'] = float(np.median(mot[s1])) if s1.sum() > 20 else None
        res.append(r)
    v = {m: [x[f'mot_when_{m}_solo'] for x in res if x[f'mot_when_{m}_solo'] is not None] for m in mic_ids}
    med = {m: (float(np.median(v[m])) if v[m] else float('nan')) for m in mic_ids}
    LOG(f'  mouth motion {cam}: ' + ', '.join(f'{m} solo {med[m]:.2f}' for m in mic_ids))
    return med, len(res)


# ------------------------------------------------------------------ 6. manifest (build_manifest.py)
def face_stats(F, cam, wrange, pick=None):
    xs, eyes, ws = [], [], []
    for s in F[cam]:
        fs = [f for f in s['faces'] if wrange[0] < f[2] < wrange[1]]
        if pick == 'left': fs = [f for f in fs if f[0] < 1920]
        if pick == 'right': fs = [f for f in fs if f[0] >= 1920]
        if not fs: continue
        f = max(fs, key=lambda f: f[14])
        xs.append(f[0] + f[2] / 2); eyes.append((f[5] + f[7]) / 2); ws.append(f[2])
    if not xs:
        raise SystemExit(f'no faces found on {cam}{" " + pick if pick else ""} in range {wrange}: check face_w_filter_4k')
    xs, eyes, ws = map(np.array, (xs, eyes, ws))
    return {'cx_median': float(np.median(xs)), 'cx_p5_p95': [float(np.percentile(xs, 5)), float(np.percentile(xs, 95))],
            'eye_y_median': float(np.median(eyes)), 'eye_y_p5_p95': [float(np.percentile(eyes, 5)), float(np.percentile(eyes, 95))],
            'face_w_median': float(np.median(ws)), 'samples': int(len(xs))}


def auto_range(F, cam, wide):
    """Face-width filter (4K px) from the faces seen: close-ups = largest face per sample; wide = all confident faces."""
    ws = []
    for s in F[cam]:
        fs = [f for f in s['faces'] if f[14] > 0.8]
        if not fs: continue
        ws += [f[2] for f in fs] if wide else [max(fs, key=lambda f: f[2])[2]]
    if not ws: return [0, 1e9]
    m = float(np.median(ws))
    return [0.6 * m, 1.6 * m] if wide else [0.7 * m, 1.4 * m]


def box(cx, eye, w, h, face_x_frac, eye_frac, W=3840, H=2160):
    x = cx - face_x_frac * w; y = eye - eye_frac * h
    x = min(max(0, x), W - w); y = min(max(0, y), H - h)
    return [int(round(x / 2) * 2), int(round(y / 2) * 2), int(w), int(h)]


def build_looks(F, role_of, cfg, wranges):
    """Crop boxes for every framing. gaze: the person sitting frame-left in the wide looks frame-right (lead room)."""
    host_side = cfg.get('wide', {}).get('host_side', 'left')
    side_of = {'host': host_side, 'guest': 'right' if host_side == 'left' else 'left'}
    fx_of = lambda person: 0.42 if side_of[person] == 'left' else 0.58
    looks, stats = {}, {}
    for cam, role in role_of.items():
        if role not in ('host_close', 'guest_close'): continue
        person = role[:-6]
        st = face_stats(F, cam, wranges[cam]); stats[cam] = st
        fx = fx_of(person)
        L = {}
        L['single'] = dict(scale=1.0, w=1215, h=2160, face_x=fx, eye_y=1 / 3)
        L['single_punch'] = dict(scale=1.2, w=even(1215 / 1.2), h=1800, face_x=fx, eye_y=1 / 3)
        L['single_tight'] = dict(scale=1.38, w=even(1215 / 1.38), h=even(2160 / 1.38), face_x=fx, eye_y=0.36)
        # split halves (9:8): equalise face size (face = 30% of half width), eyes at 40% of the half height
        hw = even(st['face_w_median'] / 0.30); hh = even(hw * 8 / 9)
        L['half'] = dict(scale=1.0, w=hw, h=hh, face_x=fx, eye_y=0.40)
        L['half_punch'] = dict(scale=1.12, w=even(hw / 1.12), h=even(hh / 1.12), face_x=fx, eye_y=0.40)
        for k, v in L.items():
            v['aspect'] = '9:16' if k.startswith('single') else '9:8'
            v['box_default'] = box(st['cx_median'], st['eye_y_median'], v['w'], v['h'], v['face_x'], v['eye_y'])
            fs = [max([f for f in s['faces'] if wranges[cam][0] < f[2] < wranges[cam][1]], key=lambda f: f[14])
                  for s in F[cam] if any(wranges[cam][0] < f[2] < wranges[cam][1] for f in s['faces'])]
            bx, by, bw, bh = v['box_default']
            inside = [(bx + 0.05 * bw < f[0] and f[0] + f[2] < bx + 0.95 * bw and f[1] > by) for f in fs]
            v['fixed_box_keeps_face_inside_pct'] = round(100 * float(np.mean(inside)), 1) if inside else None
        if person == 'guest':
            # the guest's half of a split sits higher and wider so eyes and mouth clear the captions (y 1408-1472 on
            # the 1080x1920 frame = 448-512 px into the bottom half); v2 tuned this on the worked example
            g = cfg.get('looks', {}).get('guest_half')
            if not g:
                gw = min(3840, even(hw * 1800 / 1368)); gh = even(gw * 8 / 9)
                g = {'scale': round(hw / gw, 2), 'w': gw, 'h': gh, 'face_x': 0.56 if fx > 0.5 else 0.44, 'eye_y': 0.22, 'aspect': '9:8'}
            L['half'] = dict(g); L['half_punch'] = dict(g)
        looks[cam] = L
    wide = [c for c, r in role_of.items() if r == 'wide']
    if wide:
        cam = wide[0]
        close = {r[:-6]: c for c, r in role_of.items() if r in ('host_close', 'guest_close')}
        for person in ('host', 'guest'):
            side = side_of[person]
            try:
                st = face_stats(F, cam, wranges[cam], side)
            except SystemExit:
                continue
            stats[f'{cam}_{side}'] = st
            fx = fx_of(person)
            v = dict(scale=1.5, w=810, h=1440, face_x=fx, eye_y=0.30, aspect='9:16', subject_camera=close.get(person), person=person)
            v['box_default'] = box(st['cx_median'], st['eye_y_median'], v['w'], v['h'], fx, v['eye_y'])
            looks.setdefault(cam, {})[f'wide_single_{side}'] = v
            # a 1.2x tighter single from the wide: the punch-in when this person has no close-up camera
            p = dict(scale=1.8, w=676, h=1200, face_x=fx, eye_y=0.32, aspect='9:16', subject_camera=close.get(person), person=person)
            p['box_default'] = box(st['cx_median'], st['eye_y_median'], p['w'], p['h'], fx, p['eye_y'])
            looks[cam][f'wide_single_{side}_punch'] = p
    return looks, stats


def bandE(name):
    x, sr = sf.read(f'{WK}/a16/{name}.wav', dtype='float32')
    y = sosfiltfilt(butter(4, [200, 4000], 'bandpass', fs=sr, output='sos'), x)
    h = sr // 100; n = len(y) // h
    return 10 * np.log10((y[:n * h].reshape(n, h) ** 2).mean(1) + 1e-12)


def check_sources(cams, fps):
    """Proxy frame k must be source frame k (seek-then-decode), at 3%, 50% and 93% of each camera (verify_originals.py)."""
    out = {}
    def grab(src, k, n=1, pre=0):
        ss = (k - pre - 0.5) / fps
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.6f' % ss, '-i', src, '-frames:v', str(n), '-vf', 'scale=480:270',
                            '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True)
        return np.frombuffer(r.stdout, np.uint8).reshape(-1, 270, 480).astype(float)
    for cam, c in cams.items():
        src = read_url(c['source'])
        if src == c['proxy']: continue
        dur = float(ffprobe(c['proxy'])['format']['duration']); nb = int(dur * fps)
        res = []
        for k in (int(nb * 0.03), nb // 2, int(nb * 0.93)):
            o = grab(src, k, 8); pr = grab(c['proxy'], k, 14, 3)
            if len(o) < 8 or len(pr) < 14: res.append({'frame': k, 'error': 'short read'}); continue
            do = np.diff(o, axis=0); dp = np.diff(pr, axis=0)
            d = [float(np.abs(do - dp[j:j + 7]).mean() + np.abs(o - pr[j:j + 8]).mean()) for j in range(7)]
            res.append({'frame': k, 'best_offset_frames': int(np.argmin(d)) - 3, 'scores': [round(v, 2) for v in d]})
        out[cam] = res
        LOG(f'  source vs proxy {cam}: ' + ', '.join(f"frame {r['frame']}: offset {r.get('best_offset_frames', r.get('error'))}" for r in res))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_work_arg(ap)
    ap.add_argument('--config', help='shoot config (default WORK/shoot.json)')
    ap.add_argument('--only', choices=['sync'], help='stop after measuring sync (prints offsets, writes work/sync_result.json)')
    ap.add_argument('--redo', action='store_true', help='recompute every step even if its output exists')
    ap.add_argument('--face-step', type=float, default=30.0, help='seconds between face samples (default 30)')
    ap.add_argument('--check-sources', action='store_true', help='check proxy frame k == source frame k for every camera')
    a = ap.parse_args()
    cfg = json.load(open(a.config or f'{WORK}/shoot.json'))
    os.makedirs(WK, exist_ok=True)
    LOG('[1] audio and proxies')
    roles = prepare_audio(cfg, a.redo)
    cams = prepare_proxies(cfg, a.redo)
    from fractions import Fraction
    fps_str = next(iter(cams.values()))['fps']; fps = float(Fraction(fps_str))
    mic_ids = sorted(set(roles.values()))
    LOG('[2] 16 kHz copies and level envelopes')
    for m in mic_ids: a16(m, f'{WORK}/audio/{m}.wav', a.redo)
    for cam, c in cams.items():
        if c['has_audio']: a16(cam, c['proxy'], a.redo)
    envs = {m: env10(load16(m)) for m in mic_ids}
    T = len(load16(mic_ids[0])) / SR16
    LOG('[3] sync')
    sp = f'{WK}/sync_result.json'
    S = json.load(open(sp)) if os.path.exists(sp) and not a.redo else {}
    todo = [c for c in cams if c not in S and 'offset_s' not in cfg['cameras'][c]]
    if todo:
        S.update(measure_sync({c: cams[c] for c in todo if cams[c]['has_audio']}, mic_ids, envs))
        missing = [c for c in todo if not cams[c]['has_audio']]
        if missing: raise SystemExit(f'{missing}: no audio track to sync from. Set "offset_s" for them in shoot.json')
        json.dump(S, open(sp, 'w'), indent=1)
    ac = {c: float(cfg['cameras'][c].get('acoustic_delay_ms', 0.0)) for c in cams}
    sync = {}
    for c in cams:
        cc = cfg['cameras'][c]
        if 'offset_s' in cc:
            sync[c] = {'offset_s': float(cc['offset_s']), 'drift_ppm': float(cc.get('drift_ppm', 0.0)), 'measurement': 'set by hand in shoot.json',
                       'acoustic_delay_correction_ms': ac[c], 'formula': 'camera_time = offset_s + t_master * (1 + drift_ppm*1e-6)'}
    # provisional offsets (mean of talker intercepts) for the face pass; the subject mic is chosen in step 5
    prov = {c: {'offset_s': float(np.mean(list(S[c]['intercepts'].values()))) - ac[c] / 1000, 'drift_ppm': S[c]['drift'] * 1e6}
            for c in cams if c in S}
    prov.update({c: v for c, v in sync.items()})
    for c in cams: LOG(f'  {c}: offset {prov[c]["offset_s"]:.5f} s, drift {prov[c]["drift_ppm"]:.3f} ppm (provisional)')
    if a.only == 'sync': return
    LOG('[4] faces')
    fp = f'{WK}/faces.json'
    F = json.load(open(fp)) if os.path.exists(fp) and not a.redo else detect_faces(cams, prov, fps, a.face_step, T)
    json.dump(F, open(fp, 'w'))
    LOG('[5] camera roles')
    role_of, evidence, cam_mic = {}, {}, {}
    for c in cams:
        r = cfg['cameras'][c].get('role')
        if not r:
            n2 = np.median([sum(1 for f in s['faces'] if f[14] > 0.8) for s in F[c]] or [0])
            r = 'wide' if n2 >= 1.5 else 'close'
        role_of[c] = r
    closes = [c for c, r in role_of.items() if r in ('close', 'host_close', 'guest_close')]
    two_mics = len(mic_ids) == 2
    mp = f'{WK}/mouth.json'
    MO = json.load(open(mp)) if os.path.exists(mp) and not a.redo else {}
    for c in closes:
        if two_mics and c in S:
            if c not in MO:
                med, nwin = mouth_motion(c, cams[c]['proxy'], S, envs, mic_ids, T, fps)
                MO[c] = {'median': med, 'windows': nwin}
                json.dump(MO, open(mp, 'w'), indent=1)
            med = MO[c]['median']
            cam_mic[c] = max(med, key=lambda m: med[m] if med[m] == med[m] else -1)
            evidence[c] = {f'median_mouth_motion_when_{m}_solo': round(v, 2) for m, v in med.items()}
            evidence[c]['windows'] = MO[c]['windows']
        if role_of[c] == 'close':
            if not cam_mic.get(c):
                raise SystemExit(f'{c}: cannot tell whose close-up it is (one shared mic). Set "role" in shoot.json')
            role_of[c] = 'host_close' if cam_mic[c] == roles['host'] else 'guest_close'
        elif cam_mic.get(c) and two_mics:
            expect = roles[role_of[c][:-6]]
            if cam_mic[c] != expect:
                LOG(f'  ! {c}: shoot.json says {role_of[c]}, but its mouth moves with {cam_mic[c]}: check the roles')
        cam_mic.setdefault(c, roles[role_of[c][:-6]])
    rr = list(role_of.values())
    for r in ('wide', 'host_close', 'guest_close'):
        if rr.count(r) > 1: raise SystemExit(f'two cameras have role {r}: {role_of}')
    for c, r in role_of.items(): LOG(f'  {c}: {r}' + (f' (shows {cam_mic[c]})' if c in cam_mic else ''))
    LOG('[6] manifest')
    ff = cfg.get('face_w_filter_4k', {}); fa = cfg.get('face_w_accept_4k', {})
    wranges = {c: (ff.get('wide') if r == 'wide' else ff.get('close')) or auto_range(F, c, r == 'wide') for c, r in role_of.items()}
    looks, stats = build_looks(F, role_of, cfg, wranges)

    def sync_entry(c):
        if c in sync: return sync[c]
        r = S[c]; ints = r['intercepts']
        subj = cam_mic.get(c)
        a_audio = ints[subj] if subj in ints else float(np.mean(list(ints.values())))
        off = a_audio - ac[c] / 1000
        return {'offset_s': round(off, 5), 'drift_ppm': round(r['drift'] * 1e6, 3),
                'formula': 'camera_time = offset_s + t_master * (1 + drift_ppm*1e-6)',
                'audio_offset_s_by_talker': {k: round(v, 5) for k, v in ints.items()},
                'acoustic_delay_correction_ms': ac[c],
                'measurement': f'GCC-PHAT (150-4000 Hz) of camera audio vs the dominant mic, {len(r["points"])} x 20 s windows, robust linear fit',
                'points_used': sum(p['kept'] for p in r['points']), 'points_total': len(r['points']),
                'residual_rms_ms': round(r['resid_rms_ms'], 2), 'residual_max_ms': round(r['resid_max_ms'], 2),
                'offset_at_start_mid_end_s': [round(off + t * r['drift'], 5) for t in (0, T / 2, T)]}
    # speech level references (95th pct of 10 ms 200-4000 Hz band energy while that mic is clearly the active one)
    E = {m: bandE(m) for m in mic_ids}
    n = min(len(v) for v in E.values())
    E = {m: v[:n] for m, v in E.items()}
    if two_mics:
        m0, m1 = mic_ids
        speech_ref = {m0: float(np.percentile(E[m0][(E[m0] - E[m1]) > 10], 95)), m1: float(np.percentile(E[m1][(E[m1] - E[m0]) > 10], 95))}
    else:
        m0 = mic_ids[0]; speech_ref = {m0: float(np.percentile(E[m0][E[m0] > np.median(E[m0])], 95))}
    noise_floor = {m: float(np.percentile(E[m], 3)) for m in mic_ids}
    colour = cfg.get('colour', {})
    man = {
        'generated': datetime.datetime.utcnow().isoformat() + 'Z',
        'title': cfg.get('title', ''),
        'master_clock': 'audio/<mic>.wav timeline (seconds). All times in all files use it.',
        'fps': fps_str, 'duration_s': round(T, 3),
        'output': {'final': [1080, 1920], 'preview': [540, 960], 'colour': 'bt709 tv-range 8-bit yuv420p'},
        'people': cfg.get('people', {'host': {'name': 'host'}, 'guest': {'name': 'guest'}}),
        'wide': {'host_side': cfg.get('wide', {}).get('host_side', 'left')},
        'cameras': {},
        'mics': {
            'roles': roles,
            'files': {m: os.path.realpath(f'{WORK}/audio/{m}.wav') for m in mic_ids},
            'camera_for_mic': {m: c for c, m in cam_mic.items()},
            'how_camera_for_mic_was_decided': 'mouth-region motion in each close-up (YuNet landmarks, frame differences) while each mic was the only one active, 6 x 90 s windows',
            'evidence': evidence,
            'speech_ref_db_10ms_band200_4000': {k: round(v, 2) for k, v in speech_ref.items()},
            'noise_floor_db_10ms_band200_4000': {k: round(v, 2) for k, v in noise_floor.items()},
        },
        'looks_note': 'Crop boxes [x, y, w, h] in 3840x2160 units (proxies are 1920x1080 = half). box_default uses the '
                      'recording-median face; the engine re-centres each shot on a face detected in that shot.',
        'looks': looks, 'face_stats_4k': stats,
        'captions': cfg.get('captions', {}),
        'wide_opening': cfg.get('wide_opening', {}),
    }
    for c in cams:
        acc = fa.get('wide' if role_of[c] == 'wide' else 'close')
        if not acc:
            m = (stats.get(c) or stats.get(f'{c}_left') or stats.get(f'{c}_right') or {}).get('face_w_median')
            acc = [0.65 * m, 1.55 * m] if m else None
        man['cameras'][c] = {'role': role_of[c], 'proxy': cams[c]['proxy'], 'source': cams[c]['source'], 'source_size': cams[c]['source_size'],
                             'subject_mic': cam_mic.get(c), 'sync': sync_entry(c),
                             'colour': {'gains_rgb': colour.get(c, [1.0, 1.0, 1.0])},
                             'face_w_filter_4k': [round(v, 1) for v in wranges[c]],
                             'face_w_accept_4k': [round(v, 1) for v in acc] if acc else None}
    if a.check_sources:
        man['source_checks'] = check_sources(cams, fps)
    json.dump(man, open(f'{WORK}/manifest.json', 'w'), indent=1)
    LOG(json.dumps({c: (v['role'], v['sync']['offset_s'], v['sync']['drift_ppm'], v['sync'].get('residual_rms_ms')) for c, v in man['cameras'].items()}))
    for cam, L in looks.items():
        for k, v in L.items(): LOG(f'  look {cam} {k} {v.get("box_default")} inside {v.get("fixed_box_keeps_face_inside_pct")}')
    LOG(f'wrote {WORK}/manifest.json')


if __name__ == '__main__':
    main()
