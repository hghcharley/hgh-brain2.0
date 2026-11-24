#!/usr/bin/env python3
"""Stage (d1): rebuild <name>.captions.json from a clip's EDL, without re-cutting (render.py also writes it).

  python scripts/captions.py --work W out/closeup/10_my-best-clip.edl.json
  python scripts/captions.py --work W --id 10                  # same, found by clip id (closeup, full size)
  python scripts/captions.py --work W --id 10 --print          # only print the lines

Text comes from the EDL's words (output time), cleaned to the caption style: one short line at a time, lowercase
except "AI", no end punctuation, 2-5 words (<= ~26 characters), doubles and false starts dropped.
Fixes: shoot.json captions.phrase_fixes (whole recording), then edits.json per clip: word_fixes (before line breaks),
caption_fixes (on finished lines), drop_backchannel (guest's lone "yeah"), caption_patches (replace / merge_next /
drop_into_next_once on finished lines). Edit the json by hand if needed, then run overlay.py: no re-cut.
"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot, add_work_arg
boot(need=('numpy',))
import argparse, json


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_work_arg(ap)
    ap.add_argument('edl', nargs='?', help='path to <name>.edl.json')
    ap.add_argument('--id', help='clip id instead of a path')
    ap.add_argument('--opening', default='closeup', choices=['closeup', 'wide'])
    ap.add_argument('--preview', action='store_true', help='with --id: the preview folder')
    ap.add_argument('--edits', help='default WORK/clips/edits.json')
    ap.add_argument('--print', action='store_true', help='print only, do not write')
    a = ap.parse_args()
    import common, captions_v2
    W = common.WORK
    p = a.edl
    if not p:
        d = f"{W}/out/{a.opening}" + ('/preview' if a.preview else '')
        m = glob.glob(f'{d}/{a.id}_*.edl.json')
        if not m: raise SystemExit(f'no EDL for id {a.id} in {d}')
        p = m[0]
    edl = json.load(open(p))
    ep = a.edits or f'{W}/clips/edits.json'
    e = (json.load(open(ep)) if os.path.exists(ep) else {}).get(edl['id'], {})
    caps = captions_v2.make_captions(edl, None, e.get('caption_fixes', []), e.get('word_fixes', []), e.get('drop_backchannel', False))
    caps = captions_v2.apply_patches(caps, e.get('caption_patches', {}))
    for c in caps: print(f"{c['t0']:7.2f}-{c['t1']:7.2f} {len(c['text']):2d} {c['text']}")
    if not a.print:
        dst = p.replace('.edl.json', '.captions.json')
        json.dump(caps, open(dst, 'w'), indent=1, ensure_ascii=False)
        print('wrote', dst)


if __name__ == '__main__':
    main()
