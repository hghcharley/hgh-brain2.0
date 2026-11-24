"""re-transcribe word-free own-voice stretches on short windows; add words that are the mic owner's"""
import numpy as np, json, soundfile as sf
IGNORE_END = float(__import__("os").environ.get("CLIPKIT_TX_IGNORE_END", "0"))  # off-mic talk before this (s) is dropped
from asr import recognizer, asr_chunk
from attribute2 import own_excess
G=json.load(open('gaps.json')); A=json.load(open('assigned_trim.json'))
rec=recognizer(3); found={}
for sp,wav,sign in (('host','host',1),('guest','guest',-1)):
    a=sf.read(f'{wav}.16k.wav',dtype='float32')[0]; ws=A[sp]; new=[]
    for s,e in G[sp]:
        s0,e0=max(0,int((s-0.6)*16000)),int((e+0.6)*16000)
        for w in asr_chunk(rec,a,s0,e0):
            m=(w['s']+w['e'])/2
            if not (s-0.05<=m<=e+0.05) or w['e']<IGNORE_END: continue  # 0-2.3 s is an off-mic crew voice
            if any(o['s']<w['e'] and o['e']>w['s'] for o in ws+new): continue
            w['x']=own_excess(w['s'],w['e'],'R' if sign==1 else 'H')
            if w['x']>=15: w['rec']=1; new.append(w)
    found[sp]=new
    print(sp,len(new),'recovered:',' | '.join(f"{w['s']:.1f}:{w['w']}" for w in new[:80]))
json.dump(found,open('recovered.json','w'))
