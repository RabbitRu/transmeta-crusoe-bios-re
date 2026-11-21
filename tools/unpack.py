"""Unpack every module of a Phoenix BIOS 4.0 R6 image: unpack.py BIOS.ROM outdir"""
import sys,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import phxmods,lh5
d=open(sys.argv[1],'rb').read(); out=sys.argv[2]; os.makedirs(out,exist_ok=True)
ms=phxmods.mods(d); starts=sorted(m['o'] for m in ms)
for m in ms:
    raw=d[m['data']:m['data']+m['frag']]
    if m['pack']>=0xfff80000 and m['frag']<m['exp']:      # fragmented module: 'pack' is a 4G pointer to the rest
        c=m['pack']-0xfff80000; e=min([s for s in starts if s>c]+[0x80000]); raw+=d[c+9:e]      # continuation has a 9-byte header: next(4), 0, len(2), 0, 0
    try: body=raw if m['comp']==0 else lh5.decode(raw[4:],int.from_bytes(raw[:4],'little'))
    except Exception as e: print('FAIL',m['typ'],m['id'],e); continue
    n='%s%d_%06x.bin'%(m['typ'],m['id'],m['o']); open(os.path.join(out,n),'wb').write(body); print(n,len(body))
