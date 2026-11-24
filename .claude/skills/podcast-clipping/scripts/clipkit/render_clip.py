#!/usr/bin/env python3
"""v1 engine primitives (audio analysis, cleaning, edge checks, timeline, framing, shot rendering, mux).
The v2 renderer (render_v2.py) imports these. Not an entry point: use scripts/render.py.

Picture sources: USE_SOURCE False = the 1920x1080 proxies (fast, local), True = the full-quality source per camera
(file or URL, read with seek-then-decode per shot). Output size: preview=True 540x960, False 1080x1920.
"""
import argparse, json, math, os, shutil, subprocess, sys, time, re
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (POD, FPS, FPS_STR, SR, TMP, load_manifest, url, proxy, source_scale, wide_cam, wide_look, face_stats, YUNET, cam_time, master_time, cam_frame, mic_roles, person_cam,
                    read_wav, band_energy_db, silero_probs, load_words, load_speech_regions, asr_words, norm_word)
from scipy.signal import butter, sosfilt

HOP = 0.01
PAD_BEFORE, PAD_AFTER = 0.06, 0.05
GAP_MIN, GAP_KEEP = 0.25, 0.13
VAD_THR = 0.7
REL_DB = -30.0
MIN_SHOT = 1.2
WORK = f'{TMP}/render'
USE_SOURCE = False          # set by scripts/render.py --source original
LOG = print


def frames(sec):
    return int(round(sec * FPS))


# =============================================================== speech analysis
class Analysis:
    """Speech mask, per-mic energies and who-is-speaking for one master-time window."""

    def __init__(self, man, roles, t0, t1, regions, words):
        self.t0, self.t1 = t0, t1
        self.roles = roles
        self.x = {p: read_wav(roles[p], t0, t1) for p in ('host', 'guest')}
        n = int((t1 - t0) / HOP)
        self.E = {p: band_energy_db(self.x[p])[:n] for p in self.x}
        ref = man['mics']['speech_ref_db_10ms_band200_4000']
        n = min(len(v) for v in self.E.values()); self.n = n
        for p in self.E: self.E[p] = self.E[p][:n]
        # loud-speech reference: this passage's own level when it is louder than the hour's (95th pct while dominant)
        self.thr = {}
        for p in self.x:
            o = 'guest' if p == 'host' else 'host'
            dom = self.E[p][(self.E[p] - self.E[o]) > 10]
            loc = np.percentile(dom, 95) if len(dom) > 100 else -99
            self.thr[p] = max(ref[roles[p]], loc) + REL_DB
        # VAD: transcriber's regions when present, plus our own Silero >= 0.7 on each mic (union)
        vad = np.zeros(n, bool); self.prob = np.zeros(n)
        for p in self.x:
            pr = silero_probs(self.x[p])[:n]
            vad[:len(pr)] |= pr >= VAD_THR
            self.prob[:len(pr)] = np.maximum(self.prob[:len(pr)], pr)
        if regions:
            for (s, e, _) in regions:
                if e > t0 and s < t1:
                    vad[max(0, self.i(s)):min(n, self.i(e))] = True
        self.vad = vad
        self.eok = np.zeros(n, bool)
        for p in self.E: self.eok |= self.E[p] > self.thr[p]
        self.mask = self.refine(vad)
        # who is talking: own mic louder than the other (bleed is ~15-20 dB down)
        d = self.E['host'] - self.E['guest']
        self.host = self.mask & (d > 0) & (self.E['host'] > self.thr['host'])
        self.guest = self.mask & (d <= 0) & (self.E['guest'] > self.thr['guest'])
        self.words = [w for w in words if w['e'] > t0 and w['s'] < t1]

    def i(self, t):
        return int(round((t - self.t0) / HOP))

    def t(self, i):
        return self.t0 + i * HOP

    def refine(self, vad):
        """Move each VAD edge to where band energy crosses -30 dB rel. loud speech."""
        out = np.zeros_like(vad)
        n = len(vad)
        for a, b in runs(vad):
            a2 = a
            while a2 > 0 and self.eok[a2 - 1] and a - a2 < 25: a2 -= 1
            while a2 < b - 1 and not self.eok[a2] and a2 - a < 40: a2 += 1
            b2 = b
            while b2 < n and self.eok[b2] and b2 - b < 25: b2 += 1
            while b2 > a2 + 1 and not self.eok[b2 - 1] and b - b2 < 50: b2 -= 1
            out[a2:b2] = True
        # bridge tiny holes (< 50 ms)
        for a, b in runs(~out):
            if a > 0 and b < n and b - a < 5: out[a:b] = True
        # open real pauses that a generous region list bridged: >= 0.2 s below -30 dB rel with Silero < 0.5
        # (Silero and region lists hang over into pauses; band energy decides)
        for a, b in runs((~self.eok) & out):
            if b - a >= 22 and a > 0 and b < n: out[a:b] = False
        return out

    def energy_min(self, ta, tb):
        a, b = max(0, self.i(ta)), min(self.n, self.i(tb))
        tot = np.maximum(self.E['host'] - self.thr['host'], self.E['guest'] - self.thr['guest'])
        k = a + int(np.argmin(tot[a:b])) if b > a else a
        return self.t(k)


