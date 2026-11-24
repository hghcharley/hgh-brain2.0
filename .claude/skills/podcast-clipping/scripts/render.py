#!/usr/bin/env python3
"""Stage (c): render clips from clips.json: clean cut with the multi-camera shot plan, then captions burned in.

  python scripts/render.py --work W --id 10 --plan-only            # print the shot plan, render nothing (seconds)
  python scripts/render.py --work W --id 10 --preview              # 540x960 from the proxies (fast check)
  python scripts/render.py --work W --all --final                  # 1080x1920 from the full-quality sources
  python scripts/render.py --work W --id 10 --final --source proxy # 1080x1920 but from the proxies (no source access)
  python scripts/render.py --work W --id 10 --final --title        # also titled/<name>.mp4 with the title hook
  python scripts/render.py --work W --id 10 --final --opening wide # the v3 variant (see below)
  python scripts/render.py --work W --all --final --skip-done      # resume after a restart: skip finished clips

Openings:
  closeup (default, the recommended style): the clip opens close on the host's face (render_v2.py).
  wide (optional variant): shot 0 is the host alone from the wide camera with room above the head, the first guest
       shot starts 3.0-4.5 s in, then the close-up plan resumes. It REUSES the closeup render of the same clip
       (its audio stream is copied and its captions file reused), so render the closeup version first.
       Needs wide_opening settings in shoot.json (see README).
Reads W/clips/clips.json (or --clips) and W/clips/edits.json (hand edits per clip id, optional).
Writes W/out/<opening>/[preview/]: clean/<name>.mp4, <name>.mp4 (captions), <name>.edl.json, .captions.json,
.heard.txt, .check.json, _sheet.jpg (+ titled/<name>.mp4 and .title.json with --title).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot, add_work_arg
boot(need=('scipy', 'soundfile', 'cv2', 'sherpa_onnx', 'onnxruntime', 'PIL'))
import argparse, json, subprocess


def done(path, frames=None):
    if not os.path.exists(path) or os.path.getsize(path) < 10000: return False
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_packets',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    try: n = int(r.stdout.strip())
    except ValueError: return False
    return frames is None or n == frames


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_work_arg(ap)
    ap.add_argument('--clips', help='clip list (default WORK/clips/clips.json)')
    ap.add_argument('--edits', help='hand edits (default WORK/clips/edits.json)')
    ap.add_argument('--id', action='append', help='clip id (repeat for several)')
    ap.add_argument('--all', action='store_true')
    q = ap.add_mutually_exclusive_group()
    q.add_argument('--preview', action='store_true', help='540x960 output (default source: proxies)')
    q.add_argument('--final', action='store_true', help='1080x1920 output (default source: originals)')
    ap.add_argument('--source', choices=['proxy', 'original'], help='picture source (default: proxy for --preview, original for --final)')
    ap.add_argument('--opening', choices=['closeup', 'wide'], default='closeup')
    ap.add_argument('--title', action='store_true', help='also burn the title hook (titled/<name>.mp4). Off by default')
    ap.add_argument('--plan-only', action='store_true', help='plan and print the shots; render nothing')
    ap.add_argument('--no-overlay', action='store_true', help='stop after the clean render + captions.json (burn later with overlay.py)')
    ap.add_argument('--skip-done', action='store_true', help='skip clips whose captioned file exists and probes OK')
    ap.add_argument('--keep-temp', action='store_true')
    ap.add_argument('--font', help='caption font file, any bold sans .ttf/.otf (default $CLIPKIT_FONT, then shoot.json captions.font)')
    a = ap.parse_args()
    if not (a.preview or a.final or a.plan_only):
        raise SystemExit('choose --preview, --final or --plan-only')
    if a.font: os.environ['CLIPKIT_FONT'] = os.path.abspath(a.font)
    import common, render_clip as rc, render_v2 as rv
    W = common.WORK
    rc.USE_SOURCE = (a.source or ('original' if a.final else 'proxy')) == 'original'
    rv.TITLE = a.title
    clips = json.load(open(a.clips or f'{W}/clips/clips.json'))
    ep = a.edits or f'{W}/clips/edits.json'
    edits = json.load(open(ep)) if os.path.exists(ep) else {}
    sel = clips if a.all else [c for c in clips if c['id'] in (a.id or [])]
    if not sel: raise SystemExit('no clip selected (use --id or --all)')
    if not a.plan_only:
        import overlay; overlay.font_path()          # fail early if the caption font is missing
    preview = bool(a.preview)
    for c in sel:
        name = f"{c['id']}_{c['slug']}"
        if a.opening == 'closeup':
            out = f"{rv.V2}{'/preview' if preview else ''}/{name}.mp4"
            if a.skip_done and done(out):
                print(f'skip {name}: {out} exists and probes OK', flush=True); continue
            rv.render(c, preview, edits, a.keep_temp, a.plan_only, overlay_pass=not a.no_overlay)
        else:
            import render_v3 as r3
            r3.PREVIEW = preview
            mode = 'plan' if a.plan_only else 'final'
            out = f"{r3.V3}{'/preview' if preview else ''}/{name}.mp4"
            if a.skip_done and done(out):
                print(f'skip {name}: {out} exists and probes OK', flush=True); continue
            r3.run_clip(c, edits, mode, title=a.title)


if __name__ == '__main__':
    main()
