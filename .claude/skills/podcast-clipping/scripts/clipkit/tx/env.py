"""5 ms band-limited power envelopes of the two personal mics + bleed gains. Saves env.npz"""
import numpy as np, soundfile as sf, scipy.signal as ss, json, sys
HOP=80  # 5 ms at 16 kHz
def env(x):
    sos=ss.butter(4,[90,5000],btype='band',fs=16000,output='sos'); y=ss.sosfilt(sos,x)
    n=len(y)//HOP*HOP; p=(y[:n].reshape(-1,HOP)**2).mean(1)
    # 15 ms smoothing (3 frames), keeps ~5 ms resolution of edges
    return np.convolve(p,np.ones(3)/3,'same')+1e-13
R=env(sf.read('host.16k.wav',dtype='float32')[0]); H=env(sf.read('guest.16k.wav',dtype='float32')[0])
d=10*np.log10(R/H); lvl=10*np.log10(np.maximum(R,H))
act=lvl>np.percentile(lvl,50)
# bleed gain of Guest into Host's mic (power ratio R/H when Guest clearly dominant) and vice versa
gHR=np.median((R/H)[act&(d<-12)]); gRH=np.median((H/R)[act&(d>12)])
print('bleed Guest->Host mic %.1f dB, Host->Guest mic %.1f dB'%(10*np.log10(gHR),10*np.log10(gRH)))
# clean = own power minus predicted leak (floored)
Rc=np.maximum(R-gHR*H*1.5, R*0.01); Hc=np.maximum(H-gRH*R*1.5, H*0.01)
def floor(p):
    db=10*np.log10(p); w=6000  # 30 s blocks
    fl=np.array([np.percentile(db[i:i+w],5) for i in range(0,len(db),w)])
    return np.repeat(fl,w)[:len(db)]
np.savez('env.npz',R=R,H=H,Rc=Rc,Hc=Hc,fR=floor(Rc),fH=floor(Hc),gHR=gHR,gRH=gRH)
print('floors R %.1f H %.1f'%(np.median(floor(Rc)),np.median(floor(Hc))))