def runs(m):
    """[start, end) index pairs of True runs."""
    m = np.asarray(m, bool)
    if not len(m): return []
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


# =============================================================== audio cleaning
def clean_mix(an, ts, te, ctx=0.4):
    """Return the cleaned mono mix for master [ts, te): HPF, duck the non-speaker's mic, level-match, sum."""
    t0 = max(an.t0, ts - ctx); t1 = min(an.t1, te + ctx)
    if t0 > ts or t1 < te:   # outside the analysed window: extend with a fresh read (edge checks may look further out)
        an2 = Analysis.__new__(Analysis); an2.__dict__.update(an.__dict__)
        lo, hi = min(an.t0, ts - ctx), max(an.t1, te + ctx)
        an2.x = {p: read_wav(an.roles[p], lo, hi) for p in an.x}
        pad = lambda v, fill: np.concatenate([np.full(int(round((an.t0 - lo) / HOP)), fill), v, np.full(int(round((hi - an.t1) / HOP)) + 2, fill)])
        an2.E = {p: pad(an.E[p], -120.0) for p in an.E}
        an2.t0, an2.t1, an2.n = lo, hi, len(an2.E['host'])
        return clean_mix(an2, ts, te, ctx)
    a, b = int(round((t0 - an.t0) * SR)), int(round((t1 - an.t0) * SR))
    sos = butter(2, 80, 'highpass', fs=SR, output='sos')
    out = 0
    if an.roles['host'] == an.roles['guest']:      # one mixed track for both people: nothing to duck, use it as is
        x = sosfilt(sos, an.x['host'][a:b].astype(np.float64)) * an.mic_gain['host']
        i0 = int(round((ts - t0) * SR)); n = int(round((te - ts) * SR))
        return x[i0:i0 + n]
    for p in ('host', 'guest'):
        x = an.x[p][a:b].astype(np.float64)
        x = sosfilt(sos, x)
        other = 'guest' if p == 'host' else 'host'
        own = an.E[p] - an.E[other]
        active = (own > -6) & (an.E[p] > an.thr[p])    # this mic is carrying its own talker
        # the transcriber's words for this talker keep the mic open through overlaps (a quiet "No, no," under "Okay.")
        # and duck a mic with no words of its own while the other talker has words (a laugh over "Oh my god")
        wo = np.zeros(len(active), bool); wx = np.zeros(len(active), bool)
        for w in getattr(an, 'words', []):
            (wo if w['who'] == p else wx)[max(0, an.i(w['s'] - 0.03)):max(0, an.i(min(w['e'], w['s'] + 0.6) + 0.03))] = True
        active = (active & ~(wx & ~wo)) | wo
        # hold 200 ms after, open 40 ms early
        act = active.copy()
        for k in range(1, 21): act[:-k] |= active[k:] if k <= 4 else False
        for k in range(1, 21): act[k:] |= active[:-k]
        g = np.where(act, 1.0, 10 ** (-14 / 20))
        # smooth gain: 15 ms attack, 120 ms release (one-pole on 10 ms grid then per-sample interpolation)
        gs = np.empty_like(g); v = g[0]
        for k in range(len(g)):
            c = 0.5 if g[k] > v else 0.08
            v += c * (g[k] - v); gs[k] = v
        tg = an.t0 + (np.arange(len(gs)) + 0.5) * HOP
        tt = t0 + np.arange(len(x)) / SR
        x *= np.interp(tt, tg, gs)
        out = out + x * an.mic_gain[p]
    i0 = int(round((ts - t0) * SR)); n = int(round((te - ts) * SR))
    return out[i0:i0 + n]


