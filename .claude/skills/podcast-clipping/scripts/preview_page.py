#!/usr/bin/env python3
"""Stage (g): a review page for the host: small 540x960 copies with posters, a version switch, a song line.

  python scripts/preview_page.py --spec page.json --out W/preview_page

page.json (paths relative to the spec file; every key except "clips" is optional):
  {"title": "Guest name clips",
   "intro": "Tap any clip to play it. The switch changes how every clip opens.",
   "footer": "These are small preview copies so they load fast.\\nThe full quality files are in the shared folder.",
   "modes": [{"key": "c", "label": "Close-up", "legend": "Opens close on your face. Captions only, no title hook."},
             {"key": "m", "label": "Music", "legend": "...", "song": true},
             {"key": "t", "label": "Wide + title", "legend": "...", "title": true}],
   "clips": [{"id": "10", "hook": "the one thing most people get wrong", "label": "10 · new ending",
              "song": "Song title · Artist",
              "files": {"c": "../out/closeup/10_my-best-clip.mp4", "m": "music/10.mp4"}}],
   "sections": [{"title": "Music level test", "legend": "...", "clips": [{"id": "m11a", "hook": "...", "file": "m11a.mp4"}]}]}
The first mode is the default. "song": true on a mode shows each clip's "Song: ..." line; "title": true shows the
hook text at full strength. A clip with no file for the current mode shows its first available one.
Each file becomes media/<mode><id>.v<N>.mp4 + .jpg with these fixed settings (small, fast on a phone):
  video  -vf scale=540:960:flags=lanczos -c:v libx264 -preset medium -crf 27 -profile:v high -pix_fmt yuv420p -g 48
         -c:a aac -b:a 128k -movflags +faststart
  poster -ss 0.6 -frames:v 1 -vf scale=432:768 -q:v 5
Re-running is incremental: unchanged sources are skipped (media/index.json keeps size+mtime+hash). A source that
CHANGED gets the next version number, so browsers never play a cached old copy; the old copy is removed.
Writes OUT/index.html (self-contained: the data is inlined; videos load from OUT/media/).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot, KIT
boot(need_work=False, need=())
import argparse, hashlib, json, re, subprocess, html

VIDEO = ['-vf', 'scale=540:960:flags=lanczos', '-c:v', 'libx264', '-preset', 'medium', '-crf', '27', '-profile:v', 'high',
         '-pix_fmt', 'yuv420p', '-g', '48', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart']
POSTER = ['-ss', '0.6', '-frames:v', '1', '-vf', 'scale=432:768', '-q:v', '5']


def sha(p):
    h = hashlib.sha1()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()[:16]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: raise SystemExit(' '.join(cmd[:6]) + '\n' + r.stderr[-800:])


def duration(p):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', p], capture_output=True, text=True)
    return float(r.stdout.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--template', default=os.path.join(KIT, 'templates', 'preview_page.html'))
    a = ap.parse_args()
    spec = json.load(open(a.spec)); base = os.path.dirname(os.path.abspath(a.spec))
    out = os.path.abspath(a.out); md = f'{out}/media'; os.makedirs(md, exist_ok=True)
    ip = f'{md}/index.json'
    idx = json.load(open(ip)) if os.path.exists(ip) else {}

    def safe(s): return re.sub(r'[^A-Za-z0-9_-]', '', s)

    def make(key, src):
        """key -> media files for src (versioned). Returns {'mp4','jpg'} relative to OUT, plus the duration."""
        src = src if os.path.isabs(src) else os.path.join(base, src)
        if not os.path.exists(src): raise SystemExit(f'missing file: {src}')
        st = os.stat(src); e = idx.get(key)
        quick = [st.st_size, int(st.st_mtime)]
        if e and e['quick'] == quick and os.path.exists(f"{out}/{e['mp4']}"):
            return e
        h = sha(src)
        if e and e['hash'] == h and os.path.exists(f"{out}/{e['mp4']}"):
            e['quick'] = quick; return e
        ver = (e['version'] + 1) if e else 1
        name = f'{safe(key)}.v{ver}'
        mp4, jpg = f'media/{name}.mp4', f'media/{name}.jpg'
        print(f'  {key}: {os.path.basename(src)} -> {mp4}', flush=True)
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', src, *VIDEO, f'{out}/{mp4}'])
        run(['ffmpeg', '-nostdin', '-v', 'error', '-y', *POSTER[:2], '-i', src, *POSTER[2:], f'{out}/{jpg}'])
        if e:                                         # a replaced file: drop the old copy (its name is never reused)
            for k in ('mp4', 'jpg'):
                try: os.remove(f"{out}/{e[k]}")
                except OSError: pass
        e = {'src': src, 'quick': quick, 'hash': h, 'version': ver, 'mp4': mp4, 'jpg': jpg, 'len': round(duration(f'{out}/{mp4}'))}
        idx[key] = e
        json.dump(idx, open(ip, 'w'), indent=1)
        return e

    data = {k: spec[k] for k in ('title', 'intro', 'footer', 'storage_key') if k in spec}
    data['modes'] = spec.get('modes') or [{'key': 'c', 'label': 'Clips', 'legend': ''}]
    data['clips'] = []
    for c in spec['clips']:
        files, ln = {}, None
        for m, f in c['files'].items():
            e = make(f'{m}{c["id"]}', f)
            files[m] = {'mp4': e['mp4'], 'jpg': e['jpg']}; ln = ln or e['len']
        data['clips'].append({**{k: v for k, v in c.items() if k != 'files'}, 'files': files, 'len': c.get('len', ln)})
    data['sections'] = []
    for s in spec.get('sections', []):
        cl = []
        for c in s['clips']:
            e = make(f'x{c["id"]}', c['file'])
            cl.append({**{k: v for k, v in c.items() if k != 'file'}, 'file': {'mp4': e['mp4'], 'jpg': e['jpg']}, 'len': c.get('len', e['len'])})
        data['sections'].append({**s, 'clips': cl})
    t = open(a.template).read()
    blob = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    page = t.replace('{{TITLE}}', html.escape(spec.get('title', 'Clip previews'))).replace('{{DATA}}', blob)
    open(f'{out}/index.html', 'w').write(page)
    print(f'wrote {out}/index.html ({len(data["clips"])} clips, {sum(len(c["files"]) for c in data["clips"])} files)')


if __name__ == '__main__':
    main()
