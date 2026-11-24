#!/usr/bin/env python3
"""Optional "wide opening" variant (v3). Entry point: scripts/render.py --opening wide (not run directly).

What changes against the close-up cut (render_v2.py), which must be rendered first for the same clip:
  * shot 0 is the host alone from the WIDE camera, the crop at the top of the source so there is room above the head;
    with --title the title hook sits ABOVE the head (overlay.py title style 'wide').
  * the first guest shot (cutaway / split / guest speaking) starts 3.0-4.5 s into the clip; then the host's close-up.
  * everything after that follows the close-up shot plan (out/closeup/<name>.edl.json) as closely as possible.
  * AUDIO IS NOT RE-PLANNED: the close-up render's audio stream is copied bit for bit; its captions file is reused.
Shoot settings (shoot.json "wide_opening"): plate_cam_time [a, b] = a stretch of WIDE-camera time with both chairs
empty (the empty-room plate the head/hands detector compares against), crop_x_limits_4k [lo, hi] (keep the crop clear
of a picture frame or edge), head_search_cols_proxy [x0, x1] (proxy columns that can hold the host's head), and
hair_top_range_out [lo, hi] (plausible top of hair on the 1080x1920 frame, a sanity check).
Hand overrides per clip: clips/wide_openings.json ({"<id>": {"force": {"E0", "E1", "kind": "C|S|H", "why"}}}).
Outputs: out/wide/clean/<name>.mp4, out/wide/<name>.mp4 (captions), titled/<name>.mp4 (with --title), .edl/.title/.captions.json.
"""

import argparse, copy, json, math, os, shutil, subprocess, sys, time
import numpy as np
import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_v2 as rv
import render_clip as rc
from render_clip import runs, frames as F
from common import POD, FPS, FPS_STR, TMP, load_manifest, cam_frame, mic_roles, person_cam, load_words, load_speech_regions, url, proxy, wide_cam, wide_side, face_stats

V2 = f'{POD}/out/closeup'
V3 = f'{POD}/out/wide'
QA = f'{V3}/qa'
WORK = f'{TMP}/v3'
PREVIEW = False                      # scripts/render.py --preview: 540x960 (reads out/closeup/preview)


def set_dirs():
    global V2, V3, QA
    V2 = f'{POD}/out/closeup' + ('/preview' if PREVIEW else '')
    V3 = f'{POD}/out/wide' + ('/preview' if PREVIEW else '')
    QA = f'{V3}/qa'


def WCFG():
    return load_manifest().get('wide_opening', {})


def WIDE():
    return wide_cam(load_manifest())


def plate_path():
    return f'{WORK}/plate_{WIDE()}.npy'
LOG = print

# ---- opening rules (brief, round 3)
OPEN_MIN, OPEN_MAX = 3.0, 4.5          # shot 0 length (s) = start of the first Guest shot
CUT_MIN, CUT_MAX = 1.5, 2.5            # listening cutaway length
SPLIT_MIN, SPLIT_MAX = 3.0, 4.0        # fallback split length
TITLE_SAFE_TOP = 270                   # Instagram safe area
TITLE_HAIR_GAP = 45                    # block bottom at least this far above the top of his hair / raised hands
HAIR_TARGET = 590                      # top of hair on the 1080x1920 frame (brief: about 580-660)
def crop_limits():                     # worked example: [0, 1000], the left artwork frame's shadow starts at x ~1024 (4K)
    return WCFG().get('crop_x_limits_4k', [0, 3840])


def name_of(clip):
    return f"{clip['id']}_{clip['slug']}"


# =============================================================== v2 state (exact reproduction of the v2 audio plan)
def load_state(clip, edits_all):
    """Re-run the v2 audio planner exactly as render_v2.render() does (same edits, same tighten loop), then check that
    every piece equals out/v2/<name>.edl.json (in-point to 1 ms, length to the frame). Nothing about the audio is
    re-decided: the v2 audio stream itself is copied at mux time; the plan is only needed for word/speaker timing."""
    man = rv.tune_looks(load_manifest())
    roles = mic_roles(man)
    cams = {'host': person_cam(man, 'host', roles), 'guest': person_cam(man, 'guest', roles)}
    words = load_words(); regions = load_speech_regions()
    edits = copy.deepcopy(edits_all.get(clip['id'], {}))
    old_log = rv.LOG; rv.LOG = lambda *a, **k: None
    try:
        for it in range(4):
            pieces, analyses = rv.plan_pieces_v2(man, roles, clip, regions, words, edits)
            rv.trim_edges_v2(pieces, analyses)
            rv.verify_edges_v2(man, pieces, analyses, words)
            tl = rv.TimelineV2(man, pieces, analyses)
            ch = rv.tighten(tl, analyses) if it < 3 else []
            if not ch: break
            for seg, kind, v in ch:
                se = edits.setdefault('segments', {}).setdefault(str(seg), {})
                if kind == 'cut': se.setdefault('cuts', []).append(list(v))
                elif kind == 'start': se['start'] = max(v, float(se.get('start', -1e9)))
                else: se['end'] = min(v, float(se.get('end', 1e9)))
    finally:
        rv.LOG = old_log
    v2 = json.load(open(f'{V2}/{name_of(clip)}.edl.json'))
    assert tl.N == v2['frames'], f'frames {tl.N} != v2 {v2["frames"]}'
    assert len(tl.p) == len(v2['pieces'])
    for p, q in zip(tl.p, v2['pieces']):
        assert p['n'] == q['frames'] and abs(p['ts'] - q['master_in']) < 1e-3, (p['ts'], q)
    ow = rv.output_words(tl, analyses)
    key = f"{clip['id']}_" + '%08x' % (abs(hash(tuple(round(p['ts'], 3) for p in pieces))) % (1 << 32))
    cache = f'{rv.WORK}/cache/guest_{key}.npz'
    if not os.path.exists(cache):
        os.makedirs(f'{WORK}/cache', exist_ok=True); cache = f'{WORK}/cache/guest_{key}.npz'
    M = rv.guest_track(man, tl, cache)
    att, react, ref, eyes = rv.guest_quality(M, tl)
    bad, nh = rv.guest_bad(tl, att, eyes, edits)
    return dict(clip=clip, name=name_of(clip), man=man, roles=roles, cams=cams, tl=tl, analyses=analyses, ow=ow,
                v2=v2, edits=edits, att=att, react=react, eyes=eyes, bad=bad, nh=nh, M=M)


