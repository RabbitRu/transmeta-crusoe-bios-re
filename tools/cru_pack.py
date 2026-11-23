#!/usr/bin/env python3
"""Repack a modified CMS image back into a .cru file (inverse of cru.py).

    cru_pack.py ORIG.cru NEW.image OUT.cru [--keep-sig]

Takes the original .cru (for its 192-byte header and DSA signature) and a
modified decompressed image, and writes a new .cru:
  * gzip-deflate the image (same container the loader expects: 1f 8b 08)
  * patch the header's decompressed-size fields (+0x28, +0x2c) if the size changed
  * leave the header magic word +0x00 unchanged (derivation unknown, see note)

By default the DSA signature is DROPPED (replaced with nothing): a modified
image can never carry a valid Transmeta signature, so the only honest output is
an unsigned one, which the normal MSR update path will reject. Such an image is
only usable by direct SROM programming (bypasses DSA) or by patching CMS in RAM.
--keep-sig re-appends the original 63-byte signature verbatim (it will NOT
verify; use only if you want a byte-layout-complete file for a programmer that
doesn't check, or for your own round-trip tests).

NOTE on the magic word (+0x00 = 0x795b6151 in 4.4.03): we do not know its
derivation, so we leave it unchanged. If the loader validates it against the
body, a programmed image may need it fixed; flag this when testing on hardware.
"""
import sys, struct, zlib

def main(a):
    orig, newimg, out = a[1], a[2], a[3]
    keepsig = '--keep-sig' in a
    od = open(orig, 'rb').read()
    hdr = bytearray(od[:0xc0])
    # recover original signature by decompressing the original body
    x = zlib.decompressobj(31)
    x.decompress(od[0xc0:])
    sig = x.unused_data

    image = open(newimg, 'rb').read()
    # gzip with deflate, matching 1f 8b 08 container
    co = zlib.compressobj(9, zlib.DEFLATED, 31)
    body = co.compress(image) + co.flush()

    struct.pack_into('<I', hdr, 0x28, len(image))          # decompressed size
    # +0x2c is a second, slightly smaller size in the original; keep its delta
    orig_sz = struct.unpack_from('<I', od, 0x28)[0]
    orig_sz2 = struct.unpack_from('<I', od, 0x2c)[0]
    struct.pack_into('<I', hdr, 0x2c, len(image) - (orig_sz - orig_sz2))

    with open(out, 'wb') as f:
        f.write(hdr)
        f.write(body)
        if keepsig:
            f.write(sig)
    print('wrote %s: header 0xc0 + body %d%s' %
          (out, len(body), (' + sig %d (INVALID)' % len(sig)) if keepsig else ' (unsigned)'))
    print('decompressed size field: %d' % len(image))
    if image != open(newimg, 'rb').read():
        print('WARNING: image changed under us')

if __name__ == '__main__':
    main(sys.argv)
