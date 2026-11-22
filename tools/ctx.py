"""Disassemble (16-bit) around every occurrence of 32-bit constants in a module: ctx.py FILE before after const..."""
import sys,re,struct
from capstone import *
md=Cs(CS_ARCH_X86,CS_MODE_16)
d=open(sys.argv[1],'rb').read(); before=int(sys.argv[2],0); after=int(sys.argv[3],0)
for cs in sys.argv[4:]:
    c=struct.pack('<I',int(cs,16))
    for m in re.finditer(re.escape(c),d):
        o=m.start(); print('---- %s @%x in %s'%(cs,o,sys.argv[1]))
        # find a sync point: try starts so that an instruction boundary hits o-2 (66 B9) or o-1
        best=None
        for st in range(o-before,o-before+16):
            ins=list(md.disasm(d[st:o+after],st))
            if any(i.address<=o<i.address+i.size and i.address+i.size==o+4 for i in ins): best=ins;break
        for i in (best or []): print('  %05x: %-22s %s %s'%(i.address,i.bytes.hex(),i.mnemonic,i.op_str))