def v2_shots(v2):
    """v2 shot list in frames with the exact v2 framings (crop boxes) so unchanged shots render identically."""
    K = {'host': 'R', 'guest_speaking': 'H', 'guest_cutaway': 'C', 'split': 'S'}
    out = []
    for s in v2['shots']:
        f0 = int(round(s['out_start'] * FPS))
        src = [{k: x[k] for k in ('person', 'camera', 'look', 'pos', 'crop_4k', 'face_4k')} for x in s['sources']]
        who = 'split' if s['layout'] == 'split' else ('guest' if K[s['kind']] in 'HC' else 'host')
        look = s['look'] if not (src[0]['camera'] == WIDE()) else 'wide'
        out.append({'f0': f0, 'f1': f0 + s['frames'], 'kind': K[s['kind']], 'look': (who, look), 'src': src,
                    'why': f"v2: {s['reason']}", 'v2_index': s['index']})
    return out


# =============================================================== camA: where is the top of his head / raised hands
_plate = None


def plate():
    global _plate
    if _plate is None:
        if not os.path.exists(plate_path()): make_plate()
        _plate = np.load(plate_path()).astype(np.int16)
    return _plate


def make_plate():
    """Median of wide-camera proxy frames (one per second) over wide_opening.plate_cam_time, when both chairs are empty."""
    a, b = WCFG().get('plate_cam_time') or (None, None)
    if a is None: raise SystemExit('shoot.json wide_opening.plate_cam_time [a, b] (wide camera seconds with the room empty) is needed')
    man = load_manifest(); fr = []
    for t in np.arange(a, b, 1.0):
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.3f' % t, '-i', proxy(man, WIDE()), '-frames:v', '1',
                            '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
        if len(r.stdout) == 1920 * 1080 * 3: fr.append(np.frombuffer(r.stdout, np.uint8).reshape(1080, 1920, 3))
    if len(fr) < 3: raise SystemExit('plate: could not read wide frames in plate_cam_time')
    os.makedirs(WORK, exist_ok=True)
    np.save(plate_path(), np.median(np.stack(fr), 0).astype(np.uint8))


def camA_proxy_frames(st, f0, f1):
    """camA proxy frames (1920x1080 BGR) for output frames f0..f1-1 (each piece decoded from its own in-point)."""
    man, tl = st['man'], st['tl']
    out = np.zeros((f1 - f0, 1080, 1920, 3), np.uint8)
    f = f0
    while f < f1:
        pi = tl.piece_of[f]; p = tl.p[pi]
        e = min(f1, p['f0'] + p['n'])
        k0, _ = cam_frame(man, WIDE(), tl.mt[f])
        r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.6f' % ((k0 - 0.5) / FPS), '-i', proxy(man, WIDE()),
                            '-frames:v', str(e - f), '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
        a = np.frombuffer(r.stdout, np.uint8)
        n = len(a) // (1920 * 1080 * 3)
        out[f - f0:f - f0 + n] = a[:n * 1920 * 1080 * 3].reshape(n, 1080, 1920, 3)
        if n < e - f: LOG(f'  ! camA proxy short read at frame {f}: {n}/{e - f}')
        f = e
    return out


def foreground_top(frame, x0, x1, y_lim=700):
    """Topmost proxy row (1080p) in columns x0..x1 where the frame differs from the empty-room plate (hair, hands, ...).
    Returns (row, mask) or (None, mask)."""
    d = np.abs(frame[:y_lim, x0:x1].astype(np.int16) - plate()[:y_lim, x0:x1]).max(2)
    m = (d > 22).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    rows = np.where(m.sum(1) >= 3)[0]
    return (int(rows[0]) if len(rows) else None), m


def opening_scan(st, f1):
    """Per output frame 0..f1-1: the top of anything in front of the wall above Host (hair or raised hands) in 4K px,
    over the column range of his head +- generous margin and over the whole possible crop width; plus the visual jump
    at every piece boundary (camA, his region)."""
    fr = camA_proxy_frames(st, 0, f1)
    face = face_stats(st['man'], WIDE(), wide_side(st['man'], 'host'))
    # proxy columns: the widest crop we would use (worked example 60..520: left wall/shelves .. artwork edge)
    hx0, hx1 = WCFG().get('head_search_cols_proxy', [max(0, int(face['cx_median'] / 2) - 260), min(1920, int(face['cx_median'] / 2) + 260)])
    top = np.full(f1, np.nan); top_head = np.full(f1, np.nan)
    for i in range(f1):
        r, m = foreground_top(fr[i], hx0, hx1)
        top[i] = 2 * r if r is not None else np.nan
        cx = int(face['cx_median'] / 2)
        r2, _ = foreground_top(fr[i], cx - 110, cx + 110)
        top_head[i] = 2 * r2 if r2 is not None else np.nan
    # jump size: mean abs grey diff of his region (proxy x 100..500, y 100..700) between consecutive frames
    g = fr[:, 100:700:2, 100:500:2].mean(3)
    dif = np.abs(np.diff(g, axis=0)).mean((1, 2))           # dif[i] = frame i -> i+1
    return {'top_4k': top, 'head_top_4k': top_head, 'diff': dif, 'frames': fr}


# =============================================================== opening plan
def piece_bounds(tl):
    return sorted(set(p['f0'] for p in tl.p[1:]))


def jump_info(st, scan, f1):
    """Every audio jump (piece boundary) in 0..f1: removed master time and how visible it is on the wide (frame diff at
    the boundary over the median frame-to-frame diff nearby)."""
    tl = st['tl']; out = []
    d = scan['diff']
    for b in piece_bounds(tl):
        if b >= f1 or b < 1: continue
        p0 = tl.p[tl.piece_of[b - 1]]; p1 = tl.p[tl.piece_of[b]]
        removed = p1['ts'] - (p0['ts'] + p0['n'] / FPS)
        near = np.r_[d[max(0, b - 8):b - 1], d[b:min(len(d), b + 7)]]
        base = float(np.median(near)) if len(near) else 1.0
        out.append({'frame': b, 't': round(b / FPS, 3), 'removed_s': round(removed, 3), 'seg_join': p0['seg'] != p1['seg'],
                    'diff': round(float(d[b - 1]), 2), 'base': round(base, 2), 'ratio': round(float(d[b - 1]) / max(0.3, base), 2)})
    return out


# =============================================================== the new opening
JUMP_VISIBLE_DIFF, JUMP_VISIBLE_RATIO = 3.0, 2.5     # camA frame diff at a jump that reads as a visible jump


