"""Shared helpers for the clip engine: work dir, manifest, clocks, audio, VAD, ASR.

Everything shoot-specific comes from the work directory:
  $CLIPKIT_WORK/manifest.json   written by ingest.py (cameras, sync, looks, mic roles)
  $CLIPKIT_WORK/audio/<mic>.wav 48 kHz mono studio mics (links or converted copies, made by ingest.py)
  $CLIPKIT_WORK/transcript/     written by transcribe.py (words_host.json, words_guest.json, speech_regions.json)
Models live in $CLIPKIT_MODELS (default: <kit>/models, filled by setup.sh).
People are roles: 'host' (whose channel the clips are for) and 'guest'. Display names are in manifest['people'].
"""
import json, os, re, subprocess, functools
from fractions import Fraction
import numpy as np, soundfile as sf

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.abspath(os.environ.get('CLIPKIT_WORK', os.getcwd()))
POD = WORK                      # old name kept so ported code reads the same
MODELS = os.path.abspath(os.environ.get('CLIPKIT_MODELS', os.path.join(KIT, 'models')))
AUDIO = f'{WORK}/audio'
TR = f'{WORK}/transcript'
TMP = f'{WORK}/tmp'
SR = 48000
PEOPLE = ('host', 'guest')
YUNET = f'{MODELS}/yunet.onnx'
PARAKEET = f'{MODELS}/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8'
SILERO = f'{MODELS}/silero_vad.onnx'
MANIFEST = f'{WORK}/manifest.json'


def _fps_from_manifest():
    try:
        return json.load(open(MANIFEST))['fps']
    except Exception:
        return os.environ.get('CLIPKIT_FPS', '24000/1001')


FPS_STR = _fps_from_manifest()          # all cameras must share one frame rate; output uses it
FPS = float(Fraction(FPS_STR))


@functools.lru_cache(1)
def load_manifest():
    return json.load(open(MANIFEST))


def fresh_manifest():
    load_manifest.cache_clear()
    return load_manifest()


def proxy(man, cam):
    """1920x1080 proxy of a camera (local file)."""
    return man['cameras'][cam]['proxy']


def url(man_or_cam, cam=None, kind='src'):
    """Full-quality source of a camera: a local file, or a URL (a value ending in .url is a file holding the URL)."""
    if cam is None:                                   # old call style url(cam)
        man, cam = load_manifest(), man_or_cam
    else:
        man = man_or_cam
    s = man['cameras'][cam].get('source') or man['cameras'][cam]['proxy']
    if s.endswith('.url') and os.path.exists(s):
        return open(s).read().strip()
    return s


def source_scale(man, cam, use_source):
    """Source pixels per 4K-unit pixel. Crop boxes are kept in 3840x2160 units; proxies are 1920x1080 (0.5)."""
    if not use_source:
        return 0.5
    return man['cameras'][cam].get('source_size', [3840, 2160])[0] / 3840.0


def cam_role(man, role):
    """Camera id with a role ('wide', 'host_close', 'guest_close') or None."""
    for c, v in man['cameras'].items():
        if v.get('role') == role:
            return c
    return None


def wide_cam(man):
    return cam_role(man, 'wide')


def wide_side(man, person):
    """'left' or 'right': where a person sits in the wide shot."""
    hs = man.get('wide', {}).get('host_side', 'left')
    return hs if person == 'host' else ('right' if hs == 'left' else 'left')


def wide_look(man, person, punch=False):
    return f'wide_single_{wide_side(man, person)}' + ('_punch' if punch else '')


def face_stats(man, cam, side=None):
    return man['face_stats_4k'][cam if side is None else f'{cam}_{side}']


def name_of(man, person):
    return man.get('people', {}).get(person, {}).get('name', person)


# ---------------------------------------------------------------- clocks
def cam_time(man, cam, t):
    c = man['cameras'][cam]['sync']
    return c['offset_s'] + t * (1.0 + c['drift_ppm'] * 1e-6)


def master_time(man, cam, tc):
    c = man['cameras'][cam]['sync']
    return (tc - c['offset_s']) / (1.0 + c['drift_ppm'] * 1e-6)


def cam_frame(man, cam, t):
    """Nearest camera frame index for master time t, and the sub-frame error (s, video minus audio)."""
    tc = cam_time(man, cam, t)
    k = int(round(tc * FPS))
    return k, (k / FPS - tc)


# ---------------------------------------------------------------- mic roles
def mic_roles(man):
    """{'host': '<mic id>', 'guest': '<mic id>'} from the manifest (ingest.py copies it from shoot.json)."""
    r = man.get('mics', {}).get('roles')
    if not r or 'host' not in r or 'guest' not in r:
        raise SystemExit('manifest has no mics.roles {host, guest}: fix shoot.json and re-run ingest.py')
    return r


def person_cam(man, person, roles=None):
    """Close-up camera of a person, or None (then the engine falls back, see README 'degraded modes')."""
    return cam_role(man, f'{person}_close')


def shared_mic(man):
    """True when host and guest come from the same audio track (no per-person mic)."""
    r = mic_roles(man)
    return r['host'] == r['guest']


# ---------------------------------------------------------------- audio
def wav_path(name):
    return f'{AUDIO}/{name}.wav'


def read_wav(name, t0, t1, sr_out=SR):
    with sf.SoundFile(wav_path(name)) as f:
        sr = f.samplerate
        i0 = max(0, int(round(t0 * sr)))
        f.seek(i0)
        x = f.read(int(round((t1 - t0) * sr)), dtype='float32')
        if x.ndim > 1: x = x.mean(1)
        if i0 > int(round(t0 * sr)):
            x = np.concatenate([np.zeros(i0 - int(round(t0 * sr)), np.float32), x])
    return x


