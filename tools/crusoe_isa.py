"""Transmeta Crusoe TM5x00 native VLIW instruction set: encoding tables.

Shared by crusoe_dis.py (disassembler / pseudo-C decompiler) and crusoe_asm.py
(assembler). Everything here was derived from the CMS 4.4.03 image; see
docs/crusoe-isa.md for the evidence behind each field. Names ending in '?'
are guesses; 'opXXX' means the opcode is known to exist but is unnamed.

Molecule ("bundle") layout, little-endian 32-bit words w0..w3:

    w1[30:29] = format field (always carried by the second word)
        00 -> 128-bit  w0=IMM32|BRU  w1=ALU0  w2=ALU1  w3=LSU
              w1[31] selects w0: 0 = IMM32, 1 = BRU
        01 ->  64-bit  w0=ALU1  w1=LSU
        10 ->  64-bit  w0=ALU1  w1=ALU0
              (w0 is IMM32 instead when the ALU0 opcode is an imm32 form)
        11 ->  64-bit  w0=BRU   w1=ALU0

This reproduces, to the molecule, the bundle census published in
"Crusoe Exposed" part 2 for the same image (78460 x 64-bit, 23297 x 128-bit;
LSU|ALU1 25401, ALU0|ALU1 31625, ALU0|IMM 5409, ALU0|BRU 16025,
128-bit with IMM 13386, with BRU 9911).
"""

# molecule kinds (text names used by the disassembler and assembler)
K_Q_IMM, K_Q_BRU, K_LA, K_AA, K_AI, K_AB = 'Q.imm', 'Q.bru', 'LA', 'AA', 'AI', 'AB'
KINDS = (K_Q_IMM, K_Q_BRU, K_LA, K_AA, K_AI, K_AB)
# slot order inside each kind, by word index
SLOTS = {
    K_Q_IMM: ('IMM', 'ALU0', 'ALU1', 'LSU'),
    K_Q_BRU: ('BRU', 'ALU0', 'ALU1', 'LSU'),
    K_LA:    ('ALU1', 'LSU'),
    K_AA:    ('ALU1', 'ALU0'),
    K_AI:    ('IMM', 'ALU0'),
    K_AB:    ('BRU', 'ALU0'),
}
FORMAT_BITS = {K_Q_IMM: 0, K_Q_BRU: 4, K_LA: 1, K_AA: 2, K_AI: 2, K_AB: 3}  # w1[31:29] (bit31 only fixed for Q)

def is_imm32_op(op):
    """ALU opcode that takes its operand from the molecule's 32-bit IMM word."""
    return (op >> 7) == 3 and (op & 7) == 3

def classify(w0, w1):
    """Return (kind, length_in_words) from the first two words of a molecule."""
    f = (w1 >> 29) & 3
    if f == 0:
        return (K_Q_BRU if w1 >> 31 else K_Q_IMM), 4
    if f == 1:
        return K_LA, 2
    if f == 2:
        return (K_AI if is_imm32_op((w1 >> 20) & 0x1ff) else K_AA), 2
    return K_AB, 2

# ---------------------------------------------------------------- registers
# Register name table recovered from CMS's own atom printer: strings stored in
# reverse order at image offset 0xfad80..0xfb173 (r*, s*, f*, X*, 0xNN classes).
GPR = ['%%r%d' % i for i in range(62)] + ['%sink', '%zero']
SPR = ['%%s%d' % i for i in range(64)]
for _i, _n in {0: '%weflags', 1: '%aeflags', 8: '%pci_status', 32: '%fl_stack_eip',
               33: '%fl_ctx', 35: '%fl_eip', 58: '%link', 59: '%from'}.items():
    SPR[_i] = _n
for _i in range(8):
    SPR[16 + _i] = '%%selector%d' % _i
    SPR[24 + _i] = '%%limit%d' % _i
FPR = ['%%f%d' % i for i in range(32)]
# x86 guest state lives in the low GPRs (Crusoe Exposed part 2, p5)
X86_ALIAS = {0: 'eax', 1: 'ecx', 2: 'edx', 3: 'ebx', 47: 'sp'}

def reg7(n):
    """7-bit unified register number used by indirect branches: 0-63 GPR, 64-127 SPR."""
    return GPR[n] if n < 64 else SPR[n - 64]

GPR_NUM = {n: i for i, n in enumerate(GPR)}
SPR_NUM = {n: i + 64 for i, n in enumerate(SPR)}

# x86 condition-code order, as in CMS's own table ("#o,", "#no,", ...)
CC = ['o', 'no', 'b', 'nb', 'e', 'ne', 'be', 'nbe', 's', 'ns', 'p', 'np',
      'l', 'nl', 'le', 'nle']

