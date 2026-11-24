"""Caption text + timing from an EDL's words (SPEC_V2 section 3). Output: [{"t0","t1","text"}] in clip seconds.
Entry point: scripts/captions.py (rebuild a captions.json from an existing EDL without re-cutting).
Shoot-specific phrase fixes come from manifest['captions']['phrase_fixes'] (shoot.json), per-clip fixes from edits.json."""
import json, re, sys, os
from common import FPS, load_manifest
MAX_CHARS, MAX_WORDS = 28, 6          # prefer <= 26; up to 28 when it buys a clean break
SUBJ = {'i', 'you', 'we', 'they', 'he', 'she'}
CONJ = {'and', 'but', 'so', 'because', 'cause', 'then'}
WEAK_END = {'the', 'a', 'an', 'to', 'of', 'and', 'in', 'on', 'my', 'your', 'their', 'with', 'for', 'at', 'that', 'is',
            'are', 'was', 'i', 'it', 'but', 'so', 'or', 'as', 'if', 'how', 'what', 'this', 'these', 'be', 'can', 'just',
            'they', 'we', 'you', 'he', 'she', 'than', 'from', 'about', 'into', 'by', 'very', 'really', 'all', 'had', 'have', 'has', 'were', 'when', 'where', 'because', 'like', 'would', 'will', 'don\'t', 'not', 'no', 'more', 'most', 'some', 'every', 'each', 'one', 'our', 'his', 'her', 'its', 'who', 'which',
            "it's", "that's", "i'm", "you're", "we're", "they're", "there's", "he's", "she's", "i'll", "you'll", "it'll",
            "gonna", "could", "should", "might", "must", "then", "little", "two", "three", "four", "five", "six", "ten", "don't", "doesn't", "can't", "didn't", "i've", "you've", "we've"}

# phrase fixes on lowercased word sequences: (match, replacement). Generic number formatting lives here; anything
# specific to one shoot (misheard names, "951" -> "9:51") goes in shoot.json captions.phrase_fixes, which is checked
# first. A ',,' at the end of a replacement word shows a comma ("20,, 30" -> "20, 30").
DEFAULT_FIXES = [
    (['two', 'p.m'], ['2pm']), (['two', 'pm'], ['2pm']), (['a', 'hundred'], ['100']),
    (['thirty'], ['30']), (['twenty'], ['20']),
    (['20-30'], ['20,,', '30']), (['2030'], ['20,,', '30']), (['20', '30'], ['20,,', '30']),
]


def phrase_fixes():
    try:
        extra = load_manifest().get('captions', {}).get('phrase_fixes', [])
    except Exception:
        extra = []
    return [(list(a), list(b)) for a, b in extra] + DEFAULT_FIXES


def clean_token(w):
    """lowercase except AI; keep apostrophes, $, %, digits (with their . , :); strip other punctuation."""
    t = w.strip()
    t = re.sub(r'[“”"()\[\]]', '', t)
    t = re.sub(r'^[.,!?;:]+|[.,!?;:]+$', '', t)                 # leading/trailing punctuation only
    t = re.sub(r'[,;!?]+(?=\D)', '', t)                          # inner commas etc. not inside a number
    low = t.lower()
    if low in ('ai', "ai's"):
        return 'AI' + low[2:]
    return low


def apply_word_fixes(toks, word_fixes):
    """Token-level fixes, applied BEFORE chunking so line breaks respect them. Each fix: [old words, new words] or
    [old, new, who]. Matching is on the cleaned lowercase words (punctuation ignored). In the new words a trailing ','
    or '.' marks a clause/sentence end (used for line breaks, not shown); ',,' shows a comma ('20,, 30' -> '20, 30').
    An empty new string deletes the words. A fix whose new words are already there is skipped (idempotent)."""
    for fx in word_fixes:
        old = fx[0].lower().split(); new = fx[1].split(); who = fx[2] if len(fx) > 2 else None
        i = 0; out = []
        while i < len(toks):
            seq = [x['t'].rstrip(',').lower() for x in toks[i:i + len(old)]]
            newt = [re.sub(r'[,.]+$', '', w).lower() for w in new]
            have = [x['t'].rstrip(',').lower() for x in toks[i:i + len(new)]]
            grown = len(new) > len(old) and have == newt          # a growing fix already satisfied
            if old and seq == old and not grown and (seq != newt or len(new) != len(old) or new != old):
                grp = toks[i:i + len(old)]
                for k, w in enumerate(new):
                    g = grp[min(k, len(grp) - 1)]
                    out.append({**g, 't': re.sub(r'[,.]+$', '', w) + (',' if w.endswith(',,') else ''),
                                'start': g['start'] if k < len(grp) else grp[-1]['start'] + 0.01 * (k - len(grp) + 1),
                                'who': who or g['who'], 'comma': w.endswith(','), 'stop': w.endswith('.')})
                i += len(old)
            else:
                out.append(toks[i]); i += 1
        toks = out
    return toks


