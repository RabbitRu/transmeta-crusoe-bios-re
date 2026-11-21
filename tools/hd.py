"""Hex dump: hd.py FILE offset:length ..."""
import sys
d=open(sys.argv[1],'rb').read()
for a in sys.argv[2:]:
    o,n=[int(x,0) for x in a.split(':')]
    for i in range(o,o+n,16):
        b=d[i:i+16]; print('%06x  %-48s %s'%(i,b.hex(' '),''.join(chr(c) if 32<=c<127 else '.' for c in b)))
    print()
