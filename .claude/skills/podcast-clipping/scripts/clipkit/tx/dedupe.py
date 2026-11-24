"""after attribute2: drop the off-mic crew line at the very start, and resolve a word kept for BOTH speakers
(same word, overlapping in time): keep it for the person whose own mic has it closer to their normal speaking level"""
import json, re, numpy as np
IGNORE_END = float(__import__("os").environ.get("CLIPKIT_TX_IGNORE_END", "0"))  # off-mic talk before this (s) is dropped
Z=np.load('env.npz'); P={'host':Z['R'],'guest':Z['H']}
A=json.load(open('assigned.json'))
def lvl(w,sp):
    a=int(w['s']/0.005); b=max(a+3,int(w['e']/0.005)); return 10*np.log10(np.percentile(P[sp][a:b],90))
med={sp:np.median([lvl(w,sp) for w in A[sp]]) for sp in A}
for sp in A:
    for w in A[sp]: w['rel']=round(lvl(w,sp)-med[sp],1)
# 0.0-2.2 s: "You guys are good to go, so whenever you're ready" is a third voice (20-35 dB under both speakers' normal level)
crew=[w for sp in A for w in A[sp] if w['e']<IGNORE_END and w['rel']<-15]
for sp in A: A[sp]=[w for w in A[sp] if not (w['e']<IGNORE_END and w['rel']<-15)]
n=lambda w:re.sub(r"[^a-z0-9']","",w.lower())
drop={'host':set(),'guest':set()}
def cont(ws,k,gap=0.3):
    """does word k sit inside that person's own run of speech (an own word within `gap` s before or after)?"""
    return (k>0 and ws[k]['s']-ws[k-1]['e']<gap) or (k+1<len(ws) and ws[k+1]['s']-ws[k]['e']<gap)
# a word heard on both mics is one utterance: it goes to the person whose sentence it continues; if both or
# neither, to the one whose mic has it nearer their normal level (the other mic usually carries a laugh or breath)
for i,r in enumerate(A['host']):
    for j,h in enumerate(A['guest']):
        if h['s']<r['e'] and h['e']>r['s'] and n(h['w'])==n(r['w']):
            cr,ch=cont(A['host'],i),cont(A['guest'],j)
            if cr!=ch: (drop['guest'].add(j) if cr else drop['host'].add(i))
            elif r['rel']>=h['rel']: drop['guest'].add(j)
            else: drop['host'].add(i)
# an isolated, quiet, borderline word (energy between bleed and own voice) is far more likely bleed than speech
for sp in A:
    for k,w in enumerate(A[sp]):
        if w.get('amb') and w['rel']<-10 and not cont(A[sp],k,0.5): drop[sp].add(k)
        # a lone word 20+ dB under that person's normal level, with no own word within 1 s: bleed the local estimate missed
        elif w['rel']<-20 and not cont(A[sp],k,1.0): drop[sp].add(k)
for sp in A: A[sp]=[w for k,w in enumerate(A[sp]) if k not in drop[sp]]
json.dump(A,open('assigned.json','w'))
print('crew words removed:',' '.join(w['w'] for w in sorted(crew,key=lambda w:w['s'])))
print('duplicates removed: host',len(drop['host']),'guest',len(drop['guest']),'| remaining host',len(A['host']),'guest',len(A['guest']))