def make_captions(edl, clip=None, fixes=(), word_fixes=(), drop_backchannel=False):
    ws = edl['words']
    dur = edl['duration_s']
    # segment ends in output time (last word of each segment -> caption must end within 0.15 s)
    pieces = edl['pieces']
    seg_end = {}
    for p in pieces:
        seg_end[p['segment']] = max(seg_end.get(p['segment'], 0), p['out_end'])
    # drop the secondary talker's words that overlap the other talker (one caption line at a time)
    keep = []
    for w in ws:
        s, e = w['start'], min(w['end'], w['start'] + 0.6)
        clash = [v for v in ws if v['who'] != w['who'] and v['start'] < e and min(v['end'], v['start'] + 0.6) > s]
        if clash and w['who'] == 'guest' and any(v['who'] == 'host' for v in clash):
            # Guest over Host: drop unless Guest's run continues on alone (then Host's tail yields)
            continue
        keep.append(w)
    toks = []
    for w in keep:
        raw = w['w']
        toks.append({'t': clean_token(raw), 'raw': raw, 'start': w['start'], 'end': w['end'], 'who': w['who'], 'seg': w['seg'],
                     'stop': bool(re.search(r'[.?!]["”]?$', raw)), 'comma': raw.rstrip().endswith(',')})
    toks = [t for t in toks if t['t'] and t['t'] not in ('uh', 'um', 'uh-huh')]
    # false starts / doubles: "you you" -> "you", "that's that's" -> "that's", "could could" -> "could"
    out = []
    for t in toks:
        if out and out[-1]['t'] == t['t'] and out[-1]['who'] == t['who'] and t['start'] - out[-1]['start'] < 0.6 \
                and t['t'] not in ('9:50',):
            out[-1]['stop'] = t['stop']; out[-1]['comma'] = t['comma']; out[-1]['end'] = t['end']
            continue
        out.append(t)
    toks = out
    # phrase fixes
    i = 0; out = []
    FIXES = phrase_fixes()
    while i < len(toks):
        hit = None
        for pat, rep in FIXES:
            seq = [x['t'].strip(',') for x in toks[i:i + len(pat)]]
            if seq == pat:
                hit = (pat, rep); break
        if hit:
            pat, rep = hit
            grp = toks[i:i + len(pat)]
            n = len(rep)
            for k, r in enumerate(rep):
                g = grp[min(k, len(grp) - 1)]
                comma = r.endswith(',') and not r.endswith(',,')
                out.append({**g, 't': r[:-1] if r.endswith(',,') else r.rstrip(','), 'start': grp[0]['start'] if k == 0 else g['start'],
                            'stop': grp[-1]['stop'] if k == n - 1 else False, 'comma': comma or (grp[-1]['comma'] if k == n - 1 else False)})
            i += len(pat)
        else:
            out.append(toks[i]); i += 1
    toks = out
    if drop_backchannel:      # Guest's lone 'yeah' / 'yes' between Host's lines: heard, not captioned
        keep2 = []
        for k, t in enumerate(toks):
            prv = toks[k - 1] if k else None; nxt = toks[k + 1] if k + 1 < len(toks) else None
            lone = (not prv or prv['who'] != t['who'] or t['start'] - prv['end'] > 0.3) and \
                   (not nxt or nxt['who'] != t['who'] or nxt['start'] - t['end'] > 0.3)
            if t['who'] == 'guest' and lone and t['t'] in ('yeah', 'yes', 'yep', 'mm', 'mhm'): continue
            keep2.append(t)
        toks = keep2
    toks = apply_word_fixes(toks, word_fixes)
    # chunking: split into blocks (sentence end, talker change, segment change, pause), then the best line breaks
    # inside each block by dynamic programming (2-5 words, <= 26 chars, prefer breaks at commas, avoid weak line ends
    # and single stray words)
    def text(c): return ' '.join(x['t'] for x in c)
    blocks, cur = [], []
    for t in toks:
        if cur:
            prev = cur[-1]
            if prev['stop'] or prev['who'] != t['who'] or prev['seg'] != t['seg'] or t['start'] - prev['end'] > 0.6:
                blocks.append(cur); cur = []
        cur.append(t)
    if cur: blocks.append(cur)

    def cost(c, is_last, is_first=False, prev=None):
        L = len(text(c))
        # a whole clause (starts after a comma/stop, ends on one) may run 1 character longer rather than break inside
        clause_start = is_first or (prev is not None and (prev['comma'] or prev['stop']))
        whole = clause_start and (is_last or c[-1]['comma'] or c[-1]['stop'])
        if len(c) > MAX_WORDS or (L > MAX_CHARS + (1 if whole else 0) and len(c) > 1): return 1e9
        k = 1.0 + 0.02 * abs(L - 18) + (0.25 if len(c) == 2 else 0) + 0.3 * max(0, L - 26)
        # a line must not start with the last word of the previous clause ("it | and that's two hours")
        if len(c) == 6: k += 0.4
        if len(c) >= 2 and c[1]['t'] in CONJ and c[0]['t'] not in CONJ | SUBJ and not clause_start: k += 1.6
        if any(x['t'] in CONJ for x in c[2:]): k += 0.4                     # prefer the break before and/but/so
        if c[0]['t'] in ('them', 'me', 'us', 'him') and not is_first: k += 0.8
        if c[0]['t'] == 'it' and len(c) >= 2 and c[1]['t'] in ('to', 'and', 'in', 'on', 'for', 'with') and not is_first: k += 0.8
        if len(c) >= 2 and c[0]['comma'] and not is_first: k += 1.6
        if c[0]['t'] in CONJ and not is_first: k -= 0.3          # break before and/but/so/because
        if len(c) == 1: k += 2.0
        if not is_last and c[-1]['t'] in WEAK_END and not c[-1]['comma']: k += 1.5
        if not is_last and re.fullmatch(r'[$\d][\d,.:]*', c[-1]['t']): k += 1.2     # '10 / times' -> keep numbers with their noun
        if not is_last and c[-1]['comma']: k -= 0.6
        if any(x['comma'] for x in c[:-1]): k += 1.0          # a comma inside a line: break there instead
        return k
    chunks = []
    for blk in blocks:
        n = len(blk)
        best = [0.0] + [1e18] * n; arg = [0] * (n + 1)
        for j in range(1, n + 1):
            for i in range(max(0, j - MAX_WORDS), j):
                v = best[i] + cost(blk[i:j], j == n, i == 0, blk[i - 1] if i else None)
                if v < best[j]: best[j], arg[j] = v, i
        cuts, j = [], n
        while j > 0: cuts.append((arg[j], j)); j = arg[j]
        chunks += [blk[i:j] for i, j in reversed(cuts)]
    # a stray single-word block (e.g. "yeah" between sentences) joins a neighbour of the same talker when it fits
    changed = True
    while changed:
        changed = False
        for a, c in enumerate(chunks):
            if len(c) != 1: continue
            for b in (a - 1, a + 1):
                if not 0 <= b < len(chunks) or chunks[b][0]['who'] != c[0]['who'] or chunks[b][0]['seg'] != c[0]['seg']: continue
                if (b < a and chunks[b][-1]['stop']) or (b > a and c[-1]['stop']): continue   # never across a sentence end
                m = chunks[b] + c if b < a else c + chunks[b]
                if len(text(m)) <= MAX_CHARS + 2 and len(m) <= MAX_WORDS + 1 and abs(c[0]['start'] - (chunks[b][-1]['start'] if b < a else chunks[b][0]['start'])) < 1.2:
                    chunks[min(a, b)] = m; del chunks[max(a, b)]; changed = True; break
            if changed: break
    caps = []
    for a, c in enumerate(chunks):
        t0 = c[0]['start']
        nxt = chunks[a + 1][0]['start'] if a + 1 < len(chunks) else dur
        last = c[-1]
        # end of a segment, or a real pause before the next line: end within 0.15 s of the last word
        end_est = min(last['end'], last['start'] + 0.6)
        stop_at = nxt
        if a + 1 < len(chunks):
            if chunks[a + 1][0]['seg'] != last['seg']:
                stop_at = min(nxt, max(end_est, seg_end[last['seg']] - 0.02) + 0.0)
                stop_at = min(stop_at, seg_end[last['seg']] + 0.15)
            elif nxt - end_est > 0.3:
                stop_at = min(nxt, end_est + 0.15)
        else:
            stop_at = dur
        caps.append({'t0': round(t0, 3), 't1': round(max(stop_at, t0 + 0.25), 3), 'text': text(c).strip()})
    # per-clip text fixes from clips_v2_edits.json ("caption_fixes": [[old, new], ...]) on whole caption lines
    for c in caps:
        for old, new in fixes:
            if old in c['text'] and not (old in new and new in c['text']):     # idempotent for growing fixes
                c['text'] = c['text'].replace(old, new)
    # strip a trailing comma/stop that survived; never overlap the next caption
    for a, c in enumerate(caps):
        c['text'] = re.sub(r'[.,]+$', '', c['text'])
        if a + 1 < len(caps): c['t1'] = min(c['t1'], caps[a + 1]['t0'])
    return caps


def apply_patches(caps, f):
    """Hand fixes on finished caption lines (edits.json caption_patches): replace [[old line, new line]],
    merge_next [[line, new text]] joins a line with the next one, drop_into_next_once [line] deletes a line and gives
    its time to the next one."""
    if not f: return caps
    c = [dict(x) for x in caps]
    for old, new in f.get('replace', []):
        for x in c:
            if x['text'] == old: x['text'] = new
    for old, new in f.get('merge_next', []):
        for i, x in enumerate(c):
            if x['text'] == old and i + 1 < len(c):
                x['text'] = new; x['t1'] = c[i + 1]['t1']; del c[i + 1]; break
    for old in f.get('drop_into_next_once', []):
        for i, x in enumerate(c):
            if x['text'] == old and i + 1 < len(c):
                c[i + 1]['t0'] = x['t0']; del c[i]; break
    return c
