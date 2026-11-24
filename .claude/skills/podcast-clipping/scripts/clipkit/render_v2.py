#!/usr/bin/env python3
"""The approved renderer ("v2", close-up opening). Entry point: scripts/render.py (this module is not run directly).
Reuses render_clip.py (v1) for its audio/picture primitives.

Per clip it writes (preview under out/closeup/preview/, full size under out/closeup/):
  clean/<name>.mp4          picture + sound, no text
  <name>.mp4                captions burned in (overlay.py); titled/<name>.mp4 too when a title hook is asked for
  <name>.edl.json           pieces, shots, words in output time, edge checks
  <name>.captions.json      [{"t0","t1","text"}] in clip time: edit, then re-run overlay_v2.py only
  <name>.title.json         title text + block position (1080-frame pixels) + frames it shows on (with --title)
  <name>.heard.txt          recogniser on the whole clip and on every seam window, diffed against intended words
  <name>.check.json         loudness, silences, clicks, sync, word diff, shot stats
  <name>_sheet.jpg          contact sheet of the captioned video
Per-clip hand edits (edge locks, cut-outs, mic choice, shot hints, caption fixes) live in clips/edits.json.
"""
import argparse, json, math, os, re, shutil, subprocess, sys, time, difflib
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_clip as rc
from render_clip import runs, frames as F
from common import (POD, FPS, FPS_STR, SR, TMP, YUNET, load_manifest, cam_time, cam_frame, mic_roles, person_cam, load_words,
                    load_speech_regions, asr_words, norm_word, proxy, face_stats, wide_cam)

CLIPS = f'{POD}/clips/clips.json'
EDITS = f'{POD}/clips/edits.json'
V2 = f'{POD}/out/closeup'
WORK = f'{TMP}/render_v2'
TITLE = False           # scripts/render.py --title: also make titled/<name>.mp4
LOG = print

PAD_START = 0.07        # before the first word of a segment (about 2 frames)
PAD_END_SEAM = 0.03     # after the last word of a segment that is followed by another segment
GAP_MIN, GAP_KEEP = 0.25, 0.13
rc.PAD_BEFORE, rc.PAD_AFTER = PAD_START, PAD_END_SEAM
MIN_SHOT_S = 1.5


def overlap(a, b):
    return min(a[1], b[1]) - max(a[0], b[0])


def wspan(w):
    """A word's believable span: recogniser end times run late, so cap a word at 0.6 s."""
    return (w['s'], min(w['e'], w['s'] + 0.6))


# =============================================================== words: who is audible
def audible_words(words, s, e, mics):
    """Words in [s, e) that will be heard. mics: 'auto' = the segment's main talker plus the other talker's words that
    do NOT overlap the main talker (overlapping backchannels are ducked); 'both' = everything; 'host' = Host only.
    Returns (audible, ducked)."""
    ws = [w for w in words if s - 0.6 < w['s'] < e + 0.6]
    if mics == 'both':
        return ws, []
    if mics == 'host':
        return [w for w in ws if w['who'] == 'host'], [w for w in ws if w['who'] != 'host']
    # a talker's short run (a backchannel: <= 3 words, < 1.2 s) that overlaps the other talker is ducked;
    # longer overlapping runs are real crosstalk and stay
    # (Guest's backchannels yield to any Host word; Host's yield only to Guest's real turns)
    keep, duck = [], []
    for who in ('guest', 'host'):
        mine = sorted([w for w in ws if w['who'] == who], key=lambda w: w['s'])
        other = [wspan(w) for w in (ws if who == 'guest' else keep) if w['who'] != who]
        rr = []
        for w in mine:
            if rr and w['s'] - wspan(rr[-1][-1])[1] < 0.45: rr[-1].append(w)
            else: rr.append([w])
        for r in rr:
            span = (r[0]['s'], wspan(r[-1])[1])
            short = len(r) <= 3 and span[1] - span[0] < 1.2
            if short and any(overlap(wspan(w), o) > 0.02 for w in r for o in other):
                duck += r
            else:
                keep += r
    keep.sort(key=lambda w: w['s'])
    return keep, duck


# =============================================================== pieces (audio edit)
def plan_pieces_v2(man, roles, clip, regions, words, edits):
    pieces, analyses = [], []
    segs_ed = edits.get('segments', {})
    used = [i for i in range(len(clip['segments'])) if not segs_ed.get(str(i), {}).get('skip')]
    for si, seg in enumerate(clip['segments']):
        ed = segs_ed.get(str(si), {})
        if ed.get('skip'):
            LOG(f"  seg{si} skipped: {ed.get('why', '')}")
            continue
        s, e = float(seg['start']), float(seg['end'])
        mics = ed.get('mics', 'auto')
        aud, duck = audible_words(words, s - 2.0, e + 2.0, mics)
        an = rc.Analysis(man, roles, s - 2.0, e + 2.0, regions, aud)
        an.mic_gain = rc.mic_gains(man, roles)
        if mics == 'host':
            an.mic_gain['guest'] = 0.0
        an.ducked = [w for w in duck if s - 0.05 <= w['s'] < e]
        an.seg = si
        analyses.append(an)
        ws = an.words
        pen = lambda w: 0.15 if w['who'] != 'host' else 0.0
        first = min([w for w in ws if w['e'] > s - 0.05] or ws, key=lambda w: abs(w['s'] - s) + pen(w))
        last = min([w for w in ws if w['s'] < e - 0.05] or ws, key=lambda w: abs(w['e'] - e) + pen(w))
        s_w, e_w = first['s'], last['e']
        nxw = [w for w in ws if w['s'] > last['s'] + 0.05 and w['s'] >= last['e'] - 0.15]
        next_start = min(w['s'] for w in nxw) if nxw else e_w + 0.8
        next_word = norm_word(min(nxw, key=lambda w: w['s'])['w']) if nxw else None
        pvw = [w for w in ws if w['s'] < first['s'] - 0.05 and w['e'] <= first['s'] + 0.15]
        prev_end = max(w['e'] for w in pvw) if pvw else s_w - 0.8
        prev_word = norm_word(max(pvw, key=lambda w: w['e'])['w']) if pvw else None
        e_w = min(e_w, next_start)
        same_r = sorted([w for w in ws if w['who'] == last['who']], key=lambda w: w['s'])
        i_l = next((i for i, w in enumerate(same_r) if w is last), None)
        exp_last_prev = norm_word(same_r[i_l - 1]['w']) if i_l else None
        same_f = sorted([w for w in ws if w['who'] == first['who']], key=lambda w: w['s'])
        i_f = next((i for i, w in enumerate(same_f) if w is first), None)
        exp_first_next = norm_word(same_f[i_f + 1]['w']) if i_f is not None and i_f + 1 < len(same_f) else None
        R = runs(an.mask)
        ls, fe = last['s'], first['e']

        def has_word(a, b):
            return any(w['s'] < an.t(b) and min(w['e'], w['s'] + 0.6) > an.t(a) for w in ws)
        R = [(a, b) for a, b in R if (b - a) >= 15 or ((b - a) >= 6 and has_word(a, b))]
        run_s = [(x, y) for x, y in R if x <= an.i(fe) and y > an.i(s_w)]
        if run_s and an.t(run_s[0][0]) >= prev_end - 0.03:
            start = an.t(run_s[0][0]); adjacent_prev = False
        elif run_s:
            start = an.energy_min(max(prev_end - 0.03, s_w - 0.25), s_w + 0.02) + PAD_START; adjacent_prev = True
        else:
            start = s_w; adjacent_prev = False
        run_e = [(x, y) for x, y in R if x < an.i(e_w - 0.02) and y > an.i(ls)]
        y_end = an.t(run_e[-1][1]) if run_e else e_w
        if y_end <= next_start + 0.03:
            end = y_end
        else:
            end = an.energy_min(max(ls + 0.1, e_w - 0.1), next_start + 0.02)
        is_last_seg = si == used[-1]
        pad_end = 0.0 if is_last_seg else PAD_END_SEAM
        if nxw and next_start - e_w > 0.05:
            end = min(end, next_start - 0.03 - pad_end)
        sp = [(max(an.t(a), start), min(an.t(b), end)) for a, b in R if an.t(b) > start and an.t(a) < end]
        if not sp: sp = [(start, end)]
        sp[0] = (start, sp[0][1]); sp[-1] = (sp[-1][0], end)
        segp = []
        cur = [sp[0][0] - PAD_START, sp[0][1]]
        for (a, b) in sp[1:]:
            gap = a - cur[1]
            if gap >= GAP_MIN:
                extra = (GAP_KEEP - PAD_START - PAD_END_SEAM) / 2
                segp.append([cur[0], cur[1] + PAD_END_SEAM + extra, gap])
                cur = [a - PAD_START - extra, b]
            else:
                cur[1] = b
        segp.append([cur[0], cur[1] + pad_end, None])
        # hand edges first (so hand cuts can fall in the stretch a moved edge adds), then hand cut-outs
        if 'start' in ed:
            segp = [x for x in segp if x[1] > float(ed['start']) + 0.04] or segp[-1:]
            segp[0][0] = float(ed['start'])
        if 'end' in ed:
            segp = [x for x in segp if x[0] < float(ed['end']) - 0.04] or segp[:1]
            segp[-1][1] = float(ed['end'])
        # hand cut-outs (repeated words, false starts): exact master ranges removed, no pads
        for ca, cb in sorted(ed.get('cuts', [])):
            nxt = []
            for a, b, g in segp:
                if cb <= a or ca >= b:
                    nxt.append([a, b, g]); continue
                if ca - a > 0.04: nxt.append([a, ca, 'cut'])
                if b - cb > 0.04: nxt.append([cb, b, g])
            segp = nxt
        for k, (a, b, g) in enumerate(segp):
            pieces.append({'seg': si, 'ts': a, 'te': b, 'an': len(analyses) - 1, 'gap_after_src': g,
                           'exp_first': norm_word(first['w']) if k == 0 else None,
                           'exp_last': norm_word(last['w']) if k == len(segp) - 1 else None,
                           'exp_last_prev': exp_last_prev, 'exp_first_next': exp_first_next,
                           'outside_next': next_word, 'outside_prev': prev_word,
                           'first_in_seg': k == 0, 'last_in_seg': k == len(segp) - 1,
                           'first_word_s': s_w, 'adjacent_prev': adjacent_prev, 'clip_end': is_last_seg and k == len(segp) - 1,
                           'lock_start': 'start' in ed and k == 0, 'lock_end': 'end' in ed and k == len(segp) - 1})
        mine = pieces[-len(segp):]
        del pieces[-len(segp):]
        # hand edges: drop pieces wholly outside them, clamp the rest, keep the first/last flags on the survivors
        if 'start' in ed:
            s0 = float(ed['start']); mine = [p for p in mine if p['te'] > s0 + 0.04]
            mine[0]['ts'] = s0
        if 'end' in ed:
            e0 = float(ed['end']); mine = [p for p in mine if p['ts'] < e0 - 0.04]
            mine[-1]['te'] = e0
        for k, p in enumerate(mine):
            if k == 0 and not p['first_in_seg']:
                p.update(first_in_seg=True, lock_start=True, exp_first=None)
            if k == len(mine) - 1 and not p['last_in_seg']:
                p.update(last_in_seg=True, lock_end=True, exp_last=None, gap_after_src=None, clip_end=is_last_seg)
            if k == len(mine) - 1: p['gap_after_src'] = None
        pieces += mine
    return pieces, analyses


