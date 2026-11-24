#!/usr/bin/env python3
"""Check one title hook version against the clip it was made from.

  python scripts/title_check.py TITLED.mp4 UNTITLED.mp4

Pulls the frame at 1 s (saved next to TITLED as <name>_1s.jpg), finds the white title box in the middle of the frame
(35-75% down), and prints one line of JSON: box [x0, y0, x1, y1], width as % of the frame, left and right margins,
the box centre as a fraction of the height (cy), and whether the two files are the same length.
Works for a white box with dark text, whichever editor made it. The numbers do not replace looking at the still.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _boot import boot
boot(need_work=False, need=('PIL',))
import subprocess, json
from PIL import Image
if len(sys.argv) != 3 or sys.argv[1] in ('-h', '--help'):
    print(__doc__); sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help') else 2)
FF = ""                                   # ffmpeg and ffprobe from PATH
f, ref = sys.argv[1], sys.argv[2]
out = os.path.splitext(f)[0] + "_1s.jpg"
subprocess.run([FF+"ffmpeg","-v","error","-y","-ss","1","-i",f,"-frames:v","1","-q:v","2",out],check=True)
def probe(p):
    j=json.loads(subprocess.run([FF+"ffprobe","-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",p],capture_output=True,text=True).stdout)
    return float(j["format"]["duration"]), sorted(s["codec_type"] for s in j["streams"])
d,s=probe(f); rd,rs=probe(ref)
im=Image.open(out).convert("RGB"); W,H=im.size; px=im.load()
# rows where a long run of near-white pixels exists in the middle band
rows=[]
for y in range(int(H*0.35),int(H*0.75)):
    run=best=0;bx=None;cur=None
    for x in range(W):
        r,g,b=px[x,y]
        if r>245 and g>245 and b>245:
            if run==0: cur=x
            run+=1
            if run>best: best=run;bx=(cur,x)
        else: run=0
    if best>W*0.25: rows.append((y,bx))
if rows:
    y0,y1=rows[0][0],rows[-1][0]; x0=min(r[1][0] for r in rows); x1=max(r[1][1] for r in rows)
    print(json.dumps(dict(file=os.path.basename(f),dur=round(d,3),ref_dur=round(rd,3),dur_ok=abs(d-rd)<0.1,streams=s,box=[x0,y0,x1,y1],box_w_pct=round((x1-x0)/W*100,1),margin_l=x0,margin_r=W-1-x1,cy=round((y0+y1)/2/H,3),frame=out)))
else: print(json.dumps(dict(file=f,dur=d,ref_dur=rd,streams=s,box=None)))
