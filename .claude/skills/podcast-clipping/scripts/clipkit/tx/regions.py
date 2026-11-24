"""per-speaker speech regions from own-mic energy with bleed removed, reconciled with that speaker's words.
Also trims word end times that run past the end of the sound. reads assigned.json, env.npz"""
import numpy as np, json
Z=np.load('env.npz'); FR=0.005
def runs(m):
    m=np.concatenate([[0],m.astype(np.int8),[0]]); d=np.diff(m)
    return list(zip(np.where(d==1)[0],np.where(d==-1)[0]))
def active(P,Q,g,fl):
    """frames where this mic carries its own speaker's voice: clean power well above floor and well above predicted leak"""
    leak=g*Q; clean=np.maximum(P-leak,1e-13); cdb=10*np.log10(clean)-fl
    d=10*np.log10(P/Q)          # raw own-vs-other level: bleed sits at -11..-25 dB, own voice at +15..+25 dB
    core=(cdb>18)&(d>3)
    ext=(cdb>8)&(d>-6)
    # hysteresis: keep ext runs that contain a core frame
    out=np.zeros_like(core)
    for a,b in runs(ext):
        if core[a:b].any(): out[a:b]=True
    return out, cdb
def close(m,gap):
    g=int(gap/FR); r=runs(m); m=m.copy()
    for (a,b),(c,d) in zip(r,r[1:]):
        if c-b<=g: m[b:c]=True
    return m
def build(words,P,Q,g,fl):
    act,cdb=active(P,Q,g,fl)
    # trim late word ends: if a word runs past its sound, end it 30 ms after the last active frame
    ws=sorted(words,key=lambda w:w['s'])
    for i,w in enumerate(ws):
        a,b=int(w['s']/FR),int(w['e']/FR)
        nxt=ws[i+1]['s'] if i+1<len(ws) else 1e9
        if nxt-w['e']<0.12 or b-a<6: continue
        seg=act[a:b]
        if seg.any():
            last=a+np.where(seg)[0][-1]
            ne=(last+1)*FR+0.03
            if ne<w['e']-0.04: w['e']=round(max(ne,w['s']+0.08),3)
    # words that energy missed (quiet syllables): mark word spans active where clean level is at least modestly up
    for w in ws:
        a,b=int(w['s']/FR),int(w['e']/FR)
        if not act[a:b].any():
            act[a:b]|=cdb[a:b]>4
            if not act[a:b].any(): act[a:b]=True
    m=close(act,0.25)
    reg=[(a*FR,b*FR) for a,b in runs(m) if (b-a)*FR>=0.08]
    # keep regions that hold a word, or are short (breath/laugh/backchannel the ASR skipped); flag long word-less ones
    starts=np.array([w['s'] for w in ws]); ends=np.array([w['e'] for w in ws])
    keep=[];wordless=[]
    for a,b in reg:
        has=((starts<b)&(ends>a)).any()
        if has: keep.append((a,b))
        elif b-a>=0.3: wordless.append((round(a,3),round(b,3)))
    return [[round(a,3),round(b,3)] for a,b in keep], wordless, ws
if __name__=='__main__':
    A=json.load(open('assigned.json'))
    import os
    if os.path.exists('recovered.json'):
        Rc=json.load(open('recovered.json'))
        for sp in A: A[sp]=sorted(A[sp]+Rc[sp],key=lambda w:w['s'])
    rR,wlR,wR=build(A['host'],Z['R'],Z['H'],Z['gHR'],Z['fR'])
    rH,wlH,wH=build(A['guest'],Z['H'],Z['R'],Z['gRH'],Z['fH'])
    rg=os.environ.get('CLIPKIT_TX_RANGE')      # transcribe.py --range: the level envelope covers the whole recording,
    if rg:                                      # so keep only the regions inside the stretch that was recognised
        t0,t1=map(float,rg.split(','))
        clip=lambda L:[[round(max(a,t0),3),round(min(b,t1),3)] for a,b in L if b>t0 and a<t1]
        rR,rH,wlR,wlH=clip(rR),clip(rH),clip(wlR),clip(wlH)
    json.dump({'host':rR,'guest':rH,'wordless_host':wlR,'wordless_guest':wlH},open('regions_raw.json','w'))
    json.dump({'host':wR,'guest':wH},open('assigned_trim.json','w'))
    for n,r,wl in (('host',rR,wlR),('guest',rH,wlH)):
        print(n,len(r),'regions, talk %.0f s'%sum(b-a for a,b in r),'| wordless>=0.3s:',len(wl),'>2s:',[x for x in wl if x[1]-x[0]>2])
