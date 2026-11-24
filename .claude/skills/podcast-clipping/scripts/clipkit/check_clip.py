#!/usr/bin/env python3
"""Measure a rendered clip: loudness, leftover silences, clicks at cuts, words heard vs expected, picture/sound sync.
Library for render_v2.py and scripts/check.py."""
import json, subprocess, sys, os, re, difflib
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import POD, FPS, SR, load_manifest, proxy, read_wav, band_energy_db, asr_words, norm_word, mic_roles
from scipy.signal import butter, sosfiltfilt


def out_audio(mp4):
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', mp4, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'], capture_output=True)
    return np.frombuffer(r.stdout, np.float32).astype(np.float64)


def loudness(mp4):
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', mp4, '-map', '0:a', '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True)
    t = r.stderr[r.stderr.rfind('Summary'):]
    return float(re.search(r'I:\s+(-?[\d.]+) LUFS', t).group(1)), float(re.search(r'Peak:\s+(-?[\d.]+) dBFS', t).group(1))


def silences(x, edl):
    E = band_energy_db(x)
    ref = np.percentile(E, 95)
    sil = E < ref - 30
    d = np.diff(np.concatenate([[0], sil.astype(int), [0]]))
    rs = [(a, b) for a, b in zip(np.where(d == 1)[0], np.where(d == -1)[0])]
    durs = [(b - a) * 0.01 for a, b in rs if a > 0 and b < len(E)]   # interior only
    head = rs[0][1] * 0.01 if rs and rs[0][0] == 0 else 0.0
    tail = (len(E) - rs[-1][0]) * 0.01 if rs and rs[-1][1] == len(E) else 0.0
    return {'max_internal_silence_s': round(max(durs), 3) if durs else 0, 'internal_silences_over_0.2s': int(sum(v > 0.2 for v in durs)),
            'silence_at_head_s': round(head, 3), 'silence_at_tail_s': round(tail, 3),
            'longest_5': sorted([round(v, 2) for v in durs])[-5:]}


def clicks(x, edl):
    """Peak high-frequency jump within +-8 ms of each cut, relative to the 90th pct of the surrounding 120 ms."""
    hp = sosfiltfilt(butter(2, 3000, 'highpass', fs=SR, output='sos'), x)
    res = []
    for p in edl['pieces'][1:]:
        i = int(round(p['out_start'] * SR))
        w = np.abs(hp[i - int(0.008 * SR):i + int(0.008 * SR)])
        ctx = np.abs(hp[i - int(0.06 * SR):i + int(0.06 * SR)])
        res.append(float(w.max() / (np.percentile(ctx, 90) + 1e-9)))
    # same statistic at random non-cut points, for scale
    rng = np.random.default_rng(0); base = []
    for i in rng.integers(int(0.1 * SR), len(x) - int(0.1 * SR), 40):
        w = np.abs(hp[i - int(0.004 * SR):i + int(0.004 * SR)]); ctx = np.abs(hp[i - int(0.06 * SR):i + int(0.06 * SR)])
        base.append(float(w.max() / (np.percentile(ctx, 90) + 1e-9)))
    worst = edl['pieces'][1 + int(np.argmax(res))]['out_start'] if res else None
    return {'worst_cut_at_s': worst, 'cut_peak_ratio_max': round(max(res), 2) if res else None, 'cut_peak_ratio_median': round(float(np.median(res)), 2) if res else None,
            'random_point_ratio_p90': round(float(np.percentile(base, 90)), 2)}


def words_check(x, edl):
    heard = [norm_word(w) for w, s0, e0 in asr_words(x)]   # whole clip at once (<= ~60 s)
    exp = [norm_word(w['w']) for w in edl['words']]
    sm = difflib.SequenceMatcher(a=exp, b=heard, autojunk=False)
    ops = [(t, ' '.join(exp[i1:i2]), ' '.join(heard[j1:j2])) for t, i1, i2, j1, j2 in sm.get_opcodes() if t != 'equal']
    # expected words the recogniser did not hear, and how close each sits to a cut (a clipped word would sit on one)
    cuts = [p['out_start'] for p in edl['pieces']] + [edl['duration_s']]
    near = []
    for t, i1, i2, j1, j2 in sm.get_opcodes():
        if t in ('delete', 'replace'):
            for w in edl['words'][i1:i2]:
                dc = min(min(abs(w['start'] - c), abs(w['end'] - c)) for c in cuts)
                near.append({'word': w['w'], 'who': w['who'], 'out_t': w['start'], 'dist_to_cut_s': round(dc, 2)})
    at_cut = [n for n in near if n['dist_to_cut_s'] < 0.12]
    return {'unheard_words_near_cuts': at_cut, 'unheard_words_total': len(near), 'expected_words': len(exp), 'heard_words': len(heard), 'match_ratio': round(sm.ratio(), 3), 'differences': ops[:20],
            'first_expected': exp[:3], 'first_heard': heard[:3], 'last_expected': exp[-3:], 'last_heard': heard[-3:]}


def gcc(a, b, maxlag):
    # taper both: filter edge transients otherwise give a spurious zero-lag PHAT peak
    a = a * np.hanning(len(a)); b = b * np.hanning(len(b))
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    R = np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)); R /= np.abs(R) + 1e-9
    cc = np.fft.irfft(R, n); cc = np.concatenate([cc[-maxlag:], cc[:maxlag + 1]])
    k = int(np.argmax(cc)); y0, y1, y2 = cc[k - 1], cc[k], cc[k + 1]
    return (k - maxlag + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12))


def sync_check(edl, man):
    """For each shot: (1) camera scratch audio at the frames used vs the studio mics at the master time used
    -> how far picture is from sound (minus the camera's acoustic path); (2) the rendered frame matches the proxy frame."""
    roles = edl['mic_roles']; out = []
    sos = butter(4, [150, 4000], 'bandpass', fs=16000, output='sos')
    for s in edl['shots']:
        dur = min((s['parts'][0]['frames'] / FPS) if s.get('parts') else s['out_end'] - s['out_start'], 6.0)
        if dur < 1.0: continue
        for src in s['sources']:
            cam = src['camera']
            tc = src['src_cam_time']; tm = s['master_start']
            r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.4f' % (tc - 0.5), '-i', proxy(man, cam), '-t', '%.3f' % (dur + 1),
                                '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'], capture_output=True)
            ca = np.frombuffer(r.stdout, np.float32).astype(np.float64)
            sm = man['cameras'][cam].get('subject_mic')
            m = read_wav(sm, tm - 0.5, tm + dur + 0.5) if sm else read_wav(roles['host'], tm - 0.5, tm + dur + 0.5) + read_wav(roles['guest'], tm - 0.5, tm + dur + 0.5)
            m = m[::3]
            n = min(len(ca), len(m))
            if n < 16000: continue
            lag = gcc(sosfiltfilt(sos, ca[:n]), sosfiltfilt(sos, m[:n]), 1600) / 16000   # camera audio later than master by lag
            ac = man['cameras'][cam]['sync']['acoustic_delay_correction_ms'] / 1000
            out.append({'shot': s['index'], 'camera': cam, 'master_t': round(tm, 2),
                        'mapping_error_ms': round((lag - ac) * 1000, 1)})
    return out


