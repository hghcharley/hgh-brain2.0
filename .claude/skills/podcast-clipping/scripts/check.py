#!/usr/bin/env python3
"""Stage (e): checks on rendered clips. render.py already runs heard + check + sheet for every clip it makes.

  python scripts/check.py --work W heard  out/closeup/clean/10_x.mp4   # recognise the whole clip and every seam window,
                                                                        # diff against the intended words -> <name>.heard.txt
  python scripts/check.py --work W check  out/closeup/clean/10_x.mp4   # loudness, true peak, silences, clicks at cuts,
                                                                        # picture/sound sync per shot, shot stats -> .check.json
  python scripts/check.py --work W edges  out/closeup/10_x.mp4         # first/last 1.5 s heard vs intended + the EDL's
                                                                        # per-segment edge checks (expected vs heard word)
  python scripts/check.py --work W sheet  out/closeup/10_x.mp4         # contact sheet: frame 0, 1.5 s, middle of each shot,
                                                                        # last frame -> <name>_sheet.jpg (use the CAPTIONED file)
  python scripts/check.py --work W faces  out/closeup/10_x.mp4         # guest face crops, 8 per second, every listening shot
  python scripts/check.py --work W eyes   out/closeup/10_x.mp4         # guest eye-openness per frame in every listening shot
  python scripts/check.py --work W finals [--opening closeup] [--id 10 ...]   # QA table over finished files
  python scripts/check.py --work W lipsync                              # camera audio + mouth motion vs mics, 3 points
The EDL is found next to the file (<name>.edl.json) or one folder up (for clean/ and titled/ files).
"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot, add_work_arg
boot(need=('scipy', 'soundfile', 'cv2', 'sherpa_onnx', 'PIL'))
import argparse, json, subprocess


def edl_for(mp4):
    base = mp4[:-4]; name = os.path.basename(base)
    for p in (base + '.edl.json', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(mp4))), name + '.edl.json')):
        if os.path.exists(p): return p, json.load(open(p))
    raise SystemExit(f'no EDL found for {mp4}')


def probe(mp4):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-show_entries',
                        'stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_packets:format=duration,size',
                        '-of', 'json', mp4], capture_output=True, text=True)
    return json.loads(r.stdout)


def edges(mp4, edl):
    import check_clip as cc
    from common import SR, asr_words, norm_word
    x = cc.out_audio(mp4); dur = len(x) / SR
    want = lambda t0, t1: ' '.join(norm_word(w['w']) for w in edl['words'] if t0 - 0.05 <= w['start'] < t1 - 0.08)
    sil = cc.silences(x, edl)
    out = {'duration_s': round(dur, 3), 'head_silence_s': sil['silence_at_head_s'], 'tail_silence_s': sil['silence_at_tail_s'],
           'max_internal_silence_s': sil['max_internal_silence_s'],
           'first_1.5s_heard': ' '.join(norm_word(w) for w, _, _ in asr_words(x[:int(1.5 * SR)])), 'first_1.5s_intended': want(0, 1.5),
           'last_1.5s_heard': ' '.join(norm_word(w) for w, _, _ in asr_words(x[int((dur - 1.5) * SR):])),
           'last_1.5s_intended': want(dur - 1.5, dur + 1),
           'segment_edges': [{k: r[k] for k in ('seg', 'edge', 'expected', 'heard', 'stepped_frames', 'ok')} for r in edl.get('edge_checks', [])]}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_work_arg(ap)
    ap.add_argument('what', choices=['heard', 'check', 'edges', 'sheet', 'faces', 'eyes', 'finals', 'lipsync'])
    ap.add_argument('mp4', nargs='?')
    ap.add_argument('--opening', default='closeup', choices=['closeup', 'wide'])
    ap.add_argument('--preview', action='store_true', help='finals: the preview folder')
    ap.add_argument('--id', action='append')
    ap.add_argument('--dst')
    a = ap.parse_args()
    import common
    if a.what == 'lipsync':
        import lipsync_check; lipsync_check.run(); return
    if a.what == 'finals':
        import check_clip as cc, render_v2 as rv, contact_sheet_v2
        d = f'{common.WORK}/out/{a.opening}' + ('/preview' if a.preview else '')
        qa = f'{d}/finals_qa'; os.makedirs(qa, exist_ok=True)
        rows = []
        for mp4 in sorted(glob.glob(f'{d}/*.mp4')):
            n = os.path.basename(mp4)[:-4]
            if a.id and n.split('_')[0] not in a.id: continue
            _, edl = edl_for(mp4)
            pr = probe(mp4); v = [s for s in pr['streams'] if s['codec_type'] == 'video'][0]
            I, TP = cc.loudness(mp4)[:2]
            rep = rv.seam_report(mp4, edl, f'{qa}/{n}.heard.txt')
            contact_sheet_v2.sheet(mp4, edl, f'{qa}/{n}_sheet.jpg')
            e = edges(mp4, edl)
            row = {'clip': n, 'duration_s': round(float(pr['format']['duration']), 3), 'frames': int(v['nb_read_packets']), 'frames_edl': edl['frames'],
                   'size_mb': round(int(pr['format']['size']) / 1e6, 1), 'video': f"{v['codec_name']} {v['width']}x{v['height']} {v['r_frame_rate']}",
                   'lufs': I, 'true_peak_dbtp': TP, 'word_match': rep['match_ratio'], 'seam_flags': len(rep['seam_flags']),
                   'shots': len(edl['shots']), **{k: e[k] for k in e if k != 'segment_edges'}}
            rows.append(row); print(json.dumps(row), flush=True)
        json.dump(rows, open(f'{qa}/summary.json', 'w'), indent=1)
        print('wrote', f'{qa}/summary.json'); return
    if not a.mp4: raise SystemExit('give the clip file')
    mp4 = os.path.abspath(a.mp4)
    p, edl = edl_for(mp4)
    base = mp4[:-4]
    if a.what == 'heard':
        import render_v2 as rv
        rep = rv.seam_report(mp4, edl, a.dst or base + '.heard.txt')
        print(open(a.dst or base + '.heard.txt').read())
        print(json.dumps({k: rep[k] for k in ('match_ratio', 'seam_flags', 'heard_words', 'expected_words')}))
    elif a.what == 'check':
        import render_v2 as rv
        res = rv.check_v2(mp4, edl, common.load_manifest(), a.dst or base + '.check.json')
        print(json.dumps({k: v for k, v in res.items() if k not in ('sync', 'edge_checks')}, indent=1))
    elif a.what == 'edges':
        print(json.dumps(edges(mp4, edl), indent=1))
    elif a.what == 'sheet':
        import contact_sheet_v2
        print(contact_sheet_v2.sheet(mp4, edl, a.dst or base + '_sheet.jpg'))
    elif a.what == 'faces':
        import guest_faces
        sys.argv = ['guest_faces', mp4] + ([a.dst] if a.dst else [])
        guest_faces.main()
    elif a.what == 'eyes':
        import guest_eyes
        sys.argv = ['guest_eyes', mp4]
        guest_eyes.main()


if __name__ == '__main__':
    main()