def wide_crop(face_cx, h=1440):
    """Opening framing on camA: Host alone, top of the crop at the top of the source (all the wall above his head),
    v2 wide scale (h 1440 = 1.5x of the 4K frame). Horizontally centred on his face but the right edge stays left of
    the artwork frame's shadow (x ~1000 in 4K), so no half picture frame at the edge."""
    w = int(round(h * 9 / 16 / 2) * 2)
    lo, hi = crop_limits()
    x = min(hi - w, face_cx - 0.5 * w)
    x = int(max(lo, round(x / 2) * 2))
    return [x, 0, w, h]


def punch_crop(face_cx, hair_4k, hair_out_target, h=1200):
    """'Hide the jump' framing: the same wide source 1.2x tighter (h 1200 vs 1440), top of hair a little lower on
    screen than in the main opening framing so the title above him stays clear."""
    w = 676
    y = max(0, int(round(hair_4k - hair_out_target * h / 1920)))
    y -= y % 2
    lo, hi = crop_limits()
    x = int(max(lo, min(hi - w, round((face_cx - 0.5 * w) / 2) * 2)))
    return [x, y, w, h]


def plan_opening(st, scan, jumps, ov=None):
    """Choose E0 (end of shot 0 = start of the first Guest shot, 3.0-4.5 s), the first Guest shot and the shot-0
    framing change (if a visible jump falls inside shot 0). ov: per-clip overrides from clips/clips_v3_openings.json."""
    ov = ov or {}
    tl = st['tl']; N = tl.N
    att, react, eyes, bad = st['att'], st['react'], st['eyes'], st['bad']
    pbs = piece_bounds(tl)
    vis = [j for j in jumps if j['diff'] >= JUMP_VISIBLE_DIFF and j['ratio'] >= JUMP_VISIBLE_RATIO]
    # shot 0 ends at frame <= 107 (4.463 s); frame 108 (4.5045 s, as v2's 08c opening) only when it lands on a visible jump
    lo, hi = F(OPEN_MIN), int(math.floor(OPEN_MAX * FPS))
    if any(j['frame'] == hi + 1 for j in vis): hi += 1
    hi = min(hi, N)
    voice = (tl.who == 'guest') | tl.wh
    v2s = v2_shots(st['v2'])

    def clean_guest(a, b):
        if bad[a:a + 5].any() or bad[max(a, b - 5):b].any(): return False
        return not any(e - s0 > F(0.3) for s0, e in runs(bad[a:b]))

    def jump_cost(a, b):
        """visible jumps strictly inside a Guest shot (they jump on his face too): cost by removed time"""
        return sum(min(1.0, abs(j['removed_s'])) for j in jumps if a < j['frame'] < b)

    def shot0_cost(E0):
        """visible jumps inside shot 0, after hiding the best one with a framing change (parts >= 1.5 s)"""
        inside = [j for j in vis if 0 < j['frame'] < E0]
        best = (sum(j['diff'] for j in inside), None)
        for j in inside:
            if j['frame'] >= F(1.5) and E0 - j['frame'] >= F(1.5):
                c = sum(x['diff'] for x in inside if x is not j)
                if c < best[0]: best = (c, j['frame'])
        return best

    cands = []
    # (a) Guest speaking from v2 (clip 10): first H shot starting near the window
    for s in v2s:
        if s['kind'] == 'H' and F(2.5) <= s['f0'] <= hi + F(0.5):
            for E0 in sorted(set([s['f0']] + [b for b in pbs if s['f0'] - 4 <= b <= s['f0'] + 4])):
                if lo <= E0 <= hi:
                    c0, split_at = shot0_cost(E0)
                    sc = 5.0 - 0.3 * c0 + (1.0 if E0 in pbs else 0)
                    cands.append({'score': sc, 'E0': E0, 'E1': s['f1'], 'kind': 'H', 'split_at': split_at, 'why': 'guest speaks (v2 shot)'})
    # (b) listening cutaway
    for E0 in range(lo, hi + 1):
        c0, split_at = shot0_cost(E0)
        for L in range(F(CUT_MIN), F(CUT_MAX) + 1):
            E1 = E0 + L
            if E1 > N - F(1.5): continue
            if voice[E0:E1].any(): continue
            if not clean_guest(E0, E1): continue
            strict = bool(att[E0:E1].all())
            sc = 2.0 + float(react[E0:E1].mean()) * 1.5 + 0.8 * float(np.clip(eyes[E0:E1], 0, 1.2).mean()) \
                 - 1.5 * float((eyes[E0:E1] < 0.7).mean()) - (0 if strict else 1.0 - float(att[E0:E1].mean())) \
                 - 0.35 * c0 / 5 + 0.6 * (E0 in pbs and any(j['frame'] == E0 for j in vis)) + 0.2 * (E0 in pbs) \
                 + 0.3 * (E1 in pbs) - 0.5 * jump_cost(E0, E1) - 0.15 * abs(L - F(2.0)) / FPS
            cands.append({'score': sc, 'E0': E0, 'E1': E1, 'kind': 'C', 'split_at': split_at, 'strict': strict,
                          'react': round(float(react[E0:E1].mean()), 2), 'eyes': round(float(eyes[E0:E1].mean()), 2),
                          'why': 'listening cutaway'})
    # (d) a v2 interaction split / Guest-speaking shot that starts just after the window: start it early (<= 5 s long)
    for s in v2s:
        if s['kind'] in 'SH' and hi < s['f0'] <= hi + F(1.5) and protected(s):
            for E0 in range(lo, hi + 1):
                if s['f1'] - E0 > F(5.0) or voice[E0:s['f0']].any() and s['kind'] == 'H': continue
                if st['nh'][E0:s['f1']].any(): continue
                c0, split_at = shot0_cost(E0)
                sc = 1.8 + float(react[E0:s['f1']].mean()) - 0.35 * c0 / 5 + 0.6 * any(j['frame'] == E0 for j in vis) + 0.2 * (E0 in pbs)
                cands.append({'score': sc, 'E0': E0, 'E1': s['f1'], 'kind': s['kind'], 'split_at': split_at,
                              'why': f"v2 {s['why'][4:]} started early", 'from_v2': s['v2_index']})
    # (c) split fallback
    for E0 in range(lo, hi + 1):
        c0, split_at = shot0_cost(E0)
        for L in (F(3.5), F(3.0), F(4.0)):
            E1 = E0 + L
            if E1 > N - F(1.5) or st['nh'][E0:E1].any(): continue
            if not clean_guest(E0, E1) and not voice[E0:E1].any(): continue
            sc = 0.5 + float(react[E0:E1].mean()) - 0.35 * c0 / 5 + 0.6 * any(j['frame'] == E0 for j in vis) \
                 + 0.3 * (E1 in pbs) + 0.8 * bool(voice[E0:E1].any())
            cands.append({'score': sc, 'E0': E0, 'E1': E1, 'kind': 'S', 'split_at': split_at, 'why': 'split (no clean cutaway)'})
    if ov.get('force'):          # hand-chosen opening (looked at on frames); bypasses the automatic filters
        fz = ov['force']; E0, E1 = int(round(fz['E0'] * FPS)), int(round(fz['E1'] * FPS))
        c0, split_at = shot0_cost(E0)
        cands = [{'score': 99, 'E0': E0, 'E1': E1, 'kind': fz['kind'], 'split_at': split_at, 'why': fz.get('why', 'hand-chosen'),
                  'strict': bool(att[E0:E1].all()), 'react': round(float(react[E0:E1].mean()), 2), 'eyes': round(float(eyes[E0:E1].mean()), 2),
                  'forced': True}]
    if ov.get('E0') is not None:
        cands = [c for c in cands if c['E0'] == F(ov['E0'])] or cands
    if ov.get('kind'):
        cands = [c for c in cands if c['kind'] == ov['kind']] or cands
    if ov.get('E1') is not None:
        cands = [c for c in cands if c['E1'] == F(ov['E1'])] or cands
    cands.sort(key=lambda c: -c['score'])
    if not cands: raise RuntimeError('no opening candidate')
    best = cands[0]
    if 'split_at' in ov: best['split_at'] = F(ov['split_at']) if ov['split_at'] is not None else None
    best['alternatives'] = [{k: (round(v / FPS, 3) if k in ('E0', 'E1', 'split_at') and v is not None else v)
                             for k, v in c.items()} for c in cands[1:6]]
    best['visible_jumps'] = vis
    return best


