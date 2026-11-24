"""VAD + Parakeet word-level ASR over one mic. usage: asr.py in16k.wav out.json [threads] [t0 t1]"""
import sys, json, os, numpy as np, soundfile as sf, sherpa_onnx, time
_MD=__import__('os').environ.get('CLIPKIT_MODELS','models'); M=f'{_MD}/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8'; VAD=f'{_MD}/silero_vad.onnx'
PIECE_MAX=15.0
def recognizer(threads):
    return sherpa_onnx.OfflineRecognizer.from_transducer(encoder=f'{M}/encoder.int8.onnx', decoder=f'{M}/decoder.int8.onnx',
        joiner=f'{M}/joiner.int8.onnx', tokens=f'{M}/tokens.txt', num_threads=threads, model_type='nemo_transducer', decoding_method='greedy_search')
def asr_chunk(rec, a, s0, e0):
    s=rec.create_stream(); s.accept_waveform(16000, a[s0:e0]); rec.decode_stream(s); r=s.result
    toks, ts = list(r.tokens), list(r.timestamps); durs=list(getattr(r,'durations',[]) or [])
    lp=list(getattr(r,'ys_log_probs',[]) or [])
    off=s0/16000; words=[]; cur=None
    for k,(tk,t) in enumerate(zip(toks,ts)):
        d=durs[k] if k<len(durs) else 0.04
        p=lp[k] if k<len(lp) else 0.0
        if tk.startswith(' ') or tk.startswith('▁') or cur is None:
            if cur: words.append(cur)
            cur={'w':tk.strip().replace('▁',''),'s':round(off+t,3),'e':round(off+t+d,3),'lp':[p]}
        else:
            cur['w']+=tk; cur['e']=round(off+t+d,3); cur['lp'].append(p)
    if cur: words.append(cur)
    out=[]
    for w in words:
        if w['w']:
            w['c']=round(float(np.exp(min(w.pop('lp')))),3) if lp else None
            out.append(w)
    return out
def split_long(x16, st, n, most=PIECE_MAX):
    out, todo = [], [(st, n, False, False)]
    while todo:
        s, m, sb, sa = todo.pop()
        if m <= most*16000: out.append((s,m,sb,sa)); continue
        lo, hop = max(s, s+m//2-3*16000), 160
        x=x16[lo:lo+6*16000].astype(np.float64)
        e=np.convolve((x[:len(x)//hop*hop].reshape(-1,hop)**2).mean(1), np.ones(12)/12, 'same')
        k=lo+int(np.argmin(e))*hop+hop//2
        todo += [(s,k-s,sb,True),(k,s+m-k,True,sa)]
    return sorted(out)
def vad_segments(a, thr=0.4, minsil=0.35):
    cfg=sherpa_onnx.VadModelConfig(); cfg.silero_vad.model=VAD; cfg.silero_vad.min_silence_duration=minsil
    cfg.silero_vad.min_speech_duration=0.15; cfg.silero_vad.max_speech_duration=20; cfg.silero_vad.threshold=thr; cfg.sample_rate=16000
    vad=sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120); segs=[]
    for i in range(0,len(a),512):
        vad.accept_waveform(a[i:i+512])
        while not vad.empty(): segs.append((vad.front.start,len(vad.front.samples))); vad.pop()
    vad.flush()
    while not vad.empty(): segs.append((vad.front.start,len(vad.front.samples))); vad.pop()
    return sorted(segs)
def transcribe(rec, a, segs, offset=0):
    words=[]; pieces=[p for st,n in segs for p in split_long(a,st,n)]
    own=[(st/16000,(st+n)/16000) for st,n,_,_ in pieces]
    for i,(st,n,sb,sa) in enumerate(pieces):
        s0,e0=max(0,st-(0 if sb else 4000)), min(len(a), st+n+(0 if sa else 4000))
        ws=asr_chunk(rec,a,s0,e0)
        nb=[own[j] for j in (i-1,i+1) if 0<=j<len(own)]
        for w in ws:
            m=(w['s']+w['e'])/2
            if own[i][0]-0.05<=m<=own[i][1]+0.05 or not any(x-0.05<=m<=y+0.05 for x,y in nb):
                w['piece']=i; words.append(w)
    words.sort(key=lambda w:w['s']); out=[]
    for w in words:
        if out:
            p=out[-1]; ov=min(p['e'],w['e'])-max(p['s'],w['s'])
            if ov>0.5*min(p['e']-p['s'],w['e']-w['s']) or w['s']<p['s']+0.02: continue
        out.append(w)
    for w in out: w['s']=round(w['s']+offset,3); w['e']=round(w['e']+offset,3)
    return out, [(round(a_+offset,3),round(b_+offset,3)) for a_,b_ in own]
if __name__=='__main__':
    inp,outp=sys.argv[1],sys.argv[2]; th=int(sys.argv[3]) if len(sys.argv)>3 else 2
    a=sf.read(inp,dtype='float32')[0]; off=0
    if len(sys.argv)>5:
        t0,t1=float(sys.argv[4]),float(sys.argv[5]); a=a[int(t0*16000):int(t1*16000)]; off=t0
    T=time.time(); rec=recognizer(th); segs=vad_segments(a)
    words,pieces=transcribe(rec,a,segs,off)
    json.dump({'words':words,'pieces':pieces},open(outp,'w'))
    print(inp, len(words),'words', len(pieces),'pieces', f'{time.time()-T:.0f}s', file=sys.stderr)