def trim_edges_v2(pieces, analyses):
    """Pull in dead air beyond the pads; then never start later than the transcriber's first-word start - 0.04 s."""
    for p in pieces:
        an = analyses[p['an']]
        if p['last_in_seg'] and not p['lock_end']:
            pad = 0.0 if p['clip_end'] else PAD_END_SEAM
            k = an.i(p['te']) - 1; k0 = an.i(p['ts'])
            while k > k0 and not an.eok[k]: k -= 1
            if p['te'] - an.t(k + 1) > pad + 0.03: p['te'] = an.t(k + 1) + pad
        if p['first_in_seg'] and not p['lock_start']:
            k = an.i(p['ts']); k1 = an.i(p['te']) - 1
            while k < k1 and not an.eok[k]: k += 1
            if an.t(k) - p['ts'] > PAD_START + 0.03: p['ts'] = an.t(k) - PAD_START
            p['ts'] = min(p['ts'], p['first_word_s'] - 0.04)


def verify_edges_v2(man, pieces, analyses, words):
    locked = [(p['ts'], p['te']) for p in pieces]
    rep = rc.verify_edges(man, pieces, analyses, words, lambda *a: None)
    for p, (a, b) in zip(pieces, locked):
        if p['lock_start']: p['ts'] = a
        if p['lock_end']: p['te'] = b
    # v1's checker steps an edge OUT while the expected word is not recognised; when what it hears at the edge is the
    # neighbouring (excluded) word, stepping out only pulls more of that word in: undo it
    for r in rep:
        segp = [(p, ab) for p, ab in zip(pieces, locked) if p['seg'] == r['seg']]
        if r['stepped_frames'] > 0:
            p, (a, b) = segp[0] if r['edge'] == 'start' else segp[-1]
            nb = p['outside_prev'] if r['edge'] == 'start' else p['outside_next']
            if nb and r['heard'] and rc.same_word(r['heard'], nb, 'start' if r['edge'] == 'start' else 'end'):
                if r['edge'] == 'start': p['ts'] = a
                else: p['te'] = b
                r['reverted'] = True; r['ok'] = False
    for r in rep:
        LOG(f"  edge seg{r['seg']} {r['edge']}: expected={r['expected']!r} heard={r['heard']!r} stepped={r['stepped_frames']}")
    return rep


class TimelineV2(rc.Timeline):
    """Pieces keep their exact audio in-points (no snapping to a camera's frame grid: each shot part picks the nearest
    camera frame, so picture/sound error stays under half a frame); lengths are rounded to whole frames."""

    def __init__(self, man, pieces, analyses):
        self.p = pieces
        f = 0
        for p in pieces:
            p['n'] = max(1, int(round((p['te'] - p['ts']) * FPS)))
            p['te'] = p['ts'] + p['n'] / FPS
            p['f0'] = f; f += p['n']
        self.N = f
        self.piece_of = np.zeros(self.N, int); self.mt = np.zeros(self.N)
        for i, p in enumerate(pieces):
            self.piece_of[p['f0']:p['f0'] + p['n']] = i
            self.mt[p['f0']:p['f0'] + p['n']] = p['ts'] + np.arange(p['n']) / FPS
        self.who = np.zeros(self.N, '<U6'); self.speech = np.zeros(self.N, bool)
        for fi in range(self.N):
            an = analyses[pieces[self.piece_of[fi]]['an']]
            a = an.i(self.mt[fi]); b = a + 4
            self.speech[fi] = an.mask[a:b].any() if b <= an.n else False
        wr = np.zeros(self.N, bool); wh = np.zeros(self.N, bool)
        for i, p in enumerate(pieces):
            an = analyses[p['an']]
            sl = slice(p['f0'], p['f0'] + p['n'])
            for w in an.words:
                s, e = wspan(w)
                m = (self.mt[sl] >= s) & (self.mt[sl] < e)
                (wr if w['who'] == 'host' else wh)[sl] |= m
        self.wr, self.wh = wr, wh
        self.who = np.where(wh & ~wr, 'guest', np.where(wr, 'host', ''))
        self.forced = sorted(set(p['f0'] for p in pieces[1:]))


def output_words(tl, analyses):
    """Audible words remapped to output time (start inside a piece)."""
    out = []
    for i, p in enumerate(tl.p):
        an = analyses[p['an']]
        a, b = p['ts'], p['ts'] + p['n'] / FPS
        prev_b = tl.p[i - 1]['ts'] + tl.p[i - 1]['n'] / FPS if i > 0 and tl.p[i - 1]['seg'] == p['seg'] else a - 0.3
        for w in an.words:
            # a word whose transcriber start falls in the removed pause just before this piece (starts run early)
            early = prev_b - 0.02 <= w['s'] < a - 0.02 and wspan(w)[1] > a + 0.05
            # first piece of a segment: an early-starting word counts only when most of it lies inside the piece
            # (the tail of the excluded word before the edge, e.g. 06 "that" / 02 "file", must not be captioned)
            early |= p['first_in_seg'] and a - 0.15 <= w['s'] < a - 0.02 and (w['e'] - a) >= 0.6 * max(0.01, w['e'] - w['s'])
            if a - 0.02 <= w['s'] < b - 0.04 or early:
                s_out = p['f0'] / FPS + max(0.0, w['s'] - a)
                e_out = p['f0'] / FPS + (min(w['e'], b) - a)
                out.append({'w': w['w'], 'who': w['who'], 'start': round(s_out, 3), 'end': round(e_out, 3),
                            'master_start': w['s'], 'master_end': w['e'], 'piece': i, 'seg': p['seg']})
    out.sort(key=lambda w: w['start'])
    return out


# =============================================================== Guest close-up analysis (cutaways)
_det = None


def yunet(w, h):
    global _det
    import cv2
    if _det is None:
        _det = cv2.FaceDetectorYN.create(YUNET, '', (w, h), 0.5)
    _det.setInputSize((w, h))
    return _det