def protected(s):
    """v2 shots tied to what is heard: Guest speaking, splits on crosstalk / Guest reacting aloud / hand hints."""
    return s['kind'] == 'H' or (s['kind'] == 'S' and any(k in s['why'] for k in ('crosstalk', 'guest reacts', 'hint')))


def build_shots(st, op, scan):
    """Full v3 shot list: [wide A (+ wide B hiding a jump)] [first Guest shot] [Host close camB ...] [v2 shots]."""
    tl, man, cams = st['tl'], st['man'], st['cams']
    N = tl.N; E0, E1 = op['E0'], op['E1']
    v2s = v2_shots(st['v2'])
    notes = []
    # ---- shot 0: wide (camA), crop at the top of the source
    face = face_stats(st['man'], WIDE(), wide_side(st['man'], 'host'))
    v2w = [x for s in v2s for x in s['src'] if x['camera'] == WIDE() and x['pos'] == 'full' and x['person'] == 'host']
    cx = float(np.median([x['face_4k'][0] for x in v2w])) if v2w else face['cx_median']
    hair4k = float(np.nanmin(scan['head_top_4k'][:E0]))
    A = wide_crop(cx)
    hairA_out = hair4k * 1920 / A[3]
    sa = op.get('split_at')
    shots = []
    srcA = {'person': 'host', 'camera': WIDE(), 'look': 'wide_open', 'pos': 'full', 'crop_4k': A, 'face_4k': [round(cx), round(face['eye_y_median']), round(face['face_w_median'])]}
    if sa:
        B = punch_crop(cx, hair4k, hairA_out + 40)
        srcB = {**srcA, 'look': 'wide_open_punch', 'crop_4k': B}
        shots.append({'f0': 0, 'f1': sa, 'kind': 'R', 'look': ('host', 'wide_open'), 'src': [srcA], 'why': 'opening (title): wide, room above head'})
        shots.append({'f0': sa, 'f1': E0, 'kind': 'R', 'look': ('host', 'wide_open_punch'), 'src': [srcB],
                      'why': f'opening (title) cont.: wide 1.2x, hides the audio jump at {sa / FPS:.2f}s'})
    else:
        shots.append({'f0': 0, 'f1': E0, 'kind': 'R', 'look': ('host', 'wide_open'), 'src': [srcA], 'why': 'opening (title): wide, room above head'})
    # ---- first Guest shot
    k = op['kind']
    if k == 'H' or op.get('from_v2') is not None:
        v = next(s for s in v2s if (s['v2_index'] == op['from_v2'] if op.get('from_v2') is not None else (s['kind'] == 'H' and s['f1'] == E1)))
        hs = {**v, 'f0': E0, 'f1': E1, 'why': f"first guest: {op['why']}", 'src': [dict(x) for x in v['src']]}
    else:
        hs = {'f0': E0, 'f1': E1, 'kind': k, 'look': ('guest', 'single') if k == 'C' else ('split', 'half'),
              'why': f"first guest: {op['why']}"}
        rc.frame_shots(man, [hs], tl, cams)
    shots.append(hs)
    # v2 Guest-speaking shots that continue straight on from the first Guest shot stay as they are (clip 10)
    for s in v2s:
        if s['f0'] == E1 and s['kind'] == 'H':
            shots.append({**s, 'src': [dict(x) for x in s['src']], 'why': s['why'] + ' (first guest block cont.)'}); E1 = s['f1']
    # ---- back on Host (close-up, camB) until the v2 plan resumes
    R = None; dropped = []
    for i, s in enumerate(v2s):
        if s['f0'] < E1 + F(1.5):
            if s['f1'] > E1 and s['kind'] in 'HCS' and s.get('v2_index') != hs.get('v2_index') and not any(x is s or x.get('v2_index') == s['v2_index'] for x in shots):
                notes.append(f"v2 shot {s['v2_index']} {s['kind']} {s['f0'] / FPS:.2f}-{s['f1'] / FPS:.2f} ({s['why']}) replaced by the new opening"
                             + (' (PROTECTED interaction shot)' if protected(s) else ''))
            continue
        if s['kind'] in 'CS' and not protected(s) and s['f0'] - E1 < F(3.0):
            dropped.append(s); continue          # too close after the first Guest shot
        R = s['f0']; break
    if R is None: R = N
    for s in v2s:
        if E1 <= s['f0'] < R and s['kind'] in 'HCS' and s not in dropped:
            if protected(s): raise RuntimeError(f"protected v2 shot {s['v2_index']} would be replaced")
            dropped.append(s)
    for s in dropped:
        notes.append(f"v2 shot {s['v2_index']} {s['kind']} {s['f0'] / FPS:.2f}-{s['f1'] / FPS:.2f} ({s['why']}) replaced by the new opening")
    nxt = next((s for s in v2s if s['f0'] == R), None)
    nxt_look = nxt['look'][1] if nxt and nxt['kind'] == 'R' else None
    first = 'single_punch' if nxt_look == 'single' else 'single'
    pcs = piece_bounds(tl); beats = tl.beats()
    rem = []
    a = E1
    while R - a > F(6.0):
        lo_, hi_ = a + F(2.5), min(a + F(5.5), R - F(2.0))
        c = [x for x in pcs if lo_ <= x <= hi_] or [x for x in beats if lo_ <= x <= hi_] or [min(max(a + F(4.0), lo_), hi_)]
        b = min(c, key=lambda x: abs(x - (a + (R - a) / 2 if R - a < F(9) else a + F(4.0))))
        rem.append((a, b)); a = b
    rem.append((a, R))
    looks = [first, 'single' if first == 'single_punch' else 'single_punch']
    if len(rem) % 2 == 0 and nxt_look == looks[(len(rem) - 1) % 2]:
        looks = looks[::-1]
    new_r = []
    for i, (a, b) in enumerate(rem):
        if b > a:
            new_r.append({'f0': a, 'f1': b, 'kind': 'R', 'look': ('host', looks[i % 2]), 'why': 'back on host close-up (v3)'})
    rc.frame_shots(man, new_r, tl, cams)
    shots += new_r
    for s in v2s:
        if s['f0'] >= R:
            shots.append({**s, 'src': [dict(x) for x in s['src']]})
    shots = fill_guest_gaps(st, shots, E1, notes)
    # sanity
    for x, y in zip(shots, shots[1:]):
        assert x['f1'] == y['f0'], (x, y)
    assert shots[0]['f0'] == 0 and shots[-1]['f1'] == N
    seen = {}
    for n in notes: seen.setdefault(n.split(' (PROTECTED')[0], n)
    notes = list(seen.values())
    return shots, {'R': R, 'notes': notes, 'hair4k_min': hair4k, 'crop_A': A, 'crop_B': shots[1]['src'][0]['crop_4k'] if sa else None}


