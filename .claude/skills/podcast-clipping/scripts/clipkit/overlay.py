"""Overlay pass: burn captions (and optionally a title hook) onto a clean render. No re-cut needed.
Entry point: scripts/overlay.py.

Reads <name>.captions.json ([{"t0","t1","text"}], seconds) and, if given, <name>.title.json (text, y_top, frame range).
Captions (plain style): a bold sans font at weight 700, 50 px, solid white with a soft drop shadow, no box. One line
at a time, centred, the line's middle at y 1440 (75% down the 1080x1920 frame; the caption band is y 1408-1472).
Title: black text on white rounded blocks, one per line, merged (weight 700). Two block proportions: 'closeup' (the
v2 title below the chin) and 'wide' (the v3 title above the head).
Font: never bundled. Any bold sans .ttf/.otf works. Path from --font / $CLIPKIT_FONT / shoot.json captions.font
(relative paths are read from the work dir). Last resort: /System/Library/Fonts/SFNS.ttf (SF Pro, present on a Mac).
A variable font gets its weight (and optical size) axes set by name; a static font is used as it is."""
import argparse, json, os, subprocess, shutil, tempfile, functools
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from common import POD, FPS, FPS_STR, TMP, WORK, load_manifest
DEFAULT_FONT = '/System/Library/Fonts/SFNS.ttf'
FONT = None
W, H = 1080, 1920
CAP = dict(size=50, wght=700, opsz=28, mid_y=1440, pad=16,
           text_rgba=(255, 255, 255, 255), shadow_alpha=0.55, shadow_dy=3, shadow_blur=4)
TITLES = {'closeup': dict(size=60, wght=700, opsz=28, line_h=84, pad_x=22, cap_top=14, radius=15, min_margin=60),   # v2
          'wide': dict(size=60, wght=700, opsz=28, line_h=90, pad_x=22, cap_top=22, radius=17, min_margin=60)}      # v3
TITLE = TITLES['wide']


def font_path():
    global FONT
    if FONT: return FONT
    cand = os.environ.get('CLIPKIT_FONT')
    if not cand:
        try: cand = load_manifest().get('captions', {}).get('font')
        except Exception: cand = None
    cand = cand or DEFAULT_FONT
    if not os.path.isabs(cand) and not os.path.exists(cand) and os.path.exists(os.path.join(WORK, cand)):
        cand = os.path.join(WORK, cand)                 # shoot.json paths are relative to the work dir
    if not os.path.exists(cand):
        if os.environ.get('CLIPKIT_FONT_FALLBACK') == '1':
            for f in STANDINS:
                if os.path.exists(f[600]):
                    print(f'  ! caption font {cand} missing: using the stand-in {os.path.basename(f[600])} '
                          '(previews only; widths differ from your chosen font)', flush=True)
                    FONT = f
                    return FONT
        raise SystemExit(f'caption font not found: {cand}. Pass --font /path/to/a-bold-sans.ttf, set CLIPKIT_FONT, or set '
                         'shoot.json captions.font (no font is bundled). For a rough preview only: CLIPKIT_FONT_FALLBACK=1 '
                         'uses Inter or DejaVu Sans if installed')
    FONT = cand
    return FONT