def declick_edges(x):
    """A mouth click sitting in the first/last 25 ms of a piece would sound like an edit click: fade over it."""
    from scipy.signal import sosfiltfilt
    if len(x) < int(0.2 * SR): return x
    hp = np.abs(sosfiltfilt(butter(2, 3000, 'highpass', fs=SR, output='sos'), x))
    n25, n80 = int(0.025 * SR), int(0.08 * SR)
    x = x.copy()
    for side in (0, 1):
        seg = hp[:n80] if side == 0 else hp[-n80:][::-1]
        ref = np.percentile(seg, 90) + 1e-9
        k = int(np.argmax(seg[:n25]))
        if seg[k] > 4 * ref:
            m = min(k + int(0.004 * SR), n25)
            w = np.zeros(m + int(0.006 * SR)); w[m:] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, len(w) - m))
            if side == 0: x[:len(w)] *= w
            else: x[-len(w):] *= w[::-1]
    return x


def fade(x, ms=7):
    n = min(int(SR * ms / 1000), len(x) // 2)
    if n < 2: return x
    w = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
    x = x.copy(); x[:n] *= w; x[-n:] *= w[::-1]
    return x


# =============================================================== edit decision: pieces
def mic_gains(man, roles):
    """Level-match the two voices to the louder one's speech reference."""
    ref = man['mics']['speech_ref_db_10ms_band200_4000']
    r = {p: ref[roles[p]] for p in ('host', 'guest')}
    top = max(r.values())
    return {p: 10 ** ((top - r[p]) / 20) * 0.9 for p in r}


def same_word(a, b, side):
    if not a or not b: return False
    if a == b: return True
    if min(len(a), len(b)) >= 2:
        return b.endswith(a) or a.endswith(b) if side == 'end' else (b.startswith(a) or a.startswith(b))
    return False


def verify_edges(man, pieces, analyses, words, log, first_line=None):
    """ASR on a 1.5 s window at each OUTER clip edge (and each segment edge); step out a frame at a time until the
    first/last word is recognised whole."""
    def win_audio(an, ts, te):
        return fade(clean_mix(an, ts, te, ctx=0.2), 3)
    report = []
    for p in pieces:
        an = analyses[p['an']]
        for side in ('start', 'end'):
            if side == 'start' and not p['first_in_seg']: continue
            if side == 'end' and not p['last_in_seg']: continue
            # expected word: transcriber's words when present, else first_line, else a wide-context recognition
            exp = None
            seg_words = [w for w in words if an.t0 < w['s'] < an.t1]
            if side == 'start':
                if p.get('exp_first'):
                    exp = p['exp_first']
                elif p['seg'] == 0 and first_line:
                    exp = norm_word(first_line.split()[0])
                else:
                    ref = asr_words(clean_mix(an, p['ts'] - 0.8, p['ts'] + 1.5, ctx=0.2))
                    ref = [w for w in ref if (w[1] + w[2]) / 2 > 0.7]
                    exp = norm_word(ref[0][0]) if ref else None
            else:
                if p.get('exp_last'):
                    exp = p['exp_last']
                else:
                    ref = asr_words(clean_mix(an, p['te'] - 1.5, p['te'] + 0.8, ctx=0.2))
                    ref = [w for w in ref if (w[1] + w[2]) / 2 < 1.6]
                    exp = norm_word(ref[-1][0]) if ref else None
            steps = 0; got = None
            for steps in range(0, 9):
                ts, te = (p['ts'], p['ts'] + 1.5) if side == 'start' else (p['te'] - 1.5, p['te'])
                ws = asr_words(win_audio(an, ts, te))
                got = norm_word(ws[0][0] if side == 'start' else ws[-1][0]) if ws else None
                near = [norm_word(w[0]) for w in (ws[:2] if side == 'start' else ws[-2:])]
                outside = p.get('outside_next') if side == 'end' else p.get('outside_prev')
                spill = (outside and got == outside and got != exp and len(near) == 2
                         and same_word(near[0] if side == 'end' else near[1], exp, side))
                if not spill and (exp is None or same_word(got, exp, side) or (steps == 0 and any(same_word(x, exp, side) for x in near))):
                    break
                # the window ends/starts with a scrap of the neighbouring word: step inward instead
                ef0 = an.i(p['ts']) if side == 'start' else an.i(p['te']) - 1
                if len(near) == 2 and same_word(near[0] if side == 'end' else near[1], exp, side):
                    orig = (p['ts'], p['te']), got
                    found = False
                    for _ in range(8):
                        if side == 'start': p['ts'] += 1 / FPS
                        else: p['te'] -= 1 / FPS
                        ws = asr_words(win_audio(an, *((p['ts'], p['ts'] + 1.5) if side == 'start' else (p['te'] - 1.5, p['te']))))
                        got = norm_word(ws[0][0] if side == 'start' else ws[-1][0]) if ws else None
                        if same_word(got, exp, side): found = True; break
                    if found:
                        steps = -(_ + 1)
                    else:                       # never trade a spill for a clipped word: keep the original edge
                        (p['ts'], p['te']), got = orig; steps = 0
                    break
                # only step out while the edge sits on sound: an edge in silence cannot be clipping a word
                ef = an.i(p['ts']) if side == 'start' else an.i(p['te']) - 1
                neighbour = p.get('exp_last_prev') if side == 'end' else p.get('exp_first_next')
                clipped = neighbour and same_word(got, neighbour, side)
                if not an.eok[max(0, min(an.n - 1, ef))] and not clipped:
                    break
                if side == 'start': p['ts'] -= 1 / FPS
                else: p['te'] += 1 / FPS
            report.append({'seg': p['seg'], 'edge': side, 'expected': exp, 'heard': got, 'stepped_frames': steps,
                           'ok': exp is None or same_word(got, exp, side) or exp in near})
            log(f"  edge seg{p['seg']} {side}: expected={exp!r} heard={got!r} stepped={steps}")
    return report


# =============================================================== edit decision: shots
class Timeline:
    """Output timeline built from aligned pieces."""

    def __init__(self, man, pieces, analyses, ref_cam):
        self.p = pieces
        f = 0
        for p in pieces:
            # align the piece's first frame to the reference camera's frame grid (frame at or before ts)
            tc = cam_time(man, ref_cam, p['ts'])
            k = math.floor(tc * FPS + 1e-6)
            p['ts'] = master_time(man, ref_cam, k / FPS)
            p['n'] = int(math.ceil((p['te'] - p['ts']) * FPS - 1e-6))
            p['te'] = p['ts'] + p['n'] / FPS
            p['f0'] = f; f += p['n']
        self.N = f
        # per output frame: master time, piece index
        self.piece_of = np.zeros(self.N, int); self.mt = np.zeros(self.N)
        for i, p in enumerate(pieces):
            self.piece_of[p['f0']:p['f0'] + p['n']] = i
            self.mt[p['f0']:p['f0'] + p['n']] = p['ts'] + np.arange(p['n']) / FPS
        self.who = np.zeros(self.N, '<U6'); self.speech = np.zeros(self.N, bool)
        for fi in range(self.N):
            an = analyses[pieces[self.piece_of[fi]]['an']]
            a = an.i(self.mt[fi]); b = a + 4
            r = an.host[a:b].mean() if b <= an.n else 0; h = an.guest[a:b].mean() if b <= an.n else 0
            self.speech[fi] = an.mask[a:b].any() if b <= an.n else False
            self.who[fi] = 'guest' if h > r and h > 0.3 else ('host' if r > 0.3 else '')
        # with the transcriber's words, attribute speech by words (energy alone mistakes laughs/bleed for turns)
        ws = [w for an in analyses for w in an.words]
        if ws:
            wr = np.zeros(self.N, bool); wh = np.zeros(self.N, bool)
            for w in ws:
                e = min(w['e'], w['s'] + 0.6)
                m = (self.mt >= w['s']) & (self.mt < e)
                (wr if w['who'] == 'host' else wh)[m] = True
            self.who = np.where(wh & ~wr, 'guest', np.where(wr, 'host', np.where(self.who == 'guest', 'guest', '')))
            self.who = np.where(wh & wr & (self.who == 'guest'), 'guest', self.who)
        self.forced = sorted(set(p['f0'] for p in pieces[1:]))

    def turns(self, who, merge_gap=8, min_len=4):
        m = self.who == who
        rs = runs(m)
        out = []
        for a, b in rs:
            if out and a - out[-1][1] <= merge_gap and not any(out[-1][1] <= f <= a for f in self.forced if False):
                out[-1][1] = b
            else:
                out.append([a, b])
        return [(a, b) for a, b in out if b - a >= min_len]

    def beats(self):
        """Natural change points: speech onsets after a micro-pause (>= 60 ms), led by 2 frames, plus forced cuts."""
        out = set(self.forced)
        for a, b in runs(~self.speech):
            if b - a >= 2 and b < self.N and a > 0:
                out.add(max(0, b - 2))
        return sorted(out)


MIN_SHOT_S = 1.5
HOOK_S = 2.0


def seam_info(tl, clip):
    """Segment seams (output frame) and whether the joined segments are adjacent in the source."""
    out = []
    segs = clip['segments']
    for i, p in enumerate(tl.p[1:], 1):
        if p['seg'] != tl.p[i - 1]['seg']:
            a, b = segs[tl.p[i - 1]['seg']], segs[p['seg']]
            adjacent = 0 <= float(b['start']) - float(a['end']) < 1.5
            out.append((p['f0'], adjacent))
    return out


_det = None
def detector():
    global _det
    import cv2
    if _det is None:
        _det = cv2.FaceDetectorYN.create(YUNET, '', (1920, 1080), 0.5)
    return _det


def proxy_frame(cam, k):
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.6f' % ((k - 0.5) / FPS), '-i', proxy(load_manifest(), cam),
                        '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
    if len(r.stdout) < 1920 * 1080 * 3: return None
    return np.frombuffer(r.stdout, np.uint8).reshape(1080, 1920, 3)


def find_face(man, cam, ks, side=None):
    """Median face (cx, eye_y, w) in 4K pixels over sample frames ks. side: 'left'/'right' for the wide."""
    st = face_stats(man, cam, side)
    lo, hi = man['cameras'][cam].get('face_w_accept_4k', [120, 280] if side else [300, 650])
    got = []
    for k in ks:
        f = proxy_frame(cam, k)
        if f is None: continue
        _, faces = detector().detect(f)
        if faces is None: continue
        cands = []
        for fc in faces:
            x, y, w, h = [v * 2 for v in fc[:4]]
            cx = x + w / 2; eye = (fc[5] + fc[7])  # *2 /2
            if not (lo < w < hi): continue
            if side and (side == 'left') != (cx < 1920): continue
            if abs(cx - st['cx_median']) > 700: continue
            cands.append((fc[14], cx, eye, w))
        if cands:
            got.append(max(cands)[1:])
    if not got:
        return st['cx_median'], st['eye_y_median'], st['face_w_median'], 0
    g = np.array(got)
    return float(np.median(g[:, 0])), float(np.median(g[:, 1])), float(np.median(g[:, 2])), float(np.ptp(g[:, 0]))


def crop_box(look, cx, eye, W=3840, H=2160):
    w, h = look['w'], look['h']
    x = cx - look['face_x'] * w; y = eye - look['eye_y'] * h
    x = min(max(0, x), W - w); y = min(max(0, y), H - h)
    return [int(round(x / 2) * 2), int(round(y / 2) * 2), int(w), int(h)]


def frame_shots(man, shots, tl, cams):
    for s in shots:
        mid = [s['f0'] + 2, (s['f0'] + s['f1']) // 2, s['f1'] - 3]
        parts = []
        who, look = s['look']
        wide = wide_cam(man)
        if who == 'split':
            parts = [('host', cams['host'], look, 'top'), ('guest', cams['guest'], look, 'bottom')]
        elif look == 'wide' or cams.get(who) is None:
            # no close-up of this person: their single comes from the wide (punch-in = tighter wide crop)
            parts = [(who, wide, wide_look(man, who, punch=(look == 'single_punch' and cams.get(who) is None)), 'full')]
        else:
            parts = [(who, cams[who], look, 'full')]
        s['src'] = []
        for person, cam, lk, pos in parts:
            ks = [cam_frame(man, cam, tl.mt[min(f, tl.N - 1)])[0] for f in mid]
            side = None
            if cam == wide_cam(man) and lk.startswith('wide_single_'): side = 'left' if 'left' in lk else 'right'
            L = man['looks'][cam][lk]
            cx, eye, fw, spread = find_face(man, cam, ks, side)
            if spread > 0.25 * L['w'] and lk == 'single_punch':     # subject moving a lot: use the wider look
                lk = 'single'; L = man['looks'][cam][lk]
            box = crop_box(L, cx, eye)
            s['src'].append({'person': person, 'camera': cam, 'look': lk, 'pos': pos, 'crop_4k': box,
                             'face_4k': [round(cx), round(eye), round(fw)]})
    return shots


# =============================================================== rendering
def colour_filter(man, cam):
    g = man['cameras'][cam]['colour']['gains_rgb']
    if all(abs(v - 1) < 1e-3 for v in g):
        return None
    return f'colorchannelmixer=rr={g[0]}:gg={g[1]}:bb={g[2]}'


def src_filter(man, cam, box, out_w, out_h, preview):
    x, y, w, h = box                            # 3840x2160 units
    k = source_scale(man, cam, USE_SOURCE)
    if k == 0.5:   # proxy is exactly half of 4K
        x, y, w, h = x // 2, y // 2, w // 2, h // 2
        x -= x % 2; y -= y % 2; w -= w % 2; h -= h % 2
    elif k != 1.0:
        x, y, w, h = [int(round(v * k / 2) * 2) for v in (x, y, w, h)]
    cf = colour_filter(man, cam)
    flt = f'crop={w}:{h}:{x}:{y}'
    if cf:
        flt += (f',scale={out_w}:{out_h}:flags=lanczos+accurate_rnd+full_chroma_int:in_color_matrix=bt709:in_range=tv,'
                f'format=gbrp16le,{cf},scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd,format=yuv420p')
    else:
        flt += f',scale={out_w}:{out_h}:flags=lanczos+accurate_rnd+full_chroma_int,format=yuv420p'
    return flt


def input_args(man, cam, k, preview):
    src = url(man, cam) if USE_SOURCE else proxy(man, cam)
    a = ['-ss', '%.6f' % ((k - 0.5) / FPS)]
    if src.startswith(('http://', 'https://')):
        a = ['-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_on_network_error', '1', '-reconnect_delay_max', '10'] + a
    return a + ['-i', src]


def render_shot(man, s, tl, idx, tmp, preview):
    W, H = (540, 960) if preview else (1080, 1920)
    n = s['f1'] - s['f0']
    t_start = tl.mt[s['f0']]
    ins, flts = [], []
    for j, src in enumerate(s['src']):
        k, err = cam_frame(man, src['camera'], t_start)
        src['src_frame'] = k; src['sync_err_ms'] = round(err * 1000, 2)
        src['src_cam_time'] = round(k / FPS, 4)
        ins += input_args(man, src['camera'], k, preview)
        oh = H if src['pos'] == 'full' else H // 2
        flts.append(f'[{j}:v:0]{src_filter(man, src["camera"], src["crop_4k"], W, oh, preview)},setpts=PTS-STARTPTS[v{j}]')
    if len(s['src']) == 2:
        dh = 2 if preview else 4
        flts.append(f'[v0][v1]vstack=2,drawbox=x=0:y={H // 2 - dh // 2}:w={W}:h={dh}:color=0x0d0d0d@1:t=fill[v]')
    else:
        flts[-1] = flts[-1].replace('[v0]', '[v]')
    out = f'{tmp}/shot_{idx:05d}.mkv'
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-y', *ins, '-filter_complex', ';'.join(flts), '-map', '[v]',
           '-frames:v', str(n), '-r', FPS_STR, '-c:v', 'libx264', '-preset', 'ultrafast' if preview else 'veryfast',
           '-crf', '14' if preview else '6', '-pix_fmt', 'yuv420p', '-an', out]
    for attempt in range(3):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            got = count_frames(out)
            if got == n: return out
            LOG(f'   shot {idx}: got {got} frames, expected {n}; retrying')
        else:
            LOG(f'   shot {idx} ffmpeg error: {r.stderr[-400:]}')
    raise RuntimeError(f'shot {idx} failed')


def count_frames(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_packets',
                        '-of', 'csv=p=0', p], capture_output=True, text=True)
    try: return int(r.stdout.strip())
    except ValueError: return -1