def fill_guest_gaps(st, shots, after, notes, max_gap=11.5):
    """If dropping a v2 Guest shot left a stretch over ~12 s without Guest, put a listening cutaway (1.5-2.5 s, no
    Guest words, clean eyes/pose, no audio jump inside, >= 3 s from other Guest shots) into it. Host pieces left under
    1.5 s by the insert are absorbed by the neighbouring Host shot (its edge moves to the cutaway's edge)."""
    tl = st['tl']; N = tl.N
    att, react, eyes, bad = st['att'], st['react'], st['eyes'], st['bad']
    voice = (tl.who == 'guest') | tl.wh
    pcs = set(piece_bounds(tl))
    for _ in range(3):
        vis = np.zeros(N, bool)
        for s in shots:
            if s['kind'] in 'HCS': vis[s['f0']:s['f1']] = True
        gaps = [(a, b) for a, b in runs(~vis) if (b - a) / FPS > max_gap and a >= after]
        if not gaps: return shots
        g0, g1 = gaps[0]
        best = None
        for a in range(g0 + F(3.0), g1 - F(3.0)):
            for L in range(F(1.5), F(2.5) + 1):
                b = a + L
                if b > g1 - F(3.0): continue
                if voice[a:b].any() or bad[a:a + 5].any() or bad[b - 5:b].any(): continue
                if any(e - s0 > F(0.3) for s0, e in runs(bad[a:b])): continue
                if any(a < x < b for x in pcs): continue
                if max(a - g0, g1 - b) > F(max_gap): continue
                sc = float(react[a:b].mean()) + 0.8 * float(np.clip(eyes[a:b], 0, 1.2).mean()) + 0.5 * float(att[a:b].mean()) \
                    - 1.5 * float((eyes[a:b] < 0.7).mean()) + 0.3 * (b in pcs) + 0.2 * (a in pcs) - 0.4 * abs((a + b) / 2 - (g0 + g1) / 2) / (g1 - g0)
                if best is None or sc > best[0]: best = (sc, a, b)
        if not best:
            notes.append(f'! could not fill a {(g1 - g0) / FPS:.1f} s stretch without Guest at {g0 / FPS:.1f}s'); return shots
        _, a, b = best
        c = {'f0': a, 'f1': b, 'kind': 'C', 'look': ('guest', 'single'), 'why': 'cutaway: guest every ~10 s (v3, replaces a dropped v2 guest shot)'}
        rc.frame_shots(st['man'], [c], tl, st['cams'])
        out = []
        for s in shots:
            if s['f1'] <= a or s['f0'] >= b: out.append(s); continue
            if s['f0'] < a: out.append({**s, 'f1': a})
            if not any(x is c for x in out): out.append(c)
            if s['f1'] > b: out.append({**s, 'f0': b, 'src': [dict(x) for x in s['src']]})
        # absorb Host fragments under 1.5 s
        changed = True
        while changed:
            changed = False
            for i, s in enumerate(out):
                if s['kind'] == 'R' and s['f1'] - s['f0'] < F(1.5):
                    if i > 0 and out[i - 1]['kind'] == 'R' and out[i - 1]['f1'] == s['f0'] and s['f1'] == a:
                        out[i - 1]['f1'] = s['f1']; del out[i]; changed = True; break
                    if i + 1 < len(out) and out[i + 1]['kind'] == 'R' and s['f0'] == b:
                        out[i + 1]['f0'] = s['f0']; del out[i]; changed = True; break
        if any(s['f1'] - s['f0'] < F(1.5) for s in out if s['f0'] >= after):
            notes.append(f'! inserted cutaway {a / FPS:.2f}-{b / FPS:.2f} left a short shot')
        notes.append(f'inserted cutaway {a / FPS:.2f}-{b / FPS:.2f} s (Guest gap was {(g1 - g0) / FPS:.1f} s)')
        shots = out
    return shots


