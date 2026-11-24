#!/usr/bin/env python3
"""Stage (d2): burn captions (and optionally the title hook) onto a clean render. No re-cut.

  python scripts/overlay.py --work W --id 10                    # out/closeup/clean/<name>.mp4 -> out/closeup/<name>.mp4
  python scripts/overlay.py --work W --id 10 --title            # also titled/<name>.mp4 (needs <name>.title.json)
  python scripts/overlay.py --work W --all --preview            # the 540x960 previews
  python scripts/overlay.py --work W --test-frame /tmp/cap.png [--ref reference.png]   # one caption, to check size

Font: any bold sans font file (.ttf or .otf; a variable font is set to weight 700).
Not bundled: pass --font, set CLIPKIT_FONT, or set shoot.json captions.font.
"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot, add_work_arg
boot(need=('numpy', 'PIL', 'cv2'))
import argparse, json


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_work_arg(ap)
    ap.add_argument('--id', action='append'); ap.add_argument('--all', action='store_true')
    ap.add_argument('--opening', default='closeup', choices=['closeup', 'wide'])
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--title', action='store_true', help='also make titled/<name>.mp4 from <name>.title.json')
    ap.add_argument('--font', help='caption font file (.ttf/.otf)'); ap.add_argument('--test-frame'); ap.add_argument('--ref')
    a = ap.parse_args()
    if a.font: os.environ['CLIPKIT_FONT'] = os.path.abspath(a.font)
    import common, overlay
    if a.test_frame:
        return overlay.test_frame(a.test_frame, a.ref)
    d = f"{common.WORK}/out/{a.opening}" + ('/preview' if a.preview else '')
    names = sorted(os.path.basename(p)[:-4] for p in glob.glob(f'{d}/clean/*.mp4'))
    sel = names if a.all else [n for n in names if n.split('_')[0] in (a.id or [])]
    if not sel: raise SystemExit(f'no clean renders selected in {d}/clean')
    for n in sel:
        print(overlay.overlay(f'{d}/clean/{n}.mp4', f'{d}/{n}.captions.json', None, f'{d}/{n}.mp4', a.preview))
        if a.title:
            os.makedirs(f'{d}/titled', exist_ok=True)
            print(overlay.overlay(f'{d}/clean/{n}.mp4', f'{d}/{n}.captions.json', f'{d}/{n}.title.json', f'{d}/titled/{n}.mp4', a.preview))


if __name__ == '__main__':
    main()