def build_audio(pieces, analyses, tmp):
    chunks = []
    for p in pieces:
        an = analyses[p['an']]
        x = clean_mix(an, p['ts'], p['ts'] + p['n'] / FPS)
        n = int(round(p['n'] / FPS * SR))
        x = np.pad(x, (0, max(0, n - len(x))))[:n]
        chunks.append(declick_edges(fade(x, 7)))
    y = np.concatenate(chunks).astype(np.float32)
    import soundfile as sf
    raw = f'{tmp}/mix_raw.wav'
    sf.write(raw, y, SR, subtype='FLOAT')
    # gentle compression, then loudness to -15 LUFS with true peak <= -1.5 dBTP
    comp = f'{tmp}/mix_comp.wav'
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', raw, '-af',
         'acompressor=threshold=-24dB:ratio=2.2:attack=12:release=180:knee=6:makeup=1', '-c:a', 'pcm_f32le', comp])
    I, TP = measure_loudness(comp)
    gain = -15.0 - I
    final = f'{tmp}/mix.wav'
    lim = 10 ** (-2.6 / 20)   # margin for AAC overshoot (true peak must stay under -1.5 dBTP)
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', comp, '-af',
         f'volume={gain:.2f}dB,aresample=192000,alimiter=limit={lim:.4f}:attack=2:release=60:level=false:latency=true,aresample=48000,'
         f'pan=stereo|c0=c0|c1=c0', '-c:a', 'pcm_f32le', final])
    I2, TP2 = measure_loudness(final)
    g = gain
    for _ in range(4):   # converge on -15 LUFS (stereo, as delivered) after the limiter
        if abs(I2 + 15) <= 0.15: break
        g -= (I2 + 15)
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', comp, '-af',
             f'volume={g:.2f}dB,aresample=192000,alimiter=limit={lim:.4f}:attack=2:release=60:level=false:latency=true,aresample=48000,'
             f'pan=stereo|c0=c0|c1=c0', '-c:a', 'pcm_f32le', final])
        I2, TP2 = measure_loudness(final)
    return final, {'integrated_lufs': I2, 'true_peak_dbtp': TP2, 'pre_gain_lufs': I}


def measure_loudness(p):
    r = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-i', p, '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True)
    t = r.stderr[r.stderr.rfind('Summary'):]
    I = float(re.search(r'I:\s+(-?[\d.]+) LUFS', t).group(1))
    m = re.search(r'Peak:\s+(-?[\d.inf]+) dBFS', t)
    TP = float(m.group(1)) if m else float('nan')
    return I, TP


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(' '.join(cmd[:6]) + '...\n' + r.stderr[-800:])
    return r


def mux(shot_files, audio, out, tmp, preview, nframes):
    lst = f'{tmp}/concat.txt'
    open(lst, 'w').write(''.join(f"file '{f}'\n" for f in shot_files))
    v = ['-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p']
    if preview:
        v += ['-preset', 'veryfast', '-crf', '22']
    else:
        v += ['-preset', 'slow', '-crf', '17', '-maxrate', '16M', '-bufsize', '32M', '-x264-params', 'keyint=48:min-keyint=12']
    run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', audio,
         '-map', '0:v:0', '-map', '1:a:0', *v, '-r', FPS_STR, '-frames:v', str(nframes),
         '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
         '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-shortest', out])


