; Hand-written Crusoe native code: count %r35 down from 0x12345678 by 4
; and return through %link. Molecule kinds are inferred from the slots.
.org 0x100000
start:
    IMM imm 0x12345678 | ALU0 oril %r34, %zero, <imm>
    ALU1 addi %r35, %r34, 0 | ALU0 nop
loop:
    ALU1 addi %r35, %r35, -4 | LSU st [%r47], %r35, m=12
    BRU brc.ne loop | ALU0 cmpi.c %sink, %r35, 0
    BRU br.ind #0x7a | ALU0 nop
