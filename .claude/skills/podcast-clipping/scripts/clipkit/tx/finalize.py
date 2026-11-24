"""write transcript/ outputs: corrected word lists, transcript.md, speech_regions.json, mics.json"""
import json, re, os
from collections import Counter
OUT=os.environ['CLIPKIT_TX_OUT']; os.makedirs(OUT,exist_ok=True)
A=json.load(open('assigned_trim.json')); RG=json.load(open('regions_raw.json'))

# (heard words, lowercase, punctuation-stripped) -> replacement words; from shoot.json transcript.fixes
FIX=[(list(a),list(b)) for a,b in json.loads(os.environ.get('CLIPKIT_TX_FIXES','[]'))]
def core(w): return re.sub(r"^[^\w']+|[^\w'.]+$","",w).lower().rstrip('.') if not w.lower().startswith('clawed.md') else 'clawed.md'
def fix(ws,log):
    out=[];i=0
    while i<len(ws):
        for pat,rep in FIX:
            seg=ws[i:i+len(pat)]
            if len(seg)==len(pat) and [core(w['w']) for w in seg]==pat:
                lead=re.match(r"^[^\w']*",seg[0]['w']).group(0); trail=re.search(r"[^\w']*$",seg[-1]['w']).group(0)
                if pat==['clawed.md']: trail=''
                s,e=seg[0]['s'],seg[-1]['e']; k=len(rep)
                for j,r in enumerate(rep):
                    out.append({'w':(lead if j==0 else '')+r+(trail if j==k-1 else ''),'s':round(s+(e-s)*j/k,3),'e':round(s+(e-s)*(j+1)/k,3)})
                heard=' '.join(w['w'] for w in seg).strip(',.?!')
                if heard!=' '.join(rep): log[heard+' -> '+' '.join(rep)]+=1
                i+=len(pat); break
        else:
            out.append({'w':ws[i]['w'],'s':ws[i]['s'],'e':ws[i]['e']}); i+=1
    return out
log=Counter(); W={}
for sp in ('host','guest'):
    W[sp]=fix(sorted(A[sp],key=lambda w:w['s']),log)
    # snap word edges that stick out of that speaker's energy region by < 0.3 s onto the region edge
    # (ASR timestamps are on an 80 ms grid and the last word of a piece tends to end late)
    import bisect
    RS=RG[sp]; starts=[a for a,b in RS]
    for w in W[sp]:
        k=bisect.bisect_right(starts,(w['s']+w['e'])/2)-1
        if k<0: continue
        a,b=RS[k]
        if not (a<=(w['s']+w['e'])/2<=b): continue
        if a-0.3<w['s']<a: w['s']=a
        if b<w['e']<b+0.3: w['e']=b
        if w['e']-w['s']<0.04: w['e']=round(w['s']+0.04,3)
    for w in W[sp]:
        if w['e']-w['s']<0.04: w['e']=round(w['s']+0.04,3)
    W[sp].sort(key=lambda w:(w['s'],w['e']))
    json.dump(W[sp],open(f'{OUT}/words_{sp}.json','w'))
json.dump({'host':RG['host'],'guest':RG['guest']},open(f'{OUT}/speech_regions.json','w'))
# transcript.md
# lines: each person's words are cut into sentence units (sentence end, a pause over 0.6 s, or 35 words, breaking at
# a comma where possible); units of both people are then put in order of their first word. Crosstalk therefore reads
# as whole phrases instead of alternating single words.
def ts(t):
    d=int(round(t*10)); return f"{d//600:02d}:{d%600//10:02d}.{d%10}"
def units(ws,most=35,gap=0.6):
    out=[];cur=[]
    for k,w in enumerate(ws):
        if cur and w['s']-cur[-1]['e']>gap: out.append(cur); cur=[]
        cur.append(w)
        if re.search(r"[.?!]$",w['w']): out.append(cur); cur=[]
        elif len(cur)>=most:
            c=[i for i,x in enumerate(cur) if x['w'].endswith(',') and i>=len(cur)//2]
            k2=c[-1] if c else len(cur)-1
            out.append(cur[:k2+1]); cur=cur[k2+1:]
    if cur: out.append(cur)
    return out
U=sorted([(u[0]['s'],sp,u) for sp in W for u in units(W[sp])],key=lambda x:x[0])
lines=[]
for k,(t0,sp,u) in enumerate(U):
    last=k+1==len(U) or U[k+1][1]!=sp
    lines.append(f"[{ts(t0)}] {sp.upper()}: {' '.join(w['w'] for w in u)}"+(f" [end {ts(u[-1]['e'])}]" if last else ''))
turns=[1 for k in range(len(U)) if k==0 or U[k][1]!=U[k-1][1]]
fixes='\n'.join(f'- "{k}" ({v}x)' for k,v in sorted(log.items()))
NAMES=json.loads(os.environ.get('CLIPKIT_TX_NAMES','{}'))
hdr=f"""# {os.environ.get('CLIPKIT_TX_TITLE','Transcript')}

Master clock = the mic audio timeline (starts at 0). Each line starts at its first word's start; `[end mm:ss.s]` marks the last word's end of each turn.
Speaker per word from per-mic energy (HOST = {NAMES.get('host','host')}, GUEST = {NAMES.get('guest','guest')}). ASR: NeMo Parakeet TDT 0.6B v2 (int8, sherpa-onnx). Filler words and false starts are as recognised;
the recogniser tends to drop some "um"/"uh" fillers, so a few may be missing. Lines are ordered by their first word; in crosstalk a line can start before the previous line ends.

## Corrections made to the recogniser's output (applied to the word files too)
{fixes}

## Transcript
"""
open(f'{OUT}/transcript.md','w').write(hdr+'\n'.join(lines)+'\n')
print('lines',len(lines),'turns',len(turns),'max words/line',max(len(l.split())-2 for l in lines)); print(fixes)