def plan_stats(shots, N):
    vis = np.zeros(N, bool)
    for s in shots:
        if s['kind'] in 'HCS': vis[s['f0']:s['f1']] = True
    gaps = [(b - a) / FPS for a, b in runs(~vis)]
    return {'shots': len(shots), 'min_shot_s': round(min((s['f1'] - s['f0']) / FPS for s in shots), 2),
            'min_shot_excl_opening_s': round(min([(s['f1'] - s['f0']) / FPS for s in shots if not s['why'].startswith('opening')] or [99]), 2),
            'longest_without_guest_s': round(max(gaps or [0]), 2),
            'guest_shots': {k: sum(s['kind'] == k for s in shots) for k in 'CSH'}}


# =============================================================== title above his head
def title_x_extent(text):
    import overlay as ov
    ov.set_title_style('wide')
    a = np.asarray(ov.title_image(text))[..., 3]
    cols = np.where(a.max(0) > 0)[0]
    return int(cols[0]), int(cols[-1]) + 1, a.shape[0]


def title_layout(st, shots, scan, E0):
    """Per frame of shot 0: top of anything in front of the wall (hair or hands) inside the title's column range, in
    1080x1920 output pixels, measured on the camA proxy (same camera frame, exactly half the 4K) against the empty-room
    plate. Title block centred between y 270 and the highest point, and never closer than 45 px to it."""
    text = st['clip']['title_hook']
    tx0, tx1, bh = title_x_extent(text)
    tops, heads = [], []
    for f in range(E0):
        s = next(x for x in shots if x['f0'] <= f < x['f1'])
        x, y, w, h = s['src'][0]['crop_4k']
        px0 = int((x + tx0 * w / 1080) / 2); px1 = int(math.ceil((x + tx1 * w / 1080) / 2))
        r, _ = foreground_top(scan['frames'][f], max(0, px0), min(1920, px1))
        tops.append((2 * r - y) * 1920 / h if r is not None else np.nan)
        hd = scan['head_top_4k'][f]
        heads.append((hd - y) * 1920 / h)
    tops = np.array(tops); heads = np.array(heads)
    if np.isnan(tops).any(): raise RuntimeError('no foreground found in some opening frames')
    top_min = float(tops.min())
    y = int(round((TITLE_SAFE_TOP + top_min) / 2 - bh / 2))
    y = min(y, int(math.floor(top_min - TITLE_HAIR_GAP - bh)))
    y = max(y, TITLE_SAFE_TOP)
    clear = top_min - (y + bh)
    ok = TITLE_SAFE_TOP <= y <= 520 and clear >= TITLE_HAIR_GAP
    # sanity: the head detector must agree with the per-frame foreground (no false 'face' far down the frame)
    hlo, hhi = WCFG().get('hair_top_range_out', [450, 760])
    if not (hlo <= heads.min() <= hhi):
        raise RuntimeError(f'implausible hair top {heads.min():.0f} on the 1080x1920 frame: check the detector')
    if not (TITLE_SAFE_TOP <= y <= 520):
        raise RuntimeError(f'title y_top {y} outside 270-520: bug')
    worst = int(np.argmin(tops))
    return {'text': text, 'y_top': y, 'frame_start': 0, 'frame_end': E0, 'block_h': bh, 'block_x': [tx0, tx1],
            'hair_top_y_min': round(float(heads.min()), 1), 'hair_top_y_median': round(float(np.median(heads)), 1),
            'anything_top_y_min': round(top_min, 1), 'anything_top_worst_frame': worst,
            'clearance_px': round(clear, 1), 'clearance_ok': bool(ok), 'frames_checked': int(E0),
            'style': 'wide', 'method': 'per frame of shot 0: topmost wide-proxy pixel that differs from the empty-room plate inside the title columns'}


# =============================================================== plan one clip (no rendering)
def overrides():
    p = f'{POD}/clips/wide_openings.json'
    return json.load(open(p)) if os.path.exists(p) else {}


def plan_clip(clip, edits_all):
    st = load_state(clip, edits_all)
    ov = overrides().get(clip['id'], {})
    scan = opening_scan(st, min(st['tl'].N, F(OPEN_MAX) + 2))
    jumps = jump_info(st, scan, F(OPEN_MAX) + 2)
    op = plan_opening(st, scan, jumps, ov)
    shots, info = build_shots(st, op, scan)
    title = title_layout(st, shots, scan, op['E0'])
    return st, scan, jumps, op, shots, info, title


def describe(st, jumps, op, shots, info, title):
    tl = st['tl']; E0, E1 = op['E0'], op['E1']
    inside = [j for j in jumps if 0 < j['frame'] < E0]
    jl = []
    for j in jumps:
        if j['frame'] > E0: continue
        v = j in op['visible_jumps']
        how = ('ends shot 0 (hidden by the cut to Guest)' if j['frame'] == E0 else
               'hidden by the wide framing change' if j['frame'] == op.get('split_at') else
               ('VISIBLE, left in (no >=1.5 s way to hide it)' if v else 'not visible (small)'))
        jl.append({**j, 'visible': v, 'handled': how})
    return {'shot0_s': round(E0 / FPS, 3), 'shot0_parts': [[round(s['f0'] / FPS, 3), round(s['f1'] / FPS, 3), s['look'][1], s['src'][0]['crop_4k']]
                                                          for s in shots if s['f1'] <= E0],
            'first_guest': {'kind': {'C': 'listening cutaway', 'S': 'split', 'H': 'guest speaking'}[op['kind']] if op['kind'] in 'CSH' else op['kind'],
                             'start_s': round(E0 / FPS, 3), 'end_s': round(E1 / FPS, 3), 'len_s': round((E1 - E0) / FPS, 3),
                             'react': op.get('react'), 'eyes': op.get('eyes'), 'attentive_all_frames': op.get('strict')},
            'jumps_in_opening': jl, 'v2_resumes_at_s': round(info['R'] / FPS, 3), 'notes': info['notes'],
            'title': {k: title[k] for k in ('y_top', 'block_h', 'hair_top_y_min', 'anything_top_y_min', 'clearance_px', 'clearance_ok')},
            'stats': plan_stats(shots, tl.N)}


