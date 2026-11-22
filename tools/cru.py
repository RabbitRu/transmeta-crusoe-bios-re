#!/usr/bin/env python3
"""Parse a Transmeta Crusoe CMS flash image (.cru): cru.py FILE [outdir]

Format (confirmed against cms4.4.03raptor.cru from HP SoftPaq SP23689):

    offset  size   meaning
    0x000   192    header (see fields below)
    0x0c0   N      CMS ROM image, gzip-deflate compressed (starts 1f 8b 08)
    end-?   ~63    DSA signature applied by Transmeta (gzip "unused_data" tail)

Header fields that are understood (little-endian u32):
    +0x00   magic / checksum word
    +0x08   0xC0  = header length = offset of the gzip stream
    +0x24   load offset of the image in CMS DRAM space (0x8e000)
    +0x28   decompressed image size in bytes
    +0x2c   second size field (slightly smaller than +0x28)
    +0x80   ASCII build string, e.g. "20030114 19:26 official release 4.4.0#3"

The decompressed image is the CMS the processor streams into RAM at boot
(total_RAM-16MB). The DSA public key used to authenticate updates lives inside
it; the private key is Transmeta's, so the normal MSR update path only accepts
Transmeta-signed images. See README.md for the modification routes.

With no outdir, prints the header report only. With outdir, also writes
<name>.image (decompressed) and <name>.dsasig (trailing signature).
"""
import sys, os, struct, zlib, re

def parse(path):
    d = open(path, 'rb').read()
    hdr = d[:192]
    f = lambda o: struct.unpack_from('<I', hdr, o)[0]
    m = re.search(rb'[0-9]{8} [ -~]+', hdr[0x80:])
    build = m.group().decode() if m else '(none)'
    info = dict(
        total=len(d), magic=f(0), hdr_len=f(8), load_off=f(0x24),
        decomp_size=f(0x28), size2=f(0x2c), build=build,
    )
    x = zlib.decompressobj(31)                 # 31 = gzip
    image = x.decompress(d[info['hdr_len']:])
    info['dsa_sig'] = x.unused_data
    return info, image

def main():
    info, image = parse(sys.argv[1])
    print('file            : %s' % sys.argv[1])
    print('total size      : %d' % info['total'])
    print('header length   : 0x%x' % info['hdr_len'])
    print('load offset     : 0x%x  (CMS DRAM)' % info['load_off'])
    print('decompressed    : %d bytes (header says %d)' % (len(image), info['decomp_size']))
    print('match           : %s' % (len(image) == info['decomp_size']))
    print('DSA signature   : %d trailing bytes' % len(info['dsa_sig']))
    print('build string    : %s' % info['build'])
    print('magic word      : 0x%08x' % info['magic'])
    if len(sys.argv) > 2:
        os.makedirs(sys.argv[2], exist_ok=True)
        base = os.path.join(sys.argv[2], os.path.basename(sys.argv[1]))
        open(base + '.image', 'wb').write(image)
        open(base + '.dsasig', 'wb').write(info['dsa_sig'])
        print('wrote %s.image and %s.dsasig' % (base, base))

if __name__ == '__main__':
    main()