# ---------------------------------------------------------------- opcodes
# 9-bit opcode field [28:20], one mapping shared by all units.
# Operand form is encoded in the low 3 bits of the opcode:
#   xxxxxx000  register-register  rd, rs1, rs2        (rs2 in [7:2], [1:0] extra)
#   xxxxxx011  register-imm8      rd, rs1, imm8       ([7:0], signed)
#   11xxxx011  register-imm32     rd, rs1, <imm>      (value in the IMM word)
# Names without '?' are confirmed by the opcode table / annotated listings of
# "Crusoe Exposed" (third_party/CrusoeReport-Part2-Samples.S, Disasm.cpp).
OPNAMES = {
    0x100: 'add', 0x103: 'addi', 0x183: 'addil',
    0x120: 'and', 0x123: 'andi', 0x1a3: 'andil',
    0x130: 'xor?', 0x133: 'xori?', 0x1b3: 'xoril?',
    0x138: 'or', 0x13b: 'ori', 0x1bb: 'oril',
    # sub.c with rd=%sink is a compare; 302 uses write a real rd, so these are subtracts
    0x170: 'sub.c', 0x173: 'subi.c', 0x1f3: 'subil.c',
    0x068: 'movlink?', 0x118: 'oprr?',
    0x020: 'cmp.and',
    0x090: 'sll?', 0x093: 'slli', 0x098: 'srl?', 0x09b: 'srli?',
    # 0x14b = nop and 0x03b = nop.lsu when all other fields are canonical
    # LSU
    0x050: 'ld', 0x044: 'st',
    # imm8 form of ld: reads slot imm of a local array based at rs1. RDMSR serves
    # SYSENTER_CS/ESP/EIP (0x174..0x176) as ldi %r0, %r21, 50/51/52 -> the LDM SRAM
    # copies of x86 MSRs described in Crusoe Exposed.
    0x053: 'ldi?',
}
# ALU1 atoms whose type-select bits [30:29] are non-zero use a separate opcode
# space (FP / MMX / special-register moves). Keyed by (type, opcode).
# t2.op060 reads and t2.op068 writes a special register given by the rs1 field
# (rs1=58 = %link before every indirect return), hence the names.
# Type-2 ALU1 register-bank moves (structure from the opcode histogram of
# Crusoe Exposed + operand statistics): opcode bits [8:7] select one of four
# banks, bit 3 the direction. 'mf' (xx1100000): rd = bank[rs1], rs2 unused;
# 'mt' (xx1101000): bank[rs1] = rs2, rd unused. Bank 0 = special registers
# (%link, %from, %fl_ctx, %selectorN ...); banks 1-3 are not identified yet.
# br.prep of the article is mtsr %link. t2.040/048/050/058 never have operands.
TOPNAMES = {
    (2, 0x060): 'mfsr', (2, 0x068): 'mtsr',
    (2, 0x0e0): 'mfb1', (2, 0x0e8): 'mtb1',
    (2, 0x160): 'mfb2', (2, 0x168): 'mtb2',
    (2, 0x1e0): 'mfb3', (2, 0x1e8): 'mtb3',
}
BANK_OPS = {(2, b << 7 | 0x60 | d): b for b in range(4) for d in (0, 8)}
NAME2OP = {v.rstrip('?'): (0, k) for k, v in OPNAMES.items()}
NAME2OP.update({v.rstrip('?'): k for k, v in TOPNAMES.items()})

def opname(op, t=0):
    if t:
        return TOPNAMES.get((t, op), 't%d.op%03x' % (t, op))
    return OPNAMES.get(op, 'op%03x' % op)

def parse_opname(s):
    """mnemonic -> (type, opcode)"""
    s = s.rstrip('?')
    if s in NAME2OP:
        return NAME2OP[s]
    t = 0
    if s[0] == 't' and s[2] == '.':
        t, s = int(s[1]), s[3:]
    if s.startswith('op'):
        return t, int(s[2:], 16)
    raise ValueError('unknown mnemonic %r' % s)

SPR_OPS = set(BANK_OPS)   # rs1 field is a register number in bank BANK_OPS[op]

def bank_reg(bank, n):
    return SPR[n] if bank == 0 else '%%b%d.%d' % (bank, n)

def opform(op):
    if is_imm32_op(op):
        return 'imm32'
    if op & 7 == 3:
        return 'imm8'
    return 'reg'

# ---------------------------------------------------------------- branches
# BRU atom: [31:29] kind, [28:25] cc, [24] x, [23] indirect, [22:0] target>>3
#   kind 100: unconditional; cc bit0 = L (write return address to %link)
#   kind 101: conditional on x86-style flags (cc in x86 Jcc order)
#   kind 111: conditional, second flag set (?)
#   other kinds: printed raw
BR_KIND = {4: 'br', 5: 'brc', 7: 'brc2'}