def write_plan(st, op, shots, info, title, desc):
    name = st['name']; v2 = st['v2']
    os.makedirs(V3, exist_ok=True)
    names = {'R': 'host', 'H': 'guest_speaking', 'C': 'guest_cutaway', 'S': 'split'}
    tl = st['tl']
    edl = {k: v2[k] for k in ('id', 'slug', 'fps', 'duration_s', 'frames', 'mic_roles', 'cameras', 'pieces', 'words', 'edge_checks', 'audio')}
    edl.update({'engine': 'v3', 'resolution': [540, 960] if PREVIEW else [1080, 1920], 'rendered_sig': desc.get('rendered_sig'),
                'audio_source': f'{V2}/clean/{name}.mp4 (audio stream copied, not re-rendered)',
                'opening': desc, 'shots': []})
    for i, s in enumerate(shots):
        edl['shots'].append({'index': i, 'out_start': round(s['f0'] / FPS, 4), 'out_end': round(s['f1'] / FPS, 4), 'frames': s['f1'] - s['f0'],
                             'kind': names[s['kind']], 'layout': 'split' if s['look'][0] == 'split' else 'full', 'look': s['look'][1],
                             'master_start': round(float(tl.mt[s['f0']]), 4), 'master_end': round(float(tl.mt[s['f1'] - 1]) + 1 / FPS, 4),
                             'reason': s.get('why'), 'from_v2_shot': s.get('v2_index'), 'sources': s['src'], 'parts': s.get('parts', [])})
    json.dump(edl, open(f'{V3}/{name}.edl.json', 'w'), indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    json.dump(title, open(f'{V3}/{name}.title.json', 'w'), indent=1, ensure_ascii=False)
    cap = f'{V3}/{name}.captions.json'
    if not os.path.exists(cap):                                  # hand-corrected v2 text; never overwrite later edits
        shutil.copyfile(f'{V2}/{name}.captions.json', cap)
    return edl


# =============================================================== single frames (opening checks)
def render_frame(st, shots, f, tmp, preview=False):
    """One output frame exactly as the final render makes it (same render_shot path), as an RGB PIL image 1080x1920
    (4K source) or 540x960 (proxy)."""
    from PIL import Image
    s = next(x for x in shots if x['f0'] <= f < x['f1'])
    sub = {**s, 'f0': f, 'f1': f + 1, 'src': [dict(x) for x in s['src']]}
    os.makedirs(tmp, exist_ok=True)
    old = rc.LOG if hasattr(rc, 'LOG') else None
    out = rc.render_shot(st['man'], sub, st['tl'], f, tmp, preview)
    W, H = (540, 960) if preview else (1080, 1920)
    r = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', out, '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                       capture_output=True)
    os.remove(out)
    return Image.fromarray(np.frombuffer(r.stdout, np.uint8)[:W * H * 3].reshape(H, W, 3).copy())


def with_text(img, f, title, caps, show_title=True):
    """Composite title + caption exactly where/when overlay_v3 burns them (frame-based timing)."""
    import overlay as ov
    from PIL import Image
    sc = img.width / 1080
    im = img.convert('RGBA')

    def put(o, x, y):
        if sc != 1: o = o.resize((max(1, round(o.width * sc)), max(1, round(o.height * sc))), Image.LANCZOS)
        im.alpha_composite(o, (round(x * sc), round(y * sc)))
    if show_title and title and title['frame_start'] <= f < title['frame_end']:
        put(ov.title_image(title['text']), 0, title['y_top'])
    for i, c in enumerate(caps):
        if not c.get('text', '').strip(): continue
        f0 = int(np.floor(c['t0'] * FPS + 1e-6)); f1 = int(round(c['t1'] * FPS))
        if i == 0 and c['t0'] < 0.15: f0 = 0
        if f1 <= f0: f1 = f0 + 1
        if f0 <= f < f1:
            o, (x, y) = ov.caption_image(c['text']); put(o, x, y)
    return im.convert('RGB')


def opening_sheet(st, shots, op, title, dst, preview=False, extra=True):
    """Frames: 0, 1.5 s, last of shot 0, first and middle of the first Guest shot (+ the frames either side of each
    audio jump inside shot 0 when extra). Returns the list of (label, image) for the overview."""
    from PIL import Image, ImageDraw
    E0, E1 = op['E0'], op['E1']
    caps = json.load(open(f"{V2}/{st['name']}.captions.json"))
    picks = [(0, 'frame 0'), (F(1.5), '1.5 s'), (E0 - 1, 'last of shot 0'), (E0, 'first Guest'), ((E0 + E1) // 2, 'mid Guest')]
    if extra:
        for j in op['visible_jumps']:
            if 0 < j['frame'] < E0:
                picks += [(j['frame'] - 1, f"before jump {j['t']:.2f}"), (j['frame'], f"after jump {j['t']:.2f}")]
        picks.append((E1, 'after Guest'))
    tmp = f"{WORK}/frames/{st['name']}"
    tiles = []
    for f, lab in picks:
        img = with_text(render_frame(st, shots, f, tmp, preview), f, title, caps)
        tiles.append((f, lab, img))
    cw = 360; ch = 640; lab_h = 22
    cols = min(len(tiles), 7); rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (cw + 6), rows * (ch + lab_h + 6)), (25, 25, 25))
    d = ImageDraw.Draw(sheet)
    for k, (f, lab, img) in enumerate(tiles):
        x, y = (k % cols) * (cw + 6), (k // cols) * (ch + lab_h + 6)
        d.text((x + 3, y + 4), f'{lab}  f{f} {f / FPS:.2f}s', fill=(255, 220, 120))
        sheet.paste(img.resize((cw, ch), Image.LANCZOS), (x, y + lab_h))
    sheet.save(dst, quality=88)
    return tiles[:5]


def overview(rows, dst):
    from PIL import Image, ImageDraw
    cw, ch, lw = 216, 384, 150
    im = Image.new('RGB', (lw + 5 * (cw + 4), len(rows) * (ch + 4)), (20, 20, 20))
    d = ImageDraw.Draw(im)
    for r, (name, info, tiles) in enumerate(rows):
        y = r * (ch + 4)
        d.text((4, y + 6), name[:22], fill=(255, 220, 120))
        for i, line in enumerate(info): d.text((4, y + 26 + 16 * i), line, fill=(220, 220, 220))
        for k, (f, lab, img) in enumerate(tiles):
            x = lw + k * (cw + 4)
            im.paste(img.resize((cw, ch), Image.LANCZOS), (x, y))
            d.text((x + 3, y + 3), f'{lab} {f / FPS:.2f}s', fill=(255, 255, 0))
    im.save(dst, quality=85)


# =============================================================== final render
def probe_ok(p, frames=None):
    if not os.path.exists(p) or os.path.getsize(p) < 10000: return False
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-show_entries', 'stream=codec_type,nb_read_packets,width,height',
                        '-of', 'json', p], capture_output=True, text=True)
    try:
        ss = json.loads(r.stdout)['streams']
    except Exception:
        return False
    v = [s for s in ss if s['codec_type'] == 'video']; a = [s for s in ss if s['codec_type'] == 'audio']
    if not v or not a or v[0]['width'] != (540 if PREVIEW else 1080) or v[0]['height'] != (960 if PREVIEW else 1920): return False
    return frames is None or int(v[0]['nb_read_packets']) == frames


