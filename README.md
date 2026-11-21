# Transmeta Crusoe BIOS / CMS reverse engineering

Цель: разобрать BIOS ноутбуков на Crusoe (Sony Vaio PCG-C1VP, PCG-C1MW, Dialogue Flybook A33i),
обновить Code Morphing Software (CMS), затем разгон и тюнинг CMS.

## Что разобрано

| Пакет | BIOS | Дата | PHLASH platform | Видео-BIOS | Память под CMS |
|---|---|---|---|---|---|
| `RB_R0213P1.EXE` (WinZip SFX) | R0213P1 | 2001-04 | `SONY IRX-1465` | ATI Mach64/Rage Mobility, BK4.2.7 | 16 МБ |
| `R0248E0_UF.EXE` (zip с образом дискеты) | R0248E0 | 2004-08 (сборка 2001) | `SONY IRX-1605` | ATI BK5.0.0 `lxsony` | 16 или 24 МБ |
| `R0248E0_WP.EXE` | тот же R0248E0, Sony SFX | — | — | — | не распакован (обфусцированный оверлей) |
| `WINPHLASH_13.EXE` | только прошивальщик WinPhlash (InstallShield) | — | — | — | — |

sha256 исходников:

    dd1bc42136178b5a1da37e22990d36ce03a252e3f1b453c67caa48cac8580db2  R0248E0_WP.EXE
    5d81ee1949c42a2a4f6843dc91462eca06464b36feb8660e878717e0ef9c3be5  WINPHLASH_13.EXE
    6d6ee35c7972f8cf7159dc8eda34e3fc987ae242020b949fe7105aa8e3097d3c  RB_R0213P1.EXE
    e1fbf696dc7c85531c27428acbff32b25938bc17e8bcec41e2fa725c7fe635b0  R0248E0_UF.EXE

## Главный вывод: CMS в этих файлах нет

`BIOS.ROM` (581632 байта) = 512 КБ образ флеша (отображается на 0xFFF80000) + 56 КБ кода для PHLASH.
Все 512 КБ — обычный PhoenixBIOS 4.0 Release 6.0.5: цепочка модулей, которая распаковывается
целиком (`tools/unpack.py`). Блока размером с CMS там нет; начало образа (64–128 КБ) — 0xFF/ESCD.

BIOS только *читает* сведения о CMS и управляет им через интерфейс процессора:

- CPUID 0x80860000–0x80860007 — строки setup «CMS Revision», «CMS Build Path», «Transmeta(tm) Crusoe(tm) Processor»;
- MSR 0x80868010 (LongRun) — в обоих BIOS; MSR 0x80868018–0x8086801A — только в R0248;
- R0213 содержит сообщения «CPU Soft Update error… perform the CPU Soft Update again» и «CPU Safe Mode» —
  CMS обновляется отдельной процедурой, а не PHLASH;
- R0248 показывает «OCT Version» и содержит строку «Transmeta PDB-ALI BIOS Label 2000-27, Version 105#1».

Значит, CMS лежит в отдельной микросхеме флеша, и получить его можно только дампом с платы
либо из отдельной утилиты обновления CMS.

## Формат Phoenix-модуля (как реализовано в tools/)

    +0  u32  указатель на предыдущий модуль (линейный адрес, 0xFFF80000 + смещение)
    +4  00 '1' '1'
    +7  u8   номер, +8 char тип (B=BIOSCODE, U, M, R=option ROM, X, A=ACPI, T, E, S=strings, D, G)
    +9  u8   длина заголовка (0x1B), +10 u8 сжатие (0 = нет, 5 = LZINT)
    +11 u16 offset, u16 segment, u32 распакованный размер, u32 размер фрагмента, u32 packed/указатель

LZINT = битовый поток LHA -lh5- (окно 8 КБ), перед ним u32 распакованного размера.
У фрагментированного B0 последнее поле — указатель на продолжение с 9-байтным заголовком.

## Инструменты

    python3 tools/fat12.py  floppy.IMA outdir      # файлы из образа дискеты
    python3 tools/phxmods.py BIOS.ROM              # список модулей
    python3 tools/unpack.py  BIOS.ROM outdir       # распаковать все модули
    python3 tools/hd.py      FILE 0x1000:0x40      # hex-дамп

Бинарники Sony в репозиторий не кладутся (см. `.gitignore`).
