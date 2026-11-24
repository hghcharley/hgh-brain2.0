#!/usr/bin/env python3
"""Stage (b): transcribe each mic to word timings, decide who said each word, write a readable transcript.

  python scripts/transcribe.py --work W                      # whole recording -> W/transcript/
  python scripts/transcribe.py --work W --peek 150           # first 150 s of each mic, printed: check whose mic is whose
  python scripts/transcribe.py --work W --range 2850 3030 --out W/transcript_test   # one stretch (testing)

Needs ingest.py first (audio/ and work/a16/). Recogniser: NVIDIA NeMo Parakeet TDT 0.6B v2 (English), int8, run by
sherpa-onnx on the CPU, with Silero VAD to cut the audio into pieces (max 15 s).
Per mic it recognises everything, then (two mics) keeps each word on the mic where it rises well above the local bleed
level, drops duplicates heard on both mics, restores words dropped by a timing slip, finds speech regions from energy,
re-recognises own-voice stretches that got no words, trims late word ends, applies shoot.json transcript.fixes.
One shared mic (host and guest on one track): no attribution is possible, every word is labelled host.
Writes: words_host.json, words_guest.json ([{"w","s","e"}] master seconds), speech_regions.json, transcript.md.
Time: about 10 minutes per mic-hour on 4 CPUs (both mics run in parallel, 2 threads each).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot, add_work_arg, KIT
boot(need=('scipy', 'soundfile', 'sherpa_onnx'))
import argparse, json, subprocess, time

WORK = os.environ.get('CLIPKIT_WORK', '')
TX = os.path.join(KIT, 'clipkit', 'tx')


def step(script, cwd, env, *args):
    t = time.time()
    r = subprocess.run([sys.executable, os.path.join(TX, script), *map(str, args)], cwd=cwd, env=env, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise SystemExit(f'{script} failed:\n{out[-2000:]}')
    print(f'  {script} {" ".join(map(str, args))} ({time.time() - t:.0f} s) ' + (out.splitlines()[0][:150] if out else ''), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_work_arg(ap)
    ap.add_argument('--range', nargs=2, type=float, metavar=('T0', 'T1'), help='only this stretch of the master clock')
    ap.add_argument('--out', help='output folder (default WORK/transcript)')
    ap.add_argument('--peek', type=float, help='recognise the first N seconds of each mic and print it, nothing else')
    ap.add_argument('--threads', type=int, default=2, help='recogniser threads per mic (default 2; mics run in parallel)')
    a = ap.parse_args()
    man = json.load(open(f'{WORK}/manifest.json'))
    cfg = json.load(open(f'{WORK}/shoot.json')) if os.path.exists(f'{WORK}/shoot.json') else {}
    roles = man['mics']['roles']
    shared = roles['host'] == roles['guest']
    tag = 'peek' if a.peek else ('tx_%d_%d' % tuple(a.range) if a.range else 'tx')
    txd = f'{WORK}/work/{tag}'; os.makedirs(txd, exist_ok=True)
    out = os.path.abspath(a.out or f'{WORK}/transcript')
    tc = cfg.get('transcript', {})
    env = dict(os.environ, CLIPKIT_TX_OUT=out, CLIPKIT_TX_IGNORE_END=str(tc.get('ignore_until_s', 0)),
               CLIPKIT_TX_FIXES=json.dumps(tc.get('fixes', [])), CLIPKIT_TX_TITLE=man.get('title') or 'Transcript',
               CLIPKIT_TX_NAMES=json.dumps({p: v.get('name', p) for p, v in man.get('people', {}).items()}))
    if a.range: env['CLIPKIT_TX_RANGE'] = '%s,%s' % tuple(a.range)
    people = ['host'] if shared else ['host', 'guest']
    for p in people:
        dst = f'{txd}/{p}.16k.wav'
        if os.path.lexists(dst): os.remove(dst)
        os.symlink(f'{WORK}/work/a16/{roles[p]}.wav', dst)
    rng = ([0, a.peek] if a.peek else list(a.range)) if (a.peek or a.range) else []
    t = time.time()
    procs = [subprocess.Popen([sys.executable, os.path.join(TX, 'asr.py'), f'{p}.16k.wav', f'full_{p}.json', str(a.threads), *map(str, rng)],
                              cwd=txd, env=env) for p in people]
    if any(p.wait() for p in procs): raise SystemExit('asr.py failed')
    print(f'  recognition done in {time.time() - t:.0f} s', flush=True)
    if a.peek:
        for p in people:
            ws = json.load(open(f'{txd}/full_{p}.json'))['words']
            print(f'\n{p} mic ({roles[p]}), first {a.peek:.0f} s:\n  ' + ' '.join(w['w'] for w in ws))
        return
    if shared:
        W = json.load(open(f'{txd}/full_host.json'))
        json.dump({'host': W['words'], 'guest': []}, open(f'{txd}/assigned_trim.json', 'w'))
        json.dump({'host': W['pieces'], 'guest': [], 'wordless_host': [], 'wordless_guest': []}, open(f'{txd}/regions_raw.json', 'w'))
        step('finalize.py', txd, env)
    else:
        step('env.py', txd, env)
        step('attribute2.py', txd, env)
        step('dedupe.py', txd, env)
        step('restore.py', txd, env)
        if os.path.exists(f'{txd}/recovered.json'): os.remove(f'{txd}/recovered.json')
        step('regions.py', txd, env); step('gaps.py', txd, env, 0.3)
        step('recover.py', txd, env)
        step('regions.py', txd, env); step('gaps.py', txd, env, 0.3)
        step('finalize.py', txd, env)
    print(f'wrote {out}/words_host.json, words_guest.json, speech_regions.json, transcript.md ({time.time() - t:.0f} s)')


if __name__ == '__main__':
    main()
