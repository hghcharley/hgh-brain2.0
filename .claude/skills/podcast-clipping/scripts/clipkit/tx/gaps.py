"""find own-voice stretches with no words: wordless regions and word-free stretches inside regions (active frames only)"""
import numpy as np, json, sys
FR=0.005
def gaps(regions_file='regions_raw.json', words_file='assigned_trim.json', minlen=1.0):
    Rg=json.load(open(regions_file)); A=json.load(open(words_file)); out={}
    for sp in ('host','guest'):
        ws=A[sp]; res=[(a,b) for a,b in Rg['wordless_'+sp]]
        for a,b in Rg[sp]:
            inside=sorted((max(a,w['s']),min(b,w['e'])) for w in ws if w['s']<b and w['e']>a)
            t=a
            for s,e in inside+[(b,b)]:
                if s-t>=minlen: res.append((round(t,3),round(s,3)))
                t=max(t,e)
        out[sp]=sorted(res)
    return out
if __name__=='__main__':
    g=gaps(minlen=float(sys.argv[1]) if len(sys.argv)>1 else 1.0)
    for sp in g: print(sp,len(g[sp]),'stretches, total %.1f s'%sum(b-a for a,b in g[sp]),'longest',sorted(g[sp],key=lambda x:x[0]-x[1])[:8])
    json.dump(g,open('gaps.json','w'))
