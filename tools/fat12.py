"""Extract all files from a FAT12 floppy image: fat12.py IMAGE outdir"""
import sys,struct,os
img=open(sys.argv[1],'rb').read(); out=sys.argv[2]
bps,spc,rsv,nf,nroot,tot,_,spf=struct.unpack_from('<HBHBHHBH',img,11)
fat=img[rsv*bps:(rsv+spf)*bps]; root=(rsv+nf*spf)*bps; data=root+nroot*32
def nxt(c):
    v=struct.unpack_from('<H',fat,c*3//2)[0]; return v>>4 if c&1 else v&0xfff
def chain(c,size=None):
    b=b''
    while 2<=c<0xff0: b+=img[data+(c-2)*spc*bps:data+(c-1)*spc*bps]; c=nxt(c)
    return b if size is None else b[:size]
def walk(d,path):
    for i in range(0,len(d),32):
        e=d[i:i+32]
        if e[0]==0: break
        if e[0]==0xe5 or e[11]&8: continue
        n=e[:8].decode('cp437').strip(); x=e[8:11].decode('cp437').strip(); name=n+('.'+x if x else '')
        cl,size=struct.unpack_from('<HI',e,26)
        if e[11]&0x10:
            if n not in('.','..'): walk(chain(cl),path+'/'+name)
        else:
            os.makedirs(path,exist_ok=True); open(path+'/'+name,'wb').write(chain(cl,size)); print(size,path+'/'+name)
walk(img[root:data],out)
