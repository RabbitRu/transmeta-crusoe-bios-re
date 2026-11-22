#!/usr/bin/env python3
"""Pull the CMS .cru image and tools out of HP SoftPaq SP23689.

    unpack_softpaq.py sp23689.exe outdir

SP23689.exe is a Windows self-extractor. Layout:
    SP23689.exe (InstallShield SFX)
      -> main cabinet (MSZIP)        : CMSUpgradeTool_1.1.16.Msi
         -> MSI stream "Data.Cab"    : inner cabinet (MSZIP)
            -> F1980_cms4.4.03raptor.cru   the CMS image  (feed to cru.py)
               F1687_SoftPatch.exe         flasher GUI
               F1949_CMSDll.dll            update logic (MSR interface)
               F1539/F1542_CMSDrv.sys      kernel driver that issues the MSR update
               F1870_CrusoePTTen.msi       Persistent Translation Technology service
               F1992_SoftPatchConfirm.exe
               F1622_SoftPatchCru.ico

Needs: pip install cabarchive olefile
"""
import sys, os, struct, re
import cabarchive, olefile

def _msi_name(n):
    tbl = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._'
    out = []
    for ch in n:
        c = ord(ch)
        if 0x3800 <= c < 0x4800:
            c -= 0x3800; out.append(tbl[c & 0x3f] + tbl[c >> 6])
        elif 0x4800 <= c < 0x4840:
            out.append(tbl[c - 0x4800])
        else:
            out.append(ch)
    return ''.join(out)

def first_cab(buf):
    """Return the first real MSCF cabinet. The SFX stub contains MSCF byte
    sequences that are not cabinets, so validate the directory fields."""
    for m in re.finditer(b'MSCF', buf):
        o = m.start()
        if o + 36 > len(buf):
            continue
        size = struct.unpack_from('<I', buf, o + 8)[0]
        coff = struct.unpack_from('<I', buf, o + 16)[0]
        nfold = struct.unpack_from('<H', buf, o + 26)[0]
        nfile = struct.unpack_from('<H', buf, o + 28)[0]
        if 0 < size <= len(buf) - o and 1 <= nfold < 100 and 0 < nfile < 1000 and coff < size:
            return buf[o:o + size]
    raise SystemExit('no cabinet found')

def main():
    exe, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    data = open(exe, 'rb').read()

    outer = cabarchive.CabArchive(first_cab(data))
    msi = next(f.buf for _, f in outer.items())            # CMSUpgradeTool_*.Msi

    ole = olefile.OleFileIO(msi)
    datacab = None
    for s in ole.listdir():
        if _msi_name(s[0]).lower() == 'data.cab':
            datacab = ole.openstream(s).read()
    if datacab is None:                                    # fall back: largest stream
        datacab = max((ole.openstream(s).read() for s in ole.listdir()), key=len)

    inner = cabarchive.CabArchive(datacab)
    for name, f in inner.items():
        dst = os.path.join(outdir, name.replace('\\', '_').replace('/', '_'))
        open(dst, 'wb').write(f.buf)
        print('%8d  %s' % (len(f.buf), os.path.basename(dst)))

if __name__ == '__main__':
    main()
