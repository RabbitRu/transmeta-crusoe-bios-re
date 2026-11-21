"""List modules of a Phoenix BIOS 4.0 R6 image (512K flash at 0xFFF80000): phxmods.py BIOS.ROM"""
import sys,struct,re
def mods(d):
    out=[]
    for m in re.finditer(rb'\x0011[\x00-\x20][A-Z_]\x1b[\x00-\x05]',d[:0x80000]):
        o=m.start()-4
        prev,=struct.unpack_from('<I',d,o)
        idn,typ,hl,comp,off,seg,explen,fraglen,packlen=struct.unpack_from('<BcBBHHIII',d,o+7)
        out.append(dict(o=o,prev=prev,id=idn,typ=typ.decode(),comp=comp,addr=(seg<<16|off) ,exp=explen,frag=fraglen,pack=packlen,data=o+hl))
    return out
if __name__=='__main__':
    d=open(sys.argv[1],'rb').read()
    for m in mods(d): print('%06x prev=%08x %s%d comp=%d addr=%08x exp=%6x frag=%6x pack=%6x end=%06x'%(m['o'],m['prev'],m['typ'],m['id'],m['comp'],m['addr'],m['exp'],m['frag'],m['pack'],m['data']+m['frag']))