# static stand-ins (no variation axes) for previews when no caption font is set: {weight: file}
STANDINS = [{600: '/usr/share/fonts/opentype/inter/Inter-SemiBold.otf', 700: '/usr/share/fonts/opentype/inter/Inter-Bold.otf'},
            {600: '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 700: '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'}]


def set_title_style(name):
    global TITLE
    TITLE = TITLES[name]


@functools.lru_cache(8)
def font(size, wght, opsz):
    p = font_path()
    if isinstance(p, dict):                             # stand-in: a static font file per weight
        return ImageFont.truetype(p[600 if wght < 650 else 700], size)
    f = ImageFont.truetype(p, size)
    try:
        axes = f.get_variation_axes()
    except Exception:                                   # a static font: use it as it is
        return f
    names = [a['name'].decode() if isinstance(a['name'], bytes) else str(a['name']) for a in axes]
    if names == ['Width', 'Optical size', 'GRAD', 'Weight']:      # SF Pro (SFNS.ttf): the values the style was set with
        f.set_variation_by_axes([100, opsz, 400, wght])
        return f
    vals = []                                           # any other variable font: set weight and optical size by name
    for a, n in zip(axes, names):
        v = {'weight': wght, 'optical size': opsz}.get(n.lower(), a.get('default', a['minimum']))
        vals.append(min(max(v, a['minimum']), a['maximum']))
    f.set_variation_by_axes(vals)
    return f


def caption_image(text):
    """RGBA image of one caption line (white text, soft drop shadow, no box) at 1080 scale and its (x, y) on the frame."""
    from PIL import ImageFilter
    f = font(CAP['size'], CAP['wght'], CAP['opsz'])
    l, t, r, b = f.getbbox('Hg' + text, anchor='lm')
    adv = f.getlength(text)
    p = CAP['pad']
    bw, bh = int(round(adv)) + 2 * p, int(round(b - t)) + 2 * p
    x, y = (W - bw) // 2, CAP['mid_y'] - bh // 2
    m = Image.new('L', (bw, bh), 0)
    ImageDraw.Draw(m).text((p, bh // 2), text, font=f, fill=255, anchor='lm')
    sh = Image.new('L', (bw, bh), 0)
    sh.paste(m, (0, CAP['shadow_dy']))
    sh = sh.filter(ImageFilter.GaussianBlur(CAP['shadow_blur'])).point(lambda v: int(round(v * CAP['shadow_alpha'])))
    out = Image.new('RGBA', (bw, bh), (0, 0, 0, 0)); out.putalpha(sh)
    txt = Image.new('RGBA', (bw, bh), CAP['text_rgba']); txt.putalpha(m)
    return Image.alpha_composite(out, txt), (x, y)


def title_size(text):
    lines = text.split('\n')
    size = TITLE['size']
    while size > 50:
        f = font(size, TITLE['wght'], TITLE['opsz'])
        if max(f.getlength(l) for l in lines) + 2 * TITLE['pad_x'] <= W - 2 * TITLE['min_margin']:
            break
        size -= 1
    return size


def title_block_height(text, style=None):
    return (TITLES[style] if style else TITLE)['line_h'] * len(text.split('\n'))


def title_image(text):
    """Instagram 'classic' with background: black text on one white rounded block per line, blocks merged (convex
    corners rounded, concave corners filleted). Returns RGBA image (full width) and its top offset 0."""
    import cv2
    lines = text.split('\n')
    size = title_size(text)
    f = font(size, TITLE['wght'], TITLE['opsz'])
    ss = 4                                            # supersample the block shape
    lh = TITLE['line_h']
    hgt = lh * len(lines)
    mask = np.zeros((hgt * ss, W * ss), np.uint8)
    widths = [f.getlength(l) for l in lines]
    rects = []
    for i, (l, w) in enumerate(zip(lines, widths)):
        bw = w + 2 * TITLE['pad_x']
        x0 = (W - bw) / 2
        rects.append((x0, i * lh, x0 + bw, (i + 1) * lh))
    # lines of nearly equal width: make them equal (avoids tiny steps)
    for i in range(1, len(rects)):
        a, b = rects[i - 1], rects[i]
        if abs((a[2] - a[0]) - (b[2] - b[0])) < 2 * TITLE['radius']:
            wmax = max(a[2] - a[0], b[2] - b[0]); c = W / 2
            rects[i - 1] = (c - wmax / 2, a[1], c + wmax / 2, a[3]); rects[i] = (c - wmax / 2, b[1], c + wmax / 2, b[3])
    for x0, y0, x1, y1 in rects:
        mask[int(y0 * ss):int(y1 * ss), int(round(x0 * ss)):int(round(x1 * ss))] = 255
    r = TITLE['radius'] * ss
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    pad = 2 * r + 2
    big = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    big = cv2.morphologyEx(big, cv2.MORPH_CLOSE, k)   # concave corners -> fillets
    big = cv2.morphologyEx(big, cv2.MORPH_OPEN, k)    # convex corners -> rounded
    mask = big[pad:-pad, pad:-pad]
    m = Image.fromarray(mask).resize((W, hgt), Image.LANCZOS)
    img = Image.new('RGBA', (W, hgt), (255, 255, 255, 0))
    img.putalpha(m)
    tm = Image.new('L', (W, hgt), 0)
    d = ImageDraw.Draw(tm)
    cap_h = f.getbbox('H', anchor='ls')
    cap = -cap_h[1]
    for i, l in enumerate(lines):
        d.text((W / 2, i * lh + TITLE['cap_top'] + cap), l, font=f, fill=255, anchor='ms')
    black = Image.new('RGBA', (W, hgt), (0, 0, 0, 255))
    black.putalpha(tm)
    return Image.alpha_composite(img, black)


def overlay(clean, captions, title, out, preview, final_encode=None):
    caps = json.load(open(captions))
    tt = json.load(open(title)) if title and os.path.exists(title) else None
    if tt: set_title_style(tt.get('style', 'wide'))
    sc = 0.5 if preview else 1.0
    os.makedirs(TMP, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='ovl_', dir=TMP)
    items = []          # (png, x, y, f0, f1)

    def put(img, x, y, f0, f1, name):
        if sc != 1.0:
            img = img.resize((max(1, round(img.width * sc)), max(1, round(img.height * sc))), Image.LANCZOS)
        p = f'{tmp}/{name}.png'; img.save(p)
        items.append((p, round(x * sc), round(y * sc), f0, f1))
    if tt and tt.get('text'):
        put(title_image(tt['text']), 0, tt['y_top'], int(tt.get('frame_start', 0)), int(tt['frame_end']), 'title')
    for i, c in enumerate(caps):
        if not c.get('text', '').strip(): continue
        img, (x, y) = caption_image(c['text'])
        f0 = int(np.floor(c['t0'] * FPS + 1e-6)); f1 = int(round(c['t1'] * FPS))
        if i == 0 and c['t0'] < 0.15: f0 = 0               # first line is up from frame 0
        if f1 <= f0: f1 = f0 + 1
        put(img, x, y, f0, f1, f'c{i:03d}')
    args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', clean]
    for p, *_ in items: args += ['-i', p]
    fl = []; last = '0:v'
    for j, (p, x, y, f0, f1) in enumerate(items):
        o = f'v{j}'
        # frame f has pts f/FPS: show on frames f0..f1-1
        fl.append(f"[{last}][{j + 1}:v]overlay=x={x}:y={y}:eof_action=repeat:"
                  f"enable='gte(t,{(f0 - 0.5) / FPS:.5f})*lt(t,{(f1 - 0.5) / FPS:.5f})'[{o}]")
        last = o
    venc = ['-c:v', 'libx264', '-profile:v', 'high', '-pix_fmt', 'yuv420p']
    venc += (['-preset', 'veryfast', '-crf', '20'] if preview else
             ['-preset', 'slow', '-crf', '17', '-maxrate', '16M', '-bufsize', '32M', '-x264-params', 'keyint=48:min-keyint=12'])
    if not items:
        shutil.copy(clean, out); shutil.rmtree(tmp, ignore_errors=True); return out
    script = f'{tmp}/graph.txt'
    open(script, 'w').write(';\n'.join(fl))
    part = out[:-4] + '.part.mp4'                        # written aside, renamed when complete (resumable runs)
    cmd = args + ['-filter_complex_script', script, '-map', f'[{last}]', '-map', '0:a', *venc, '-r', FPS_STR,
                  '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
                  '-c:a', 'copy', '-movflags', '+faststart', part]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    os.replace(part, out)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def test_frame(dst, ref_png=None):
    """Caption 'it designs like apple now' drawn alone (and next to a reference frame, if given) for a size check."""
    img, (x, y) = caption_image('it designs like apple now')
    b = Image.new('RGB', (W, H), (40, 60, 80)); b.paste(img, (x, y), img)
    if ref_png:
        ref = Image.open(ref_png).convert('RGB').resize((W, H), Image.LANCZOS)
        both = Image.new('RGB', (680, 250), (0, 0, 0)); both.paste(ref.crop((200, 1380, 880, 1500)), (0, 0))
        both.paste(b.crop((200, 1380, 880, 1500)), (0, 128)); both.resize((1360, 500), Image.NEAREST).save(dst)
    else:
        b.save(dst)
    print('caption area', x, y, x + img.width, y + img.height)
