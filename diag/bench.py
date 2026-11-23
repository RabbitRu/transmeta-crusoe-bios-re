"""Fixed CPU/memory workload; compare the times between runs (before/after BIOS changes).
Each test runs 3 times: the first run includes CMS translation, the rest show
steady-state speed of translated code."""
import hashlib, time

def t(name, f):
    for k in range(3):
        a = time.time(); f(); print('%-22s run %d: %.3f s' % (name, k + 1, time.time() - a))

buf = b'\x5a' * (16 << 20)
t('sha256 16MB', lambda: hashlib.sha256(buf).digest())
t('python loop 2M', lambda: sum(i * i for i in range(2000000)))
def copy8():
    for _ in range(8):
        bytearray(buf)          # one 16 MB copy alive at a time: fits 112 MB RAM
t('memcopy 16MB x8', copy8)
