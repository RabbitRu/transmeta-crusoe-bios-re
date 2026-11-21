# LHA -lh5- (ar002) decoder; Phoenix "LZINT" (compression type 5) is this bitstream with an 8K window.
class BitReader:
    def __init__(s,data): s.d=data; s.p=0; s.buf=0; s.n=0
    def peek(s,n):
        while s.n<n:
            s.buf=(s.buf<<8)|(s.d[s.p] if s.p<len(s.d) else 0); s.p+=1; s.n+=8
        return (s.buf>>(s.n-n))&((1<<n)-1)
    def get(s,n):
        if n==0: return 0
        v=s.peek(n); s.n-=n; s.buf&=(1<<s.n)-1; return v
def mktable(lens):
    # canonical huffman -> dict (len,code)->sym
    codes={}; code=0
    for l in range(1,17):
        for sym,ln in enumerate(lens):
            if ln==l: codes[(l,code)]=sym; code+=1
        code<<=1
    return codes
def dec(br,tbl,single):
    if single is not None: return single
    code=0
    for l in range(1,17):
        code=(code<<1)|br.get(1)
        s=tbl.get((l,code))
        if s is not None: return s
    raise ValueError('bad code')
def read_pt(br,nn,nbit,special):
    n=br.get(nbit)
    if n==0:
        return None,br.get(nbit)
    lens=[0]*nn; i=0
    while i<n:
        c=br.get(3)
        if c==7:
            while br.get(1): c+=1
        lens[i]=c; i+=1
        if i==special: i+=br.get(2)
    return mktable(lens),None
def read_c(br,pt,pts):
    NC=510; n=br.get(9)
    if n==0: return None,br.get(9)
    lens=[0]*NC; i=0
    while i<n:
        c=dec(br,pt,pts)
        if c==0: i+=1
        elif c==1: i+=br.get(4)+3
        elif c==2: i+=br.get(9)+20
        else: lens[i]=c-2; i+=1
    return mktable(lens),None
def decode(data,outlen,dicbit=13):
    br=BitReader(data); out=bytearray(); NP=dicbit+1; pbit=4 if dicbit<=13 else 5
    while len(out)<outlen:
        if br.p>len(br.d)+8: raise ValueError('truncated at %x'%len(out))
        blk=br.get(16)
        pt,pts=read_pt(br,19,5,3)
        ct,cs=read_c(br,pt,pts)
        pp,ps=read_pt(br,NP,pbit,-1)
        for _ in range(blk):
            if len(out)>=outlen: break
            c=dec(br,ct,cs)
            if c<256: out.append(c)
            else:
                ln=c-256+3
                p=dec(br,pp,ps)
                if p>1: p=(1<<(p-1))+br.get(p-1)
                src=len(out)-p-1
                for k in range(ln):
                    out.append(out[src+k] if src+k>=0 else 0x20)
    return bytes(out[:outlen])