def eye_open(img, fc, d):
    """Share of dark (iris/pupil/lash-line) pixels in small boxes on both eyes, relative to cheek brightness.
    Drops when the eyes close or look down under the lids."""
    g = img.mean(2)
    H, W = g.shape
    vals = []
    for ex, ey in ((fc[4], fc[5]), (fc[6], fc[7])):
        hx, hy = max(2, int(0.22 * d)), max(2, int(0.12 * d))
        x0, x1, y0, y1 = int(ex - hx), int(ex + hx), int(ey - hy), int(ey + hy)
        cy = int(ey + 0.55 * d)
        if x0 < 0 or y0 < 0 or x1 >= W or cy + hy >= H: return np.nan
        skin = np.median(g[cy - hy:cy + hy, x0:x1])
        vals.append(float((g[y0:y1, x0:x1] < 0.5 * skin).mean()))
    return float(np.mean(vals))


def guest_track(man, tl, cache):
    """Per output frame on the guest's close-up camera: face score, eye-line y, yaw, pitch, mouth width (in eye distances),
    face width. NaN where nothing was detected. Sampled every 2nd frame on a 960x540 decode of the proxy."""
    if os.path.exists(cache):
        z = np.load(cache)
        if len(z['m']) == tl.N and z['m'].shape[1] == 7 and 'v2' in z.files: return z['m']
    M = np.full((tl.N, 7), np.nan)
    gcam = person_cam(man, 'guest')
    st = face_stats(man, gcam)
    for p in tl.p:
        k0, _ = cam_frame(man, gcam, p['ts'])
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.6f' % ((k0 - 0.5) / FPS), '-i', proxy(man, gcam),
                            '-frames:v', str(p['n']), '-vf', 'scale=960:540', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
        fr = np.frombuffer(r.stdout, np.uint8)
        nf = len(fr) // (960 * 540 * 3)
        fr = fr[:nf * 960 * 540 * 3].reshape(nf, 540, 960, 3)
        for j in range(0, nf, 2):
            _, faces = yunet(960, 540).detect(fr[j])
            if faces is None: continue
            best = None
            for fc in faces:
                cx = (fc[0] + fc[2] / 2) * 4
                if abs(cx - st['cx_median']) > 800 or fc[2] * 4 < 250: continue
                if best is None or fc[14] > best[14]: best = fc
            if best is None: continue
            fc = best
            ex, ey = (fc[4] + fc[6]) / 2, (fc[5] + fc[7]) / 2
            d = max(1.0, math.hypot(fc[6] - fc[4], fc[7] - fc[5]))
            yaw = (fc[8] - ex) / d; pitch = (fc[9] - ey) / d
            mw = math.hypot(fc[12] - fc[10], fc[13] - fc[11]) / d
            M[p['f0'] + j] = [fc[14], ey * 4, yaw, pitch, mw, fc[2] * 4, eye_open(fr[j], fc, d)]
    # eyes, every frame, on a full-resolution 640x640 crop of the 1080p proxy around his face (the 960x540 pass above
    # samples every 2nd frame with ~25 px eyes and misses short blinks at shot edges)
    cx2, cy2 = st['cx_median'] / 2, st['eye_y_median'] / 2
    X0 = int(min(max(0, cx2 - 320), 1920 - 640)); Y0 = int(min(max(0, cy2 - 260), 1080 - 640))
    eo_full = np.full(tl.N, np.nan)
    for p in tl.p:
        k0, _ = cam_frame(man, gcam, p['ts'])
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.6f' % ((k0 - 0.5) / FPS), '-i', proxy(man, gcam),
                            '-frames:v', str(p['n']), '-vf', f'crop=640:640:{X0}:{Y0}', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                           capture_output=True)
        fr = np.frombuffer(r.stdout, np.uint8)
        nf = len(fr) // (640 * 640 * 3)
        fr = fr[:nf * 640 * 640 * 3].reshape(nf, 640, 640, 3)
        for j in range(nf):
            _, faces = yunet(640, 640).detect(fr[j])
            if faces is None or not len(faces): continue
            fc = max(faces, key=lambda z: z[14])
            if fc[14] < 0.6 or fc[2] < 120: continue
            d = max(1.0, math.hypot(fc[6] - fc[4], fc[7] - fc[5]))
            eo_full[p['f0'] + j] = eye_open(fr[j], fc, d)
    M[:, 6] = eo_full
    # fill the odd frames from neighbours
    for c in range(6):
        v = M[:, c]; ok = ~np.isnan(v)
        if ok.sum() >= 2:
            idx = np.arange(len(v))
            fill = np.interp(idx, idx[ok], v[ok])
            gap = np.ones(len(v), bool); gap[ok] = False
            # only bridge single missing frames (not real misses)
            for i in np.where(gap)[0]:
                if 0 < i < len(v) - 1 and ok[i - 1] and ok[i + 1]: v[i] = fill[i]
    np.savez(cache, m=M, v2=np.array(1))
    return M


def guest_quality(M, tl):
    """attentive[f]: face found, head turned/pitched like his usual listening pose (looking at Host), not talking.
    react[f]: nods (eye-line movement) and smiles (mouth widening) around f, 0..~1."""
    N = tl.N
    score, ey, yaw, pitch, mw, fw = [M[:, i] for i in range(6)]
    listen = ~np.isnan(score) & (tl.who != 'guest') & ~tl.wh
    if listen.sum() < 20:
        return np.zeros(N, bool), np.zeros(N), {}, np.zeros(N)     # (v2 returned 3 values here and crashed the caller)
    ref = {k: float(np.nanmedian(v[listen])) for k, v in (('yaw', yaw), ('pitch', pitch), ('ey', ey), ('mw', mw), ('fw', fw))}
    with np.errstate(invalid='ignore'):
        att = (score >= 0.80) & (np.abs(yaw - ref['yaw']) <= 0.22) & (np.abs(pitch - ref['pitch']) <= 0.16) \
              & (np.abs(ey - ref['ey']) <= 0.45 * ref['fw']) & (np.abs(fw - ref['fw']) <= 0.18 * ref['fw'])
    att &= ~tl.wh
    att = np.nan_to_num(att).astype(bool)
    eo = M[:, 6]
    if (~np.isnan(eo)).sum() > 20:
        ref['eye_open'] = float(np.nanmedian(eo[listen]))
        with np.errstate(invalid='ignore'):
            shut = ~(eo >= 0.7 * ref['eye_open'])          # closed / looking down (NaN counts as shut)
        # a normal blink (< 0.3 s) is fine; longer closed/down stretches are not
        for a, b in runs(shut):
            if b - a > F(0.3): att[max(0, a - 2):b + 2] = False
        att &= ~np.convolve(shut.astype(float), np.ones(F(1.0)), 'same').__ge__(F(0.45))
    # reaction: eye-line motion (nod) relative to face width, mouth widening (smile), over ~1 s
    eyf = np.copy(ey); bad = np.isnan(eyf); eyf[bad] = np.interp(np.where(bad)[0], np.where(~bad)[0], eyf[~bad]) if (~bad).any() else 0
    k = F(0.5)
    sm = np.convolve(eyf, np.ones(2 * k + 1) / (2 * k + 1), 'same')
    hp = np.abs(eyf - sm) / ref['fw']
    nod = np.convolve(hp, np.ones(F(1.0)) / F(1.0), 'same')
    mwf = np.nan_to_num(mw, nan=ref['mw'])
    smile = np.clip((np.convolve(mwf, np.ones(F(0.5)) / F(0.5), 'same') - ref['mw']) / (0.15 * ref['mw']), 0, 1)
    react = np.clip(nod / 0.02, 0, 1) * 0.6 + smile * 0.4
    eyes = np.clip(np.nan_to_num(eo / ref.get('eye_open', 1.0), nan=0.0), 0, 1.5) if 'eye_open' in ref else np.ones(N)
    return att, react, ref, eyes


