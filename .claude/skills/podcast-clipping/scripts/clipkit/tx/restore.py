"""restore words dropped as bleed when the ASR timing slipped: the other mic's transcript has no such word nearby
(+-0.6 s) and the word sits between two kept words of the same mic, each within 0.5 s"""
import json, re
from attribute2 import load, own_excess
IGNORE_END = float(__import__('os').environ.get('CLIPKIT_TX_IGNORE_END', '0'))
A=json.load(open('assigned.json')); n=lambda w:re.sub(r"[^a-z0-9']","",w.lower())
F={'host':load('full_host.json'),'guest':load('full_guest.json')}; mic={'host':'R','guest':'H'}
key=lambda w:(round(w['s'],3),w['w'])
added={}
for sp,ot in (('host','guest'),('guest','host')):
    kept={key(w) for w in A[sp]}; W=F[sp]; O=F[ot]; new=[]
    i=1
    while i<len(W)-1:
        if key(W[i]) in kept or W[i]['e']<IGNORE_END: i+=1; continue
        j=i
        while j<len(W) and key(W[j]) not in kept: j+=1          # W[i:j] = a run of dropped words
        if j<len(W) and j-i<=3 and key(W[i-1]) in kept and W[i]['s']-W[i-1]['e']<0.5 and W[j]['s']-W[j-1]['e']<0.5:
            run=W[i:j]
            if not any(n(o['w'])==n(w['w']) and o['s']<w['e']+0.6 and o['e']>w['s']-0.6 for w in run for o in O):
                for w in run: w['x']=own_excess(w['s'],w['e'],mic[sp]); w['restored']=1; new.append(w)
        i=j
    A[sp]=sorted(A[sp]+new,key=lambda w:w['s']); added[sp]=new
    print(sp,len(new),' | '.join(f"{w['s']:.1f}:{w['w']}({w['x']:.0f})" for w in new[:60]))
json.dump(A,open('assigned.json','w'))