def plan_sig(shots):
    import hashlib
    return hashlib.md5(json.dumps([(s['f0'], s['f1'], [x['camera'] for x in s['src']], [x['crop_4k'] for x in s['src']])
                                   for s in shots]).encode()).hexdigest()[:10]


def render_final(st, shots, title, keep=False):
    """4K clean render of the v3 cut; audio = the v2 clean file's audio stream, copied. Shot files are cached per plan
    (engine_work/v3/render/<name>_<plan hash>/) so a restarted run only renders what is missing."""
    name, tl = st['name'], st['tl']
    sig = plan_sig(shots)
    tmp = f'{WORK}/render/{name}_{sig}'
    os.makedirs(tmp, exist_ok=True)
    files = []
    for i, s in enumerate(shots):
        bnd = [s['f0']] + [p['f0'] for p in tl.p if s['f0'] < p['f0'] < s['f1']] + [s['f1']]
        s['parts'] = []
        for j, (a, b) in enumerate(zip(bnd, bnd[1:])):
            sub = {**s, 'f0': a, 'f1': b, 'src': [dict(x) for x in s['src']]}
            idx = i * 100 + j
            out = f'{tmp}/shot_{idx:05d}.mkv'
            if os.path.exists(out) and rc.count_frames(out) == b - a:
                for x in sub['src']:
                    k, err = cam_frame(st['man'], x['camera'], tl.mt[a])
                    x.update(src_frame=k, sync_err_ms=round(err * 1000, 2), src_cam_time=round(k / FPS, 4))
            else:
                out = rc.render_shot(st['man'], sub, tl, idx, tmp, PREVIEW)
            files.append(out)
            s['parts'].append({'out_start': round(a / FPS, 4), 'frames': b - a,
                               'src_frames': {x['camera']: x['src_frame'] for x in sub['src']},
                               'sync_err_ms': {x['camera']: x['sync_err_ms'] for x in sub['src']}})
        LOG(f'   shot {i} done ({len(s["parts"])} parts)')
    os.makedirs(f'{V3}/clean', exist_ok=True)
    clean = f'{V3}/clean/{name}.mp4'; part = clean[:-4] + '.part.mp4'
    lst = f'{tmp}/concat.txt'
    open(lst, 'w').write(''.join(f"file '{f}'\n" for f in files))
    rc.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', f'{V2}/clean/{name}.mp4',
            '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-preset', 'slow', '-crf', '17', '-maxrate', '16M', '-bufsize', '32M', '-x264-params', 'keyint=48:min-keyint=12',
            '-r', FPS_STR,          # no -frames:v cap: it drops the v2 file's last AAC packet (shot files are frame-exact)
            '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
            '-c:a', 'copy', '-movflags', '+faststart', part])
    if not probe_ok(part, tl.N): raise RuntimeError(f'{part}: wrong frame count')
    os.replace(part, clean)
    if not keep: shutil.rmtree(tmp, ignore_errors=True)
    return clean


def run_clip(clip, edits_all, mode, title=False):
    t0 = time.time()
    set_dirs()
    if not os.path.exists(f'{V2}/{name_of(clip)}.edl.json'):
        raise SystemExit(f'render the closeup version of {name_of(clip)} first (same --preview/--final): the wide opening reuses it')
    st, scan, jumps, op, shots, info, title = plan_clip(clip, edits_all)
    desc = describe(st, jumps, op, shots, info, title)
    name = st['name']
    LOG(f"[{clip['id']}] {name}: shot0 {desc['shot0_s']} s, first guest {desc['first_guest']}, title {desc['title']}")
    for j in desc['jumps_in_opening']: LOG(f"   jump {j['t']:.3f}s removed {j['removed_s']:.3f}s diff {j['diff']} -> {j['handled']}")
    for n in desc['notes']: LOG('   ' + n)
    LOG(f"   stats {desc['stats']}")
    for i, s in enumerate(shots):
        LOG(f"   shot {i:2d} {s['f0'] / FPS:6.2f}-{s['f1'] / FPS:6.2f} {s['kind']} {s['look'][0]:6s} {s['look'][1]:16s} {s['why']}")
    write_plan(st, op, shots, info, title, desc)
    if mode == 'openings':
        os.makedirs(QA, exist_ok=True)
        tiles = opening_sheet(st, shots, op, title, f'{QA}/{name}_opening.jpg')
        return name, desc, tiles
    if mode == 'final':
        import overlay
        clean = f'{V3}/clean/{name}.mp4'
        sigf = f'{WORK}/done/{name}.clean.sig'
        if probe_ok(clean, st['tl'].N) and os.path.exists(sigf) and open(sigf).read().strip() == plan_sig(shots):
            LOG('  clean render of this exact plan exists and probes OK: skipping the picture render')
            prev = json.load(open(f'{WORK}/done/{name}.shots.json'))
            for s0, p0 in zip(shots, prev): s0['parts'] = p0
        else:
            clean = render_final(st, shots, title)
            os.makedirs(f'{WORK}/done', exist_ok=True)
            json.dump([s0.get('parts', []) for s0 in shots], open(f'{WORK}/done/{name}.shots.json', 'w'))
            open(sigf, 'w').write(plan_sig(shots))
        desc['rendered_sig'] = plan_sig(shots)
        write_plan(st, op, shots, info, title, desc)          # again, with the rendered parts / source frames
        overlay.overlay(clean, f'{V3}/{name}.captions.json', None, f'{V3}/{name}.mp4', PREVIEW)
        if title:
            os.makedirs(f'{V3}/titled', exist_ok=True)
            overlay.overlay(clean, f'{V3}/{name}.captions.json', f'{V3}/{name}.title.json', f'{V3}/titled/{name}.mp4', PREVIEW)
        LOG(f"  -> {V3}/{name}.mp4 (+ titled) + clean, {time.time() - t0:.0f} s wall")
    return name, desc, None