def band_energy_db(x, sr=SR, hop=0.01, lo=200, hi=4000):
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, [lo, hi], 'bandpass', fs=sr, output='sos')
    y = sosfiltfilt(sos, x)
    h = int(sr * hop)
    n = len(y) // h
    e = (y[:n * h].reshape(n, h) ** 2).mean(1)
    return 10 * np.log10(e + 1e-12)


@functools.lru_cache(1)
def _vad_session():
    import onnxruntime as ort
    o = ort.SessionOptions(); o.intra_op_num_threads = 1; o.inter_op_num_threads = 1
    return ort.InferenceSession(SILERO, o)


def silero_probs(x48, hop=0.01):
    """Silero speech probability resampled to `hop` grid. x48 at 48 kHz."""
    from scipy.signal import resample_poly
    x = resample_poly(x48, 1, 3).astype(np.float32)
    s = _vad_session()
    names = [i.name for i in s.get_inputs()]
    n = len(x) // 512
    p = np.zeros(n, np.float32)
    if names == ['x', 'h', 'c']:
        h = np.zeros((2, 1, 64), np.float32); c = np.zeros((2, 1, 64), np.float32)
        for i in range(n):
            out = s.run(None, {'x': x[i * 512:(i + 1) * 512][None], 'h': h, 'c': c})
            p[i] = out[0][0, 0]; h, c = out[1], out[2]
    else:  # v5 style
        st = np.zeros((2, 1, 128), np.float32); ctx = np.zeros(64, np.float32)
        for i in range(n):
            ch = x[i * 512:(i + 1) * 512]
            inp = np.concatenate([ctx, ch])[None]
            out = s.run(None, {'input': inp, 'state': st, 'sr': np.array(16000, np.int64)})
            p[i] = out[0][0, 0]; st = out[1]; ctx = ch[-64:]
    # each prob describes chunk i (32 ms). Map to 10 ms grid
    tgrid = np.arange(int(len(x48) / SR / hop)) * hop
    tc = (np.arange(n) * 512 + 256) / 16000
    return np.interp(tgrid, tc, p) if n else np.zeros(len(tgrid))


# ---------------------------------------------------------------- words / regions from the transcriber
def load_words():
    out = []
    for who in PEOPLE:
        p = f'{TR}/words_{who}.json'
        if os.path.exists(p):
            try:
                for w in json.load(open(p)):
                    out.append({'w': w['w'], 's': float(w['s']), 'e': float(w['e']), 'who': who})
            except Exception:
                pass
    out.sort(key=lambda w: w['s'])
    return out


def load_speech_regions():
    p = f'{TR}/speech_regions.json'
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p))
    except Exception:
        return None
    regs = []
    def add(item, who=None):
        if isinstance(item, dict):
            s = item.get('s', item.get('start')); e = item.get('e', item.get('end'))
            if s is not None and e is not None:
                regs.append((float(s), float(e), item.get('who', item.get('speaker', item.get('mic', who)))))
        elif isinstance(item, (list, tuple)) and len(item) >= 2 and all(isinstance(v, (int, float)) for v in item[:2]):
            regs.append((float(item[0]), float(item[1]), who))
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list):
                for it in v:
                    add(it, k)
    elif isinstance(d, list):
        for it in d:
            add(it)
    return regs or None


# ---------------------------------------------------------------- ASR (Parakeet via sherpa-onnx)
@functools.lru_cache(1)
def recognizer():
    import sherpa_onnx
    M = PARAKEET
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f'{M}/encoder.int8.onnx', decoder=f'{M}/decoder.int8.onnx', joiner=f'{M}/joiner.int8.onnx',
        tokens=f'{M}/tokens.txt', num_threads=2, model_type='nemo_transducer', decoding_method='greedy_search')


def asr_words(x48):
    """Recognise a short buffer (48 kHz). Returns list of (word, start, end) relative to buffer start."""
    from scipy.signal import resample_poly
    x = resample_poly(x48, 1, 3).astype(np.float32)
    # pad a little silence so the recogniser sees edges
    pad = np.zeros(int(0.3 * 16000), np.float32)
    x = np.concatenate([pad, x, pad])
    r = recognizer(); s = r.create_stream(); s.accept_waveform(16000, x); r.decode_stream(s)
    res = s.result
    toks, ts = list(res.tokens), list(res.timestamps)
    words, cur = [], None
    for tk, t in zip(toks, ts):
        t = t - 0.3
        if tk.startswith(' ') or tk.startswith('▁') or cur is None:
            if cur: words.append(cur)
            cur = [tk.strip().replace('▁', ''), t, t + 0.08]
        else:
            cur[0] += tk; cur[2] = t + 0.08
    if cur: words.append(cur)
    return [tuple(w) for w in words if w[0]]


def norm_word(w):
    return re.sub(r"[^a-z0-9']", '', w.lower())


def yunet_detector(w, h, thr=0.5):
    import cv2
    return cv2.FaceDetectorYN.create(YUNET, '', (w, h), thr)


def proxy_frames(man, cam, k0, n, vf=None, size=(1920, 1080)):
    """n consecutive proxy frames from camera frame k0 as BGR arrays (seek to the frame's mid-point)."""
    W, H = size
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-ss', '%.6f' % ((k0 - 0.5) / FPS), '-i', proxy(man, cam), '-frames:v', str(n)]
    if vf: cmd += ['-vf', vf]
    r = subprocess.run(cmd + ['-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], capture_output=True)
    a = np.frombuffer(r.stdout, np.uint8)
    m = len(a) // (W * H * 3)
    return a[:m * W * H * 3].reshape(m, H, W, 3)
