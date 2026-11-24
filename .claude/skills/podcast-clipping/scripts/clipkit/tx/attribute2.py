"""assign words to speakers by how far the word rises above the LOCAL bleed level on its own mic.
bleed level b(t) = running median of own/other dB in frames where the other person clearly talks alone."""
import numpy as np, json, re
from scipy.ndimage import median_filter
Z=np.load('env.npz'); R,H=Z['R'],Z['H']; FR=0.005
D=10*np.log10(R/H); L=10*np.log10(np.maximum(R,H))
def local_bleed(mask_other, sign, win_s=20):
    """running median (over win_s) of sign*D in frames where the other speaker clearly dominates"""
    step=int(1/FR)  # evaluate per second
    n=len(D); vals=np.full(n//step+1,np.nan)
    x=sign*D
    for i in range(0,n//step+1):
        a,b=max(0,(i-win_s//2)*step),min(n,(i+win_s//2)*step)
        m=mask_other[a:b]
        if m.sum()>50: vals[i]=np.median(x[a:b][m])
    # fill gaps with global median
    g=np.nanmedian(vals); vals[np.isnan(vals)]=g
    return np.repeat(vals,step)[:n]
import os
if os.path.exists('bleed.npz'): _b=np.load('bleed.npz'); bR,bH=_b['bR'],_b['bH']
else:
    act=L>np.percentile(L,45)
    bR=local_bleed(act&(D<-8), +1)     # Host-mic bleed of Guest, as R/H dB
    bH=local_bleed(act&(D>8), -1)      # Guest-mic bleed of Host, as H/R dB
    np.savez('bleed.npz',bR=bR,bH=bH)
def norm(w): return re.sub(r"[^a-z0-9']","",w.lower())
def own_excess(s,e,mic):
    a,b=int(s/FR),max(int(s/FR)+3,int(e/FR))
    x=(D[a:b]-bR[a:b]) if mic=='R' else (-D[a:b]-bH[a:b])
    P=np.maximum(R[a:b],H[a:b]); sel=P>=np.median(P)
    return float(np.median(x[sel]))
def load(p): return json.load(open(p))['words']
def assign(Wr,Wh,hi=15.0,lo=10.0):
    for w in Wr: w['x']=own_excess(w['s'],w['e'],'R')
    for w in Wh: w['x']=own_excess(w['s'],w['e'],'H')
    def counterpart(w,other):
        n=norm(w['w']); return [o for o in other if o['s']<w['e']+0.3 and o['e']>w['s']-0.3 and norm(o['w'])==n]
    kR,kH=[],[]; st={'clear':0,'bleed':0,'amb_kept':0,'amb_dropped':0}
    for W,O,K in ((Wr,Wh,kR),(Wh,Wr,kH)):
        for w in W:
            if w['x']>=hi: K.append(w); st['clear']+=1
            elif w['x']<lo: st['bleed']+=1
            else:
                c=counterpart(w,O)
                busy=any(o['x']>=max(hi,w['x']+10) and o['s']<w['e'] and o['e']>w['s'] for o in O)
                if busy or (c and max(o['x'] for o in c)>=w['x']): st['amb_dropped']+=1
                else: w['amb']=1; K.append(w); st['amb_kept']+=1
    return kR,kH,st
if __name__=='__main__':
    print('local bleed Host mic: p5 %.1f p50 %.1f p95 %.1f; Guest mic: p5 %.1f p50 %.1f p95 %.1f'%(*np.percentile(bR,[5,50,95]),*np.percentile(bH,[5,50,95])))
    Wr,Wh=load('full_host.json'),load('full_guest.json')
    kR,kH,st=assign(Wr,Wh); print(st,'host',len(kR),'guest',len(kH))
    for nm,W in (('host-mic',Wr),('guest-mic',Wh)):
        h,ed=np.histogram([w['x'] for w in W],bins=25,range=(-10,60)); print(nm,' '.join(f'{int(a)}:{c}' for a,c in zip(ed,h)))
    json.dump({'host':kR,'guest':kH},open('assigned.json','w'))
