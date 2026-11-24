#!/usr/bin/env python3
"""Independent picture-vs-sound check using the manifest mapping:
(a) camera scratch audio at the mapped frames vs the studio mics (GCC-PHAT), and
(b) mouth motion in the close-ups vs the subject's mic envelope (lag that maximises correlation, in frames).
At the start, middle and end of the hour for all three cameras."""
import sys, json, subprocess, numpy as np, cv2
from common import *
from scipy.signal import butter, sosfiltfilt
def gcc(a, b, maxlag):
    # taper both: filter edge transients otherwise give a spurious zero-lag PHAT peak
    a = a * np.hanning(len(a)); b = b * np.hanning(len(b))
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    R = np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)); R /= np.abs(R) + 1e-9
    cc = np.fft.irfft(R, n); cc = np.concatenate([cc[-maxlag:], cc[:maxlag + 1]])
    k = int(np.argmax(cc)); y0, y1, y2 = cc[k - 1], cc[k], cc[k + 1]
    return (k - maxlag + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12))
def run(times=None):
  man = load_manifest(); roles = mic_roles(man)
  det = cv2.FaceDetectorYN.create(YUNET, '', (960, 540), 0.6)
  dur_all = man.get('duration_s', 3000)
  times = times or [round(dur_all * f, 1) for f in (0.06, 0.5, 0.94)]
  res = []
  sos = butter(4, [150, 4000], 'bandpass', fs=16000, output='sos')
  for t in times:
    for cam in man['cameras']:
        k, err = cam_frame(man, cam, t)
        dur = 40.0
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.5f' % (k / FPS), '-i', proxy(man, cam), '-t', str(dur), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'], capture_output=True)
        ca = np.frombuffer(r.stdout, np.float32).astype(float)
        tm = master_time(man, cam, k / FPS)
        sm = man['cameras'][cam].get('subject_mic')
        mm = (read_wav(sm, tm, tm + dur) if sm else read_wav(roles['host'], tm, tm + dur) + read_wav(roles['guest'], tm, tm + dur))[::3]
        n = min(len(ca), len(mm))
        lag = gcc(sosfiltfilt(sos, ca[:n]), sosfiltfilt(sos, mm[:n]), 1600) / 16000
        ac = man['cameras'][cam]['sync']['acoustic_delay_correction_ms'] / 1000
        row = {'t': t, 'camera': cam, 'audio_method_mapping_error_ms': round((lag - ac) * 1000, 1)}
        if man['cameras'][cam]['role'] in ('host_close', 'guest_close'):
            person = man['cameras'][cam]['role'][:-6]
            p = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.5f' % ((k - 0.5) / FPS), '-i', proxy(man, cam), '-t', str(dur), '-vf', 'scale=960:540', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], stdout=subprocess.PIPE)
            mot = []; prev = None; box = None; i = 0
            while True:
                b = p.stdout.read(960 * 540 * 3)
                if len(b) < 960 * 540 * 3: break
                f = np.frombuffer(b, np.uint8).reshape(540, 960, 3)
                if i % 12 == 0:
                    _, fa = det.detect(f)
                    if fa is not None and len(fa): box = fa[np.argmax(fa[:, 2] * fa[:, 3])]
                i += 1
                if box is None: mot.append(0); continue
                w = box[2]; mx = (box[10] + box[12]) / 2; my = (box[11] + box[13]) / 2
                g = cv2.cvtColor(f[int(my - 0.12 * w):int(my + 0.3 * w), int(mx - 0.35 * w):int(mx + 0.35 * w)], cv2.COLOR_BGR2GRAY).astype(np.float32)
                g = cv2.resize(g, (40, 24))
                mot.append(float(np.abs(g - prev).mean()) if prev is not None else 0); prev = g
            mot = np.array(mot)
            x = read_wav(roles[person], tm, tm + dur)
            hop = SR / FPS
            env = np.array([np.sqrt((x[int(j * hop):int((j + 1) * hop)] ** 2).mean() + 1e-12) for j in range(len(mot))])
            ed = np.abs(np.diff(np.log(env), prepend=np.log(env[0])))      # sound changes <-> mouth movement
            def z(v): v = v - v.mean(); return v / (v.std() + 1e-9)
            mz, ez = z(mot), z(ed)
            lags = range(-4, 5)
            c = [float(np.mean(mz[max(0, L):len(mz) + min(0, L)] * ez[max(0, -L):len(ez) - max(0, L)])) for L in lags]
            kk = int(np.argmax(c)); d = 0
            if 0 < kk < len(c) - 1: d = 0.5 * (c[kk - 1] - c[kk + 1]) / (c[kk - 1] - 2 * c[kk] + c[kk + 1])
            row['mouth_motion_lag_frames'] = round(list(lags)[kk] + d, 2)   # >0: picture motion trails the sound
            row['mouth_corr_peak'] = round(max(c), 3)
        res.append(row); print(row, flush=True)
  json.dump(res, open(f'{POD}/work/lipsync_check.json', 'w'), indent=1)
  return res