# =============================================================== picture plan
def clip_shape(tl, ow):
    """Frames of: last sentence start, Guest speaking runs (>= ~1 s), crosstalk/reaction anchors."""
    N = tl.N
    # last sentence: after the last sentence-ending word that is not the final word
    last_sent = 0
    for i, w in enumerate(ow[:-1]):
        if re.search(r'[.?!]$', w['w']) and w['who'] == ow[-1]['who']:
            last_sent = F(ow[i + 1]['start'])
    if N - last_sent > F(6.0):        # a long last sentence: protect only its last 4 s
        last_sent = N - F(4.0)
    # Guest runs (audible words, merged over < 0.45 s gaps)
    hw = [w for w in ow if w['who'] == 'guest']
    hr = []
    for w in hw:
        s, e = w['start'], min(w['end'], w['start'] + 0.6)
        if hr and s - hr[-1][1] < 0.45: hr[-1][1] = max(hr[-1][1], e); hr[-1][2] += 1
        else: hr.append([s, e, 1])
    rw = [(w['start'], min(w['end'], w['start'] + 0.6)) for w in ow if w['who'] == 'host']
    speak, anchors = [], []
    for s, e, n in hr:
        ov = sum(max(0, overlap((s, e), r)) for r in rw)
        solo = (e - s) - ov
        seg_last = any(w['who'] == 'guest' and abs(w['start'] - s) < 1e-6 for w in ow) and \
            not any(w['who'] == 'host' and w['start'] > s and w['seg'] == next(v['seg'] for v in ow if v['who'] == 'guest' and v['start'] >= s) for w in ow)
        if solo >= 0.9 or (seg_last and solo >= 0.4):
            speak.append((s, e))
        else:
            anchors.append(((s + e) / 2, 3 if ov > 0.05 else 2, 'crosstalk' if ov > 0.05 else 'guest reacts'))
    return last_sent, speak, anchors


def guest_bad(tl, att, eyes, edits):
    """Frames where Guest must not be shown listening: eyes shut / looking down (eyes metric), off his listening pose
    (attentive metric), or inside a hand-marked master range edits.shots.no_guest (hand on face, looking at his lap).
    While Guest himself talks, only the hand-marked ranges count."""
    N = tl.N
    voice = (tl.who == 'guest') | tl.wh
    bad = (~att | (eyes < 0.7)) & ~voice
    mt = np.zeros(N)
    for p in tl.p:
        f = np.arange(p['f0'], min(N, p['f0'] + p['n']))
        mt[f] = p['ts'] + (f - p['f0']) / FPS
    nh = np.zeros(N, bool)
    for m0, m1 in edits.get('shots', {}).get('no_guest', []):
        nh |= (mt >= m0) & (mt < m1)
    return bad | nh, nh


