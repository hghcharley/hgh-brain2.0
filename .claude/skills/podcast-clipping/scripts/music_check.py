#!/usr/bin/env python3
"""Stage (f): how loud is the music under the voice? Compares a music export with the same clip without music.

  python scripts/music_check.py --music music/10.mp4 --voice out/closeup/10_my-best-clip.mp4
  python scripts/music_check.py --music m.mp4 --voice v.mp4 --highpass 250 --seconds 14 --json out.json

How: both files are decoded to 16 kHz mono; the voice-only clip is aligned to the music export (lag search) and scaled
(least-squares gain), then subtracted. What is left is the music (plus codec noise). Reported:
  * speech level: RMS of the voice clip over its louder half of 0.1 s frames (dB)
  * music median / p90: per-0.1 s RMS of the residual (dB); voice minus music median = how far the music sits under
  * per-second music level from the start (does the music come in too hot, or fade in?) and the last 3 seconds
--highpass 250 measures only what a phone speaker plays (cuts the bass). No network, no music files are written.
Works on any two files of the same cut (the music export must be the same edit, same start, maybe re-encoded).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot
boot(need_work=False, need=('numpy',))
import argparse, json, subprocess
import numpy as np


def dec(p, hp=None):
    af = ['-af', f'highpass=f={hp}'] if hp else []
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', p, '-ac', '1', '-ar', '16000', *af, '-f', 'f32le', '-'], capture_output=True)
    if r.returncode: raise SystemExit(r.stderr.decode()[-500:])
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)


def db(x): return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def measure(music, voice, hp=None, max_lag=1600, seconds=14):
    a, b = dec(music, hp), dec(voice, hp)
    w = 16000 * 6; s0 = min(16000 * 3, max(0, len(b) - w - max_lag - 1)); seg = b[s0:s0 + w]
    best = (1e18, 0, 1.0)
    for lag in range(-max_lag, max_lag + 1):
        s = s0 + lag
        if s < 0: continue
        x = a[s:s + w]
        if len(x) < w: continue
        g = np.dot(x, seg) / (np.dot(seg, seg) + 1e-12); e = np.mean((x - g * seg) ** 2)
        if e < best[0]: best = (e, lag, g)
    _, lag, g = best
    x, y = (a[lag:], b) if lag >= 0 else (a, b[-lag:])
    n = min(len(x), len(y)); res = x[:n] - g * y[:n]
    fr = y[:n - (n % 1600)].reshape(-1, 1600); e = np.sqrt((fr ** 2).mean(1)); act = e > np.median(e)
    sp = 20 * np.log10(np.sqrt((fr[act] ** 2).mean()) + 1e-12)
    rf = res[:n - (n % 1600)].reshape(-1, 1600); rdb = 20 * np.log10(np.sqrt((rf ** 2).mean(1)) + 1e-12)
    sec = res[:n - (n % 16000)].reshape(-1, 16000); ps = 20 * np.log10(np.sqrt((sec ** 2).mean(1)) + 1e-9)
    return {'music': music, 'voice': voice, 'highpass_hz': hp, 'lag_samples_16k': int(lag), 'voice_gain_in_music_file': round(float(g), 3),
            'speech_db': round(float(sp), 1), 'music_median_db': round(float(np.median(rdb)), 1), 'music_p90_db': round(float(np.percentile(rdb, 90)), 1),
            'voice_minus_music_db': round(float(sp - np.median(rdb)), 1),
            'music_per_second_start_db': [round(float(v), 1) for v in ps[:seconds]],
            'music_last_3s_db': [round(float(v), 1) for v in ps[-3:]],
            'music_per_second_median_db': round(float(np.median(ps)), 1), 'duration_s': round(len(a) / 16000, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--music', required=True, help='export with music'); ap.add_argument('--voice', required=True, help='same cut without music')
    ap.add_argument('--highpass', type=float, help='Hz, e.g. 250 = what a phone speaker plays')
    ap.add_argument('--seconds', type=int, default=14, help='per-second values printed from the start')
    ap.add_argument('--max-lag', type=int, default=1600, help='lag search, samples at 16 kHz (default 0.1 s)')
    ap.add_argument('--json', help='also write the result here')
    a = ap.parse_args()
    r = measure(a.music, a.voice, a.highpass, a.max_lag, a.seconds)
    print(f"voice {r['speech_db']} dB, music median {r['music_median_db']} dB (p90 {r['music_p90_db']}): music sits "
          f"{r['voice_minus_music_db']} dB under the voice; lag {r['lag_samples_16k']} samples, voice gain {r['voice_gain_in_music_file']}")
    print('music per second from the start:', ' '.join(f'{v:.0f}' for v in r['music_per_second_start_db']), '| last 3 s:',
          ' '.join(f'{v:.0f}' for v in r['music_last_3s_db']))
    if a.json: json.dump(r, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