def plan_shots_v2(tl, clip, ow, att, react, edits, seed, eyes=None, bad=None, nh=None, guest_speak_pic=True, guest_listen_pic=True):
    """Shot kinds: R = Host full, H = Guest speaking full, C = Guest listening cutaway, S = split (Host top, Guest
    bottom). Rules from SPEC_V2 section 1.
    guest_speak_pic False: no picture of the guest at all (no H shots). guest_listen_pic False: no close-ups of both
    people, so no listening cutaways and no splits (single-camera / degraded shoots)."""
    N = tl.N
    eyes = np.ones(N) if eyes is None else eyes
    bad = np.zeros(N, bool) if bad is None else bad
    nh = np.zeros(N, bool) if nh is None else nh

    def clean_guest(a, b):
        """Guest shot a..b: does not start or end on a bad frame (shut eyes, looking away/down, hand on face) and has
        no bad stretch longer than 0.3 s."""
        a, b = int(a), int(b)
        if bad[a:a + 5].any() or bad[max(a, b - 5):b].any(): return False      # ~0.2 s clear of a blink at each cut
        return not any(e - s0 > F(0.3) for s0, e in runs(bad[a:b]))
    fmin = F(MIN_SHOT_S)
    pc = sorted(set(tl.forced))
    seams = rc.seam_info(tl, clip)
    hard = [f for f, adj in seams if not adj]
    beats = sorted(set(tl.beats()))
    edh = edits.get('shots', {})
    last_sent, speak, anchors = clip_shape(tl, ow)
    if not guest_speak_pic: speak = []
    if edh.get('force_frames'):
        # hand-made shot list (edits.shots.force_frames: [[f0, f1, kind R|C|S|H, look, why?], ...] in OUTPUT frames, tiling
        # the whole clip): bypasses the automatic plan; Guest shots are still checked and warned about, never moved
        shots = []
        for it in edh['force_frames']:
            f0, f1, k, look = int(it[0]), int(it[1]), it[2], it[3]
            shots.append({'f0': f0, 'f1': f1, 'kind': k, 'force_look': look,
                          'why': it[4] if len(it) > 4 else ('opening (title)' if f0 == 0 else 'hand shot list')})
        assert shots[0]['f0'] == 0 and shots[-1]['f1'] == N and all(a['f1'] == b['f0'] for a, b in zip(shots, shots[1:])), \
            f'force_frames must tile 0..{N}'
        for s in shots:
            if s['f1'] - s['f0'] < fmin: LOG(f"  ! forced shot {s['f0'] / FPS:.2f}-{s['f1'] / FPS:.2f} is under {MIN_SHOT_S} s")
            if s['kind'] in 'CS' and not clean_guest(s['f0'], s['f1']):
                LOG(f"  ! forced guest shot {s['f0'] / FPS:.2f}-{s['f1'] / FPS:.2f} has shut eyes / looking away frames")
            s['forced_start'] = s['f0'] in set(pc)
        return shots, {'open_end': shots[0]['f1'], 'last_sentence_start': last_sent, 'guest_speaking': speak,
                       'anchors': anchors, 'forced_shot_list': True}
    kind = np.array(['R'] * N, '<U1')
    why = {}
    ends_on_guest = ow and ow[-1]['who'] == 'guest'

    def snap(f, lo, hi, prefer=None):
        """Move a boundary to a pause-cut/seam (or a speech onset) within [lo, hi] if one is near."""
        for cand in ((prefer or []), pc, beats):
            c = [x for x in cand if lo <= x <= hi]
            if c: return min(c, key=lambda x: abs(x - f))
        return int(min(max(f, lo), hi))

    # 1. Guest speaking: full screen Guest, lead in 3 frames, back to Host just before Host's next word
    for s, e in speak:
        a = max(0, F(s) - 3)
        nxt = [w['start'] for w in ow if w['who'] == 'host' and w['start'] > e - 0.05]
        b = min(N, F(nxt[0]) - 2) if nxt else N
        b = max(b, min(N, F(e) + 4))
        if b - a < fmin: b = min(N, a + fmin)
        if N - b < fmin: b = N
        kind[a:b] = 'H'; why[a] = 'guest speaks'
    # opening shot: Host single for 3-4.5 s, carries the title
    lim_open = min([x for x in range(N) if kind[x] != 'R'] + [N])
    cands = [x for x in pc if F(3.0) <= x <= min(F(4.5), lim_open)] or \
            [x for x in beats if F(3.0) <= x <= min(F(4.5), lim_open)]
    open_end = min(cands, key=lambda x: abs(x - F(3.6))) if cands else min(F(3.6), lim_open)
    if lim_open < F(3.0):
        open_end = lim_open
    tail0 = N if ends_on_guest else N - F(1.5)       # last 1.5 s is Host full unless Guest has the last word

    def free(a, b, allow=('R',)):
        return a >= open_end and b <= N and all(k in allow for k in kind[a:b])

    def place(a, b, k, reason):
        kind[a:b] = k; why[a] = reason

    # 2. splits at interaction anchors (crosstalk > Guest reacting aloud > hand hints)
    for t in edh.get('split_at', []):
        anchors.append((t, 4, 'hint'))
    nsplit_target = 2 if N > F(25) else 1
    nsplit_target = edh.get('splits', nsplit_target)
    if not guest_listen_pic: anchors, nsplit_target = [], 0
    anchors.sort(key=lambda x: -x[1])
    nS = 0
    for t, pri, reason in anchors:
        if nS >= nsplit_target + (1 if pri >= 3 else 0): break
        fa = F(t)
        best = None
        for L in (F(3.5), F(3.0), F(4.0), F(4.5)):
            for lead in (F(1.2), F(0.8), F(1.6), F(0.4), F(2.0), F(2.4)):
                a = fa - lead; b = a + L
                # abut a following Guest block (07: split during crosstalk, then Guest full)
                hb = [x for x in range(min(b, N), min(N, b + F(0.8))) if kind[x] == 'H']
                if hb: b = hb[0]; a = min(a, b - F(3.0))
                a = snap(a, a - 5, a + 5); b = snap(b, b - 5, b + 5)
                if b - a < F(3.0) or b - a > F(5.0): continue
                if not free(a, b) or b > (N if kind[min(N - 1, b)] == 'H' else tail0) or a < F(3.0): continue
                if any(abs(a - x) < fmin and x != a for x in [f for f in range(1, N) if kind[f] != kind[f - 1]]): continue
                if not (a <= fa < b): continue
                if nh[a:b].any(): continue          # an audible reaction may have shut eyes; only hand marks count
                best = (a, b); break
            if best: break
        if best:
            place(*best, 'S', f'split: {reason}'); nS += 1
    # not enough interaction anchors: split where Host talks to him ("you") and Guest visibly reacts
    you = [F(w['start']) for w in ow if w['who'] == 'host' and norm_word(w['w']) in ('you', 'your', "you're", "you've", 'bro', 'dude', 'man')]
    bnds = lambda: [f for f in range(1, N) if kind[f] != kind[f - 1]] + [0, N]
    while nS < nsplit_target:
        best = None
        for a in range(max(F(3.0), open_end + fmin), tail0 - F(3.5), 2):
            b = a + F(3.5)
            if not free(a, b) or (tl.who[a:b] == 'guest').any(): continue
            if att[a:b].mean() < 0.85 or (eyes[a:b] < 0.7).mean() > 0.15: continue
            if not clean_guest(a, b): continue
            if any(0 < abs(x - a) < fmin or 0 < abs(x - b) < fmin for x in bnds()): continue
            if any(overlap((a, b), (x - F(6.0), x + F(6.0))) > 0 for x in bnds() if x not in (0, N) and kind[min(N - 1, x)] == 'S'): continue
            sc = float(react[a:b].mean()) + 0.4 * float(att[a:b].mean()) + 0.3 * min(2, sum(a + F(0.3) <= x < b - F(1.0) for x in you)) \
                 + 0.2 * (a in pc or a in beats)
            if best is None or sc > best[0]: best = (sc, a, b)
        if not best: break
        a, b = best[1], best[2]
        a2, b2 = snap(a, a - 4, a + 4), snap(b, b - 4, b + 4)
        if not clean_guest(a2, b2): a2, b2 = a, b          # never snap an edge onto a blink
        place(a2, b2, 'S', 'split: host to guest / reaction'); nS += 1

    # 3. Guest on screen at least every ~10 s (cutaways, then splits), >= 2 Guest shots over 20 s, >= 1 over 15 s
    no_cut = [(F(a), F(b)) for a, b in edh.get('no_cutaway', [])]
    for t in (edh.get('cutaway_at', []) if guest_listen_pic else []):
        a = F(t); b = a + F(2.0)
        if free(a, b): place(a, b, 'C', 'cutaway: hint')

    def hud_shots():
        return sum(1 for f in range(N) if kind[f] in 'HSC' and (f == 0 or kind[f - 1] != kind[f]))

    def gaps():
        vis = np.isin(kind, ['H', 'S', 'C'])
        return sorted([(a, b) for a, b in runs(~vis)], key=lambda g: -(g[1] - g[0]))

    def try_cutaway(g0, g1, strict=True):
        best = None
        lo = max(g0 + (fmin if g0 > 0 else 0), F(3.0), open_end + (0 if g0 >= open_end else 0))
        if g0 < open_end: lo = max(lo, open_end + fmin) if open_end - g0 < fmin else max(lo, open_end)
        hi_end = min(g1 - (fmin if g1 < N else 0), last_sent, tail0)
        mid = (g0 + g1) / 2
        for a in range(lo, hi_end - F(1.5) + 1):
            for L in (F(2.0), F(1.75), F(2.25), F(1.6), F(2.5)):
                b = a + L
                if b > hi_end: continue
                if b < g1 and g1 - b < fmin: continue
                if not free(a, b): continue
                if any(kind[x] != 'R' for x in range(max(0, a - F(3.0)), min(N, b + F(3.0)))): continue   # spaced from other Guest shots
                if any(overlap((a, b), x) > 0 for x in no_cut): continue
                if (tl.who[a:b] == 'guest').any() or tl.wh[a:b].any(): continue
                if any(a < x < b for x in hard): continue
                if strict and not att[a:b].all(): continue
                if not clean_guest(a, b): continue
                inside = sum(a < x < b for x in pc)
                sc = float(react[a:b].mean()) + 0.25 * (a in pc or a in beats) - 0.35 * inside \
                     + 0.8 * float(np.clip(eyes[a:b], 0, 1.2).mean()) - 1.5 * float((eyes[a:b] < 0.7).mean()) \
                     - 0.6 * abs((a + b) / 2 - mid) / max(1, (g1 - g0)) - (0 if strict else 1.0 - float(att[a:b].mean()))
                if best is None or sc > best[0]: best = (sc, a, b)
        return best

    for _ in range(12 if guest_listen_pic else 0):
        G = gaps()
        if not G: break
        need_count = (N > F(20) and hud_shots() < 2) or (N > F(15) and hud_shots() < 1)
        g0, g1 = G[0]
        if g1 - g0 <= F(11.0) and not need_count: break
        cand = try_cutaway(g0, g1, True) or try_cutaway(g0, g1, False)
        if cand:
            place(cand[1], cand[2], 'C', 'cutaway: guest every ~10 s'); continue
        # fallback: a split in the gap
        done = False
        for a in sorted(range(max(g0 + fmin, F(3.0), open_end), min(g1, tail0) - F(3.0)), key=lambda x: abs(x + F(1.75) - (g0 + g1) / 2)):
            b = a + F(3.5)
            if free(a, b) and (g1 - b >= fmin or b == g1) and clean_guest(a, b):
                place(a, b, 'S', 'split: guest every ~10 s'); done = True; break
        if not done:
            LOG(f'  ! could not fill a {(g1 - g0) / FPS:.1f} s stretch without Guest at {g0 / FPS:.1f}s'); break

    # 4. build shots from kinds; split long Host/Guest runs every 3-6 s at pause-cuts/seams/onsets
    bounds = [0, open_end] + [f for f in range(1, N) if kind[f] != kind[f - 1]]
    bounds = sorted(set(b for b in bounds if 0 <= b < N))
    shots = []
    for a, b in zip(bounds, bounds[1:] + [N]):
        if b > a: shots.append({'f0': a, 'f1': b, 'kind': kind[a], 'why': why.get(a, 'start' if a == 0 else 'rhythm')})
    shots[0]['why'] = 'opening (title)'
    out = []
    for s in shots:
        if s['kind'] in 'RH' and s['f0'] != 0:
            cur = s['f0']
            hs = [x for x in hard if s['f0'] + fmin <= x <= s['f1'] - fmin]
            while s['f1'] - cur > F(6.0) or [x for x in hs if x > cur + fmin]:
                lo, hi = cur + F(2.5), min(cur + F(6.0), s['f1'] - F(2.0))
                hsn = [x for x in hs if cur + fmin <= x <= cur + F(6.0)]
                if hsn: c = hsn[0]
                elif hi < lo:
                    break
                else:
                    c = snap(cur + F(4.2), lo, hi, [x for x in hard if lo <= x <= hi])
                if c - cur < fmin or s['f1'] - c < fmin: break
                out.append({**s, 'f0': cur, 'f1': c, 'why': s['why'] if cur == s['f0'] else ('seam' if c in hard else 'rhythm')})
                cur = c
                if s['f1'] - cur <= F(6.0) and not [x for x in hs if x > cur + fmin]: break
            out.append({**s, 'f0': cur, 'why': s['why'] if cur == s['f0'] else 'rhythm'})
        else:
            out.append(s)
    shots = out
    # last check on every listening Guest shot (cutaway/split): trim ends off bad frames (never into his own words)
    for i, s0 in enumerate(shots):
        if s0['kind'] not in 'CS' or s0['why'].startswith(('split: crosstalk', 'split: guest reacts')): continue
        a, b = s0['f0'], s0['f1']
        while b - a > fmin and bad[a:a + 3].any() and i > 0 and shots[i - 1]['kind'] == 'R': a += 1
        while b - a > fmin and bad[b - 3:b].any() and i + 1 < len(shots) and shots[i + 1]['kind'] == 'R': b -= 1
        if (a, b) != (s0['f0'], s0['f1']):
            if i > 0: shots[i - 1]['f1'] = a
            if i + 1 < len(shots): shots[i + 1]['f0'] = b
            s0['f0'], s0['f1'] = a, b
        if not clean_guest(a, b):
            LOG(f"  ! guest shot {a / FPS:.2f}-{b / FPS:.2f} ({s0['why']}) still has shut eyes / looking away")
    # merge any shot under 1.5 s into its neighbour of the same person (never touches the opening shot's start)
    changed = True
    while changed:
        changed = False
        for i, s in enumerate(shots):
            if s['f1'] - s['f0'] < fmin and len(shots) > 1:
                j = i - 1 if i > 0 else i + 1
                if i > 0 and i + 1 < len(shots) and shots[i + 1]['kind'] == s['kind']: j = i + 1
                a, b = min(shots[i]['f0'], shots[j]['f0']), max(shots[i]['f1'], shots[j]['f1'])
                keep = shots[j] if (shots[j]['kind'] != 'C' or s['kind'] == 'C') else s
                if i == 0 or j == 0: keep = shots[0]
                shots[min(i, j)] = {**keep, 'f0': a, 'f1': b}
                del shots[max(i, j)]
                changed = True; break
    for s in shots:
        s['forced_start'] = s['f0'] in set(pc)
    return shots, {'open_end': open_end, 'last_sentence_start': last_sent, 'guest_speaking': speak,
                   'anchors': anchors}


def assign_looks_v2(shots, seed, has_wide=True):
    rng = np.random.default_rng(seed)
    prevR = None; prev = None
    for i, s in enumerate(shots):
        k = s['kind']
        if s.get('force_look'):         # hand shot list (edits.shots.force_frames)
            look = ({'S': 'split', 'R': 'host'}.get(k, 'guest'), s['force_look'])
            if k == 'R': prevR = look
        elif k == 'S':
            look = ('split', 'half')
        elif k == 'C':
            look = ('guest', 'single')
        elif k == 'H':
            look = ('guest', 'single_punch' if prev == ('guest', 'single') else 'single')
        else:
            if i == 0:
                look = ('host', 'single')
            else:
                opts = ['single', 'single_punch', 'wide']
                w = np.array([0.40, 0.38, 0.22])
                if prev and prev[0] == 'host':
                    w[opts.index(prev[1])] = 0
                if prevR and prev and prev[0] != 'host':
                    w[opts.index(prevR[1])] *= 0.5        # back from Guest: usually a different Host framing
                if s['f1'] - s['f0'] < F(2.0) or not has_wide: w[2] = 0
                if s.get('why') == 'seam' and prev and prev[0] == 'host':
                    w[opts.index(prev[1])] = 0
                w = w / w.sum()
                look = ('host', opts[int(rng.choice(3, p=w))])
            prevR = look
        s['look'] = look; prev = look
    return shots


def tune_looks(man):
    """v2 framings now live in the manifest (ingest.py writes the guest's split half higher and wider so his eyes and
    mouth clear the captions, y 1408-1472 on the 1080x1920 frame). Kept as a no-op for callers."""
    return man


# =============================================================== EDL
def write_edl(path, clip, roles, cams, tl, shots, ow, edge_report, audio_stats, preview, plan_info):
    def ot(f): return round(f / FPS, 4)
    edl = {'id': clip['id'], 'slug': clip['slug'], 'engine': 'v2', 'fps': FPS_STR,
           'resolution': [540, 960] if preview else [1080, 1920], 'duration_s': ot(tl.N), 'frames': tl.N,
           'mic_roles': roles, 'cameras': cams,
           'pieces': [{'out_start': ot(p['f0']), 'out_end': ot(p['f0'] + p['n']), 'master_in': round(p['ts'], 4),
                       'master_out': round(p['ts'] + p['n'] / FPS, 4), 'segment': p['seg'], 'frames': p['n']} for p in tl.p],
           'shots': [], 'words': [{k: w[k] for k in ('w', 'who', 'start', 'end', 'master_start', 'master_end', 'seg')} for w in ow],
           'edge_checks': edge_report, 'audio': audio_stats,
           'plan': {'open_end_s': ot(plan_info['open_end']), 'last_sentence_start_s': ot(plan_info['last_sentence_start']),
                    'guest_speaking': plan_info['guest_speaking'], 'split_anchors': plan_info['anchors'],
                    'auto_tighten': plan_info.get('auto_tighten', [])}}
    names = {'R': 'host', 'H': 'guest_speaking', 'C': 'guest_cutaway', 'S': 'split'}
    for i, s in enumerate(shots):
        edl['shots'].append({'index': i, 'out_start': ot(s['f0']), 'out_end': ot(s['f1']), 'frames': s['f1'] - s['f0'],
                             'kind': names[s['kind']], 'layout': 'split' if s['look'][0] == 'split' else 'full', 'look': s['look'][1],
                             'master_start': round(tl.mt[s['f0']], 4), 'master_end': round(tl.mt[s['f1'] - 1] + 1 / FPS, 4),
                             'hides_cut': bool(s.get('forced_start')), 'reaction': s['kind'] == 'C',
                             'reason': s.get('why'), 'sources': s['src'], 'parts': s.get('parts', [])})
    json.dump(edl, open(path, 'w'), indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    return edl


# =============================================================== title placement
def title_position(clean_mp4, open_frames, scale, title_text):
    """Detect Host's face across the opening shot of the clean render; put the title block's top >= 50 px below the
    lowest chin estimate (1080-frame pixels). Returns (y_top, chin, block_h, ok)."""
    import overlay as ov
    W, H = int(1080 * scale), int(1920 * scale)
    ks = sorted(set(np.linspace(0, open_frames - 1, 8).astype(int)))
    sel = '+'.join(f'eq(n\\,{k})' for k in ks)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', clean_mp4, '-vf', f'select={sel}', '-fps_mode', 'passthrough',
                        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, H, W, 3)
    chins = []
    for f in fr:
        _, faces = yunet(W, H).detect(f)
        if faces is None: continue
        fc = max(faces, key=lambda z: z[2] * z[3])
        eye = (fc[5] + fc[7]) / 2; mouth = (fc[11] + fc[13]) / 2
        chin = max(fc[1] + fc[3], mouth + 0.75 * (mouth - eye))
        chins.append(float(chin) / scale)
    chin = max(chins) if chins else 1000.0
    bh = ov.title_block_height(title_text, 'closeup')
    y = int(math.ceil(chin + 50))
    y = max(y, 250)
    ok = y + bh <= min(1350, 1408 - 40)
    return int(y), round(float(chin), 1), int(bh), bool(ok), len(chins)


# =============================================================== checks
def seam_report(clean_mp4, edl, path):
    """Recognise the whole clip and a window 1 s either side of every segment join (plus the first and last 1.5 s);
    diff each against the intended (audible transcript) words."""
    import check_clip as cc
    x = cc.out_audio(clean_mp4)
    dur = len(x) / SR
    words = edl['words']
    lines = []
    def rec(a, b):
        ws = asr_words(x[int(max(0, a) * SR):int(min(dur, b) * SR)])
        if len(ws) < max(1, (b - a) * 0.8):          # the recogniser sometimes drops a short window: widen and keep the middle
            w2 = asr_words(x[int(max(0, a - 0.4) * SR):int(min(dur, b + 0.4) * SR)])
            off = max(0, a - 0.4)
            w2 = [(w, s0 + off, e0 + off) for w, s0, e0 in w2]
            got = [(w, s0 - max(0, a), e0) for w, s0, e0 in w2 if a - 0.05 <= s0 < b - 0.05]
            if len(got) > len(ws): ws = got
        return ws
    # whole clip: one recognition per segment span (more reliable than one long pass)
    allw = []
    spans = []
    for pc in edl['pieces']:
        if spans and spans[-1][2] == pc['segment']: spans[-1][1] = pc['out_end']
        else: spans.append([pc['out_start'], pc['out_end'], pc['segment']])
    for a, b, _ in spans:
        allw += [norm_word(w) for w, _, _ in asr_words(x[int(a * SR):int(b * SR)])]
    exp = [norm_word(w['w']) for w in words]
    sm = difflib.SequenceMatcher(a=exp, b=allw, autojunk=False)
    ops = [(t, ' '.join(exp[i1:i2]), ' '.join(allw[j1:j2])) for t, i1, i2, j1, j2 in sm.get_opcodes() if t != 'equal']
    lines.append(f'# {edl["id"]}_{edl["slug"]}  {dur:.2f} s')
    lines.append('## whole clip, heard:')
    lines.append(' '.join(allw))
    lines.append(f'## whole clip, differences from intended (match {sm.ratio():.3f}):')
    lines += [f'  {t:8s} intended [{a}]  heard [{b}]' for t, a, b in ops] or ['  none']
    joins = []
    P = edl['pieces']
    for i in range(1, len(P)):
        if P[i]['segment'] != P[i - 1]['segment']:
            joins.append(('seam', P[i]['out_start'], f'seg{P[i - 1]["segment"] + 1}->seg{P[i]["segment"] + 1}'))
    windows = [('start', 0.0, 1.5, 0.0)] + [(f'seam {lab}', max(0, t - 1.0), min(dur, t + 1.0), t) for _, t, lab in joins] + \
              [('end', max(0, dur - 1.5), dur, dur)]
    lines.append('## seam windows (1 s either side of each join; first/last 1.5 s)')
    flags = []
    for name, a, b, t in windows:
        hw = [norm_word(w) for w, _, _ in rec(a, b)]
        iw = [w for w in words if a - 0.05 <= w['start'] < b - 0.08]
        ie = [norm_word(w['w']) for w in iw]
        sm2 = difflib.SequenceMatcher(a=ie, b=hw, autojunk=False)
        bad = []
        for tag, i1, i2, j1, j2 in sm2.get_opcodes():
            if tag == 'equal': continue
            # a word cut by the window's own edge is not a seam problem: only flag words near the join / clip edge
            near = [w for w in iw[i1:i2] if abs(w['start'] - t) < 0.7 or abs(min(w['end'], w['start'] + 0.6) - t) < 0.5]
            if tag == 'insert':
                pos = iw[i1]['start'] if i1 < len(iw) else (iw[-1]['start'] if iw else t)
                if abs(pos - t) < 0.7: bad.append(f'extra [{" ".join(hw[j1:j2])}]')
            elif near:
                bad.append(f'{tag} [{" ".join(ie[i1:i2])}] -> [{" ".join(hw[j1:j2])}]')
        verdict = 'OK' if not bad else 'CHECK: ' + '; '.join(bad)
        if bad: flags.append((name, verdict))
        lines.append(f'[{name} | {a:6.2f}-{b:6.2f}s]')
        lines.append(f'   intended: {" ".join(ie)}')
        lines.append(f'   heard:    {" ".join(hw)}')
        lines.append(f'   {verdict}')
    open(path, 'w').write('\n'.join(lines) + '\n')
    return {'match_ratio': round(sm.ratio(), 3), 'differences': ops, 'seam_flags': flags, 'heard_words': len(allw), 'expected_words': len(exp)}


def face_clearance(clean_mp4, edl, title, scale):
    """Detect every face (YuNet) on frames sampled every ~0.5 s of the clean render. Flags: eyes or mouth inside the
    caption band (y 1400-1480, x 250-830 on the 1080 frame); any face part (top of head .. chin) inside the title block."""
    Wd, Hd = int(1080 * scale), int(1920 * scale)
    N = edl['frames']
    ks = sorted(set(list(range(0, N, 12)) + [N - 1] + [round(s['out_start'] * FPS) + s['frames'] // 2 for s in edl['shots']]))
    sel = '+'.join(f'eq(n\\,{k})' for k in ks)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', clean_mp4, '-vf', f'select={sel}', '-fps_mode', 'passthrough',
                        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, Hd, Wd, 3)
    cap_hits, title_hits, worst = [], [], 9999
    t0, t1 = title['frame_start'], title['frame_end']
    ty0, ty1 = title['y_top'], title['y_top'] + title['block_h']
    for k, f in zip(ks, fr):
        _, faces = yunet(Wd, Hd).detect(f)
        if faces is None: continue
        for fc in faces:
            if fc[14] < 0.85 or fc[2] / scale < 110: continue
            x, y, w, h = [v / scale for v in fc[:4]]
            pts = {'eye_r': fc[5] / scale, 'eye_l': fc[7] / scale, 'mouth_r': fc[11] / scale, 'mouth_l': fc[13] / scale}
            mx = (fc[10] + fc[12]) / 2 / scale
            mouth = (pts['mouth_r'] + pts['mouth_l']) / 2; eye = (pts['eye_r'] + pts['eye_l']) / 2
            chin = max(y + h, mouth + 0.75 * (mouth - eye))
            if 250 < mx < 830:
                if any(1400 <= v <= 1480 for v in pts.values()):
                    cap_hits.append({'t': round(k / FPS, 2), 'mouth_y': round(float(mouth)), 'eye_y': round(float(eye))})
                if mouth < 1400: worst = min(worst, 1400 - mouth)
            if t0 <= k < t1 and overlap((y - 0.35 * h, chin), (ty0, ty1)) > 0:
                title_hits.append({'t': round(k / FPS, 2), 'face_top': round(float(y)), 'chin': round(float(chin))})
    return {'frames_checked': len(fr), 'eyes_or_mouth_in_caption_band': cap_hits, 'face_in_title': title_hits,
            'min_mouth_clearance_above_caption_px': round(float(worst))}


def check_v2(clean_mp4, edl, man, path):
    import check_clip as cc
    x = cc.out_audio(clean_mp4)
    I, TP = cc.loudness(clean_mp4)
    sh = edl['shots']
    hud = [s for s in sh if s['kind'] != 'host']
    vis = np.zeros(edl['frames'], bool)
    for s in hud:
        a = int(round(s['out_start'] * FPS)); vis[a:a + s['frames']] = True
    no_h = max([(b - a) / FPS for a, b in runs(~vis)] or [0])
    res = {'clip': os.path.basename(clean_mp4), 'duration_s': round(len(x) / SR, 2), 'loudness_lufs': I, 'true_peak_dbtp': TP,
           'silence': cc.silences(x, edl), 'clicks': cc.clicks(x, edl),
           'shots': len(sh), 'shot_len_s': {'min': round(min(s['out_end'] - s['out_start'] for s in sh), 2),
                                            'max': round(max(s['out_end'] - s['out_start'] for s in sh), 2),
                                            'mean': round(edl['duration_s'] / len(sh), 2)},
           'guest_shots': {'cutaway': sum(s['kind'] == 'guest_cutaway' for s in sh), 'split': sum(s['kind'] == 'split' for s in sh),
                            'speaking': sum(s['kind'] == 'guest_speaking' for s in sh)},
           'longest_without_guest_s': round(no_h, 2),
           'first_shot_s': round(sh[0]['out_end'], 2), 'first_shot_kind': sh[0]['kind'],
           'last_shot': {'kind': sh[-1]['kind'], 'len_s': round(sh[-1]['out_end'] - sh[-1]['out_start'], 2)},
           'edge_checks': edl['edge_checks']}
    res['sync'] = cc.sync_check(edl, man)
    if res['sync']:
        v = [abs(r['mapping_error_ms']) for r in res['sync']]
        res['sync_abs_ms'] = {'median': round(float(np.median(v)), 1), 'max': round(max(v), 1)}
    json.dump(res, open(path, 'w'), indent=1)
    return res


# =============================================================== main
def tighten(tl, analyses):
    """Silence check on the cut audio (same measure as check_clip.silences: band energy < 95th pct - 30 dB).
    Returns master-time changes that bring the head to <= 2 frames before the first sound and every internal pause
    over 0.2 s down to ~0.14 s. Only 'dead' audio (< 95th pct - 42 dB) is removed, so quiet words stay whole.
    Each change: (seg, 'start'|'end'|'cut', value)."""
    from common import band_energy_db
    ys, starts = [], []
    for p in tl.p:
        x = rc.clean_mix(analyses[p['an']], p['ts'], p['ts'] + p['n'] / FPS)
        n = int(round(p['n'] / FPS * SR)); starts.append(p['f0'] / FPS)
        ys.append(np.pad(x, (0, max(0, n - len(x))))[:n])
    y = np.concatenate(ys)
    E = band_energy_db(y); ref = np.percentile(E, 95)
    sil = E < ref - 30; dead = E < ref - 42
    ch = []

    def at(u):          # output second -> (piece, master second)
        k = max(i for i, s0 in enumerate(starts) if s0 <= u + 1e-9)
        p = tl.p[k]
        return p, p['ts'] + (u - starts[k])

    def remove(u0, u1, ra=None):
        pa, m0 = at(u0); pb, m1 = at(u1 - 1e-4)
        ka = tl.p.index(pa)
        if pa is pb:
            # a gap before the segment's first word is moved with a start lock (a cut there would be undone by the
            # 'start no later than first word - 0.04 s' rule)
            if pa['first_in_seg'] and (abs(m0 - pa['ts']) < 0.012 or m1 <= pa.get('first_word_s', -1) + 0.02
                                       or (ra is not None and starts[ka] >= ra - 0.005)):
                ch.append((pa['seg'], 'start', round(min(m1, pa['ts'] + (m1 - m0)), 3)))
            elif pa['last_in_seg'] and abs(m1 - (pa['ts'] + pa['n'] / FPS)) < 0.012: ch.append((pa['seg'], 'end', round(m0, 3)))
            else: ch.append((pa['seg'], 'cut', (round(m0, 3), round(m1, 3))))
            return
        ea = pa['ts'] + pa['n'] / FPS
        if ea - m0 >= 0.01:
            ch.append((pa['seg'], 'end', round(m0, 3)) if pa['last_in_seg'] else (pa['seg'], 'cut', (round(m0, 3), round(ea + 0.002, 3))))
        if m1 - pb['ts'] >= 0.01:
            ch.append((pb['seg'], 'start', round(m1, 3)) if pb['first_in_seg'] else (pb['seg'], 'cut', (round(pb['ts'] - 0.002, 3), round(m1, 3))))
    rs = runs(sil)
    for a, b in rs:
        if a <= 3:                                     # head (a click-free first frame or two may sit before it): keep 0.06 s before the first sound, never past the first word
            if b * 0.01 > 0.083 and a <= 3:
                # first sound = first frame within 36 dB of speech level (a soft or quiet first word counts as sound)
                on = next((i for i in range(a, len(E)) if E[i] >= ref - 36), b)
                r = on * 0.01 - 0.05
                if r >= 0.02: remove(0.0, r)
            continue
        # measured on the uncompressed mix, where pauses read ~0.05 s shorter than on the delivered (compressed) file
        if b >= len(E) or (b - a) * 0.01 <= 0.15: continue
        dr = [(c, d) for c, d in runs(dead[a:b])]
        if not dr: continue
        c, d = max(dr, key=lambda r: r[1] - r[0])
        want = (b - a) * 0.01 - 0.11
        r = min(want, (d - c) * 0.01 - 0.04)
        if r < 0.03: continue
        mid = (a + (c + d) / 2) * 0.01
        remove(mid - r / 2, mid + r / 2, a * 0.01)
    return ch


def render(clip, preview, edits_all, keep=False, plan_only=False, overlay_pass=True):
    t_wall = time.time()
    man = tune_looks(load_manifest())
    roles = mic_roles(man)
    cams = {'host': person_cam(man, 'host', roles), 'guest': person_cam(man, 'guest', roles)}
    wide = wide_cam(man)
    if cams['host'] is None and wide is None:
        raise SystemExit('manifest has neither a host close-up nor a wide camera')
    guest_listen_pic = bool(cams['host'] and cams['guest'])       # cutaways + splits need both close-ups
    guest_speak_pic = bool(cams['guest'] or wide)                  # guest talking: close-up, else his side of the wide
    words = load_words()
    regions = load_speech_regions()
    edits = edits_all.get(clip['id'], {})
    name = f"{clip['id']}_{clip['slug']}"
    odir = f'{V2}/preview' if preview else V2
    os.makedirs(f'{odir}/clean', exist_ok=True)
    tmp = f'{WORK}/{name}{"_prev" if preview else ""}'
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    LOG(f"[{clip['id']}] {name}: {len(clip['segments'])} segments")
    if not guest_listen_pic:
        LOG('  degraded: no close-ups of both people, so no listening cutaways or splits'
            + ('' if guest_speak_pic else '; no picture of the guest at all'))
    import copy
    edits = copy.deepcopy(edits)
    auto = []
    for it in range(4):
        pieces, analyses = plan_pieces_v2(man, roles, clip, regions, words, edits)
        trim_edges_v2(pieces, analyses)
        edge = verify_edges_v2(man, pieces, analyses, words)
        tl = TimelineV2(man, pieces, analyses)
        ch = tighten(tl, analyses) if it < 3 else []
        if not ch: break
        for seg, kind, v in ch:
            se = edits.setdefault('segments', {}).setdefault(str(seg), {})
            if kind == 'cut': se.setdefault('cuts', []).append(list(v))
            elif kind == 'start': se['start'] = max(v, float(se.get('start', -1e9)))
            else: se['end'] = min(v, float(se.get('end', 1e9)))
            auto.append([seg, kind, v])
            LOG(f"  tighten: seg{seg} {kind} {v}")
    ow = output_words(tl, analyses)
    os.makedirs(f'{WORK}/cache', exist_ok=True)
    key = f"{clip['id']}_" + '%08x' % (abs(hash(tuple(round(p['ts'], 3) for p in pieces))) % (1 << 32))
    seed = int(re.sub(r'\D', '', clip['id']) or 0) * 7 + len(clip['id'])
    if cams['guest']:
        M = guest_track(man, tl, f'{WORK}/cache/guest_{key}.npz')
        att, react, ref, eyes = guest_quality(M, tl)
    else:
        att, react, eyes = np.zeros(tl.N, bool), np.zeros(tl.N), np.zeros(tl.N)
    bad, nh = guest_bad(tl, att, eyes, edits)
    shots, info = plan_shots_v2(tl, clip, ow, att, react, edits, seed, eyes, bad, nh, guest_speak_pic, guest_listen_pic)
    info['auto_tighten'] = auto
    shots = assign_looks_v2(shots, seed, has_wide=wide is not None and cams['host'] is not None)   # no host close-up: 'wide' would repeat 'single'
    shots = rc.frame_shots(man, shots, tl, cams)
    LOG(f"  {len(pieces)} pieces, {tl.N} frames ({tl.N / FPS:.2f} s), {len(shots)} shots; guest attentive {att.mean():.0%}")
    for i, s in enumerate(shots):
        LOG(f"   shot {i:2d} {s['f0'] / FPS:6.2f}-{s['f1'] / FPS:6.2f} {s['kind']} {s['look'][0]:6s} {s['look'][1]:12s} {s['why']}")
    if plan_only:
        return None
    audio, astats = rc.build_audio(tl.p, analyses, tmp)
    files = []
    for i, s in enumerate(shots):
        bnd = [s['f0']] + [p['f0'] for p in tl.p if s['f0'] < p['f0'] < s['f1']] + [s['f1']]
        s['parts'] = []
        for j, (a, b) in enumerate(zip(bnd, bnd[1:])):
            sub = {**s, 'f0': a, 'f1': b, 'src': [dict(x) for x in s['src']]}
            files.append(rc.render_shot(man, sub, tl, i * 100 + j, tmp, preview))
            s['parts'].append({'out_start': round(a / FPS, 4), 'frames': b - a,
                               'src_frames': {x['camera']: x['src_frame'] for x in sub['src']},
                               'sync_err_ms': {x['camera']: x['sync_err_ms'] for x in sub['src']}})
            if j == 0:
                for x, y in zip(s['src'], sub['src']):
                    x.update({k: y[k] for k in ('src_frame', 'sync_err_ms', 'src_cam_time')})
    clean = f'{odir}/clean/{name}.mp4'
    rc.mux(files, audio, clean, tmp, preview, tl.N)
    astats['render_seconds'] = round(time.time() - t_wall, 1)
    astats['picture_source'] = 'original' if rc.USE_SOURCE else 'proxy'
    edl = write_edl(f'{odir}/{name}.edl.json', clip, roles, cams, tl, shots, ow, edge, astats, preview, info)
    # captions + title description (text files the overlay pass reads)
    import captions_v2
    cap_path = f'{odir}/{name}.captions.json'
    caps = captions_v2.make_captions(edl, clip, edits.get('caption_fixes', []), edits.get('word_fixes', []),
                                     edits.get('drop_backchannel', False))
    caps = captions_v2.apply_patches(caps, edits.get('caption_patches', {}))
    json.dump(caps, open(cap_path, 'w'), indent=1, ensure_ascii=False)
    scale = 0.5 if preview else 1.0
    title = {'text': '', 'y_top': 0, 'frame_start': 0, 'frame_end': 0, 'block_h': 0}
    if TITLE and clip.get('title_hook'):
        y, chin, bh, ok, nfaces = title_position(clean, shots[0]['f1'] - shots[0]['f0'], scale, clip['title_hook'])
        title = {'text': clip['title_hook'], 'y_top': y, 'frame_start': 0, 'frame_end': shots[0]['f1'],
                 'chin_y_max': chin, 'block_h': bh, 'fits_safe_area': ok, 'faces_found': nfaces, 'style': 'closeup'}
        json.dump(title, open(f'{odir}/{name}.title.json', 'w'), indent=1, ensure_ascii=False)
        if not ok: LOG(f'  ! title does not fit below the chin ({chin}) inside the safe area')
    final = f'{odir}/{name}.mp4'
    if overlay_pass:
        import overlay
        overlay.overlay(clean, cap_path, None, final, preview)
        if title['text']:
            os.makedirs(f'{odir}/titled', exist_ok=True)
            overlay.overlay(clean, cap_path, f'{odir}/{name}.title.json', f'{odir}/titled/{name}.mp4', preview)
    rep = seam_report(clean, edl, f'{odir}/{name}.heard.txt')
    chk = check_v2(clean, edl, man, f'{odir}/{name}.check.json')
    chk['words'] = rep
    chk['title'] = title
    chk['faces'] = face_clearance(clean, edl, title, scale)
    chk['captions'] = len(caps)
    chk['render_seconds'] = round(time.time() - t_wall, 1)
    json.dump(chk, open(f'{odir}/{name}.check.json', 'w'), indent=1)
    if overlay_pass:
        import contact_sheet_v2
        contact_sheet_v2.sheet(final, edl, f'{odir}/{name}_sheet.jpg')
    if not keep: shutil.rmtree(tmp, ignore_errors=True)
    LOG(f"  -> {final}  {tl.N / FPS:.2f} s, {astats['integrated_lufs']} LUFS, TP {astats['true_peak_dbtp']}, "
        f"no-guest max {chk['longest_without_guest_s']} s, guest {chk['guest_shots']}, seam flags {len(rep['seam_flags'])}, "
        f"{chk['render_seconds']} s wall")
    return final
