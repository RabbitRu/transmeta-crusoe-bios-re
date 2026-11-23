# Transmeta Crusoe BIOS / CMS reverse engineering

Разбор прошивок ноутбуков на Crusoe (Sony Vaio PCG-C1VP, PCG-C1MW, Dialogue Flybook A33i).
Три этапа: (1) обновить Code Morphing Software до последней версии, (2) разгон, (3) тюнинг CMS.

## Процессоры

| Ноутбук | CPU | Видео | CMS-ветка |
|---|---|---|---|
| Sony PCG-C1VP | TM5600, 667 МГц | — | 4.1.x (последняя найденная для TM5600) |
| Sony PCG-C1MW | TM5800, 867 МГц (LongRun 333–867) | ATI Rage Mobility | 4.4.x |
| Flybook A33i | TM5800, 1 ГГц | ATI Mobility Radeon M6 16 МБ | 4.4.x |

Семейство одно (TM5800 — 130-нм вариант TM5400/5600), но C1VP — предыдущее поколение.
Ядро = `CLKIN(66.6 МГц) × множитель`; множитель и напряжение задаёт CMS, не x86-BIOS.

## Главные выводы

1. **В BIOS-файлах Sony нет CMS.** `BIOS.ROM` = 512 КБ PhoenixBIOS 4.0 R6.0.5 + код для
   PHLASH. BIOS только читает версию CMS и дёргает LongRun через MSR. См. `docs/bios-sony.md`.
2. **CMS лежит в отдельном последовательном флеше** на линиях `SROM_*` процессора (до 1 МБ),
   рядом — конфигурационный EEPROM (93LC56B). Это не та микросхема, куда пишет PHLASH.
3. **Последняя публичная CMS — 4.4.03**, добыта из HP SoftPaq `SP23689.exe`. Формат образа
   `.cru` полностью разобран (`tools/cru.py`): заголовок 192 Б + gzip-deflate + DSA-подпись.
   Детали и операционные точки частот/напряжений — в `docs/cms-format.md`.
4. **Чужой образ штатно не зальёшь**: обновление проверяет DSA-подпись Transmeta. Обходы —
   правка CMS в RAM или прямая прошивка микросхемы программатором (оба требуют доступа к железу).

5. **Нативная ISA Crusoe вскрыта** (`docs/crusoe-isa.md`): формат 64/128-битных молекул
   (признак в `w1[30:29]`), поля атомов ALU/LSU/BRU, регистры (таблица имён из самого CMS).
   Разбор воспроизводит опубликованную перепись связок до единицы. Есть дизассемблер с
   псевдо-C (`tools/crusoe_dis.py`) и ассемблер (`tools/crusoe_asm.py`); весь код CMS
   проходит «дизассемблировать → собрать» без единого расхождения.
6. **Карта CMS** (`docs/cms-architecture.md`): эмулятор CPUID, обработчики RDMSR/WRMSR,
   протокол чтения флеша и OEM Configuration Table через MSR `0x80868000`, таблицы
   диспетчеризации, подсистемы транслятора.
6a. **ABI CMS** (`docs/cms-abi.md`, `tools/cms_abi.py`): аргументы `%r40..%r45`, результат
   `%r40`, сохраняемые `%r11..%r19` и `%r25..%r33`, x86-состояние в `%r0..%r10`, глобальные
   `%r20/%r21`, стек `%r47`, возврат через `mfsr/mtsr %link` + `br.ind`.
7. **Ускорение без замены CMS** (`docs/bios-cms-tuning.md`): транслятор снаружи не
   настраивается, но есть рычаги через MSR/регистры северного моста — LongRun 100/100 и
   performance mode, `LR_ATM`, `PM_CR2_OPT.PSM_EN` (+1 такт памяти), `PERF_CTRL`, меньше SMI,
   SPD-регистры (тайминги считает CMS), арбитр PCI. Рабочие точки LongRun, вероятно, лежат в
   OCT — данных платы, а не в коде CMS.

## Этапы и план

Сделано статически (без железа): ISA, дизассемблер/ассемблер/эмулятор, ABI, карта CMS,
конвейер правки образа (`docs/toolchain.md`). Дальше всё упирается в железо.

- **Этап 1 (обновить CMS).** C1MW и Flybook (TM5800) → 4.4.03 из SP23689 (образ `raptor`
  собран под HP TC1000: привязку к плате проверить на железе). Штатно мешает DSA-подпись;
  обход — SROM-программатор или патч в RAM. Для C1VP (TM5600) нужна своя ветка 4.1.x.
- **Этап 2 (разгон).** Множитель/напряжение — в таблице LongRun (OCT или CMS). Порядок:
  1) снять таблицу `lrti_dump.py`/`crusoe_probe.py`; 2) скорость до/после рычагов BIOS
  (`docs/bios-cms-tuning.md`); 3) поднять верхний множитель в пределах ≤1.40 В.
- **Этап 3 (тюнинг CMS).** Переписать целиком нереально; реально — правки параметров
  в распакованном образе (`cms_patch.py`, `cru_pack.py`). Нужны опкоды математики
  LongRun (`op048` и др.) — добыть по живым входам/выходам.
- **Открыто без железа:** имена ~200 опкодов, отображение `%r4..10` на x86-регистры,
  подписывается ли запись OCT, происхождение magic-слова `0x795b6151`.

## Инструменты (`tools/`)

    python3 tools/unpack_softpaq.py SP23689.exe out/   # достать .cru и утилиты из HP SoftPaq
    python3 tools/cru.py  cms4.4.03raptor.cru [out/]    # разобрать образ CMS, распаковать
    python3 tools/unpack.py  BIOS.ROM out/              # распаковать модули PhoenixBIOS
    python3 tools/phxmods.py BIOS.ROM                   # список модулей BIOS
    python3 tools/fat12.py   floppy.IMA out/            # файлы из образа дискеты
    python3 tools/ctx.py     MODULE 0x30 0x40 80868010  # дизассемблер вокруг константы
    python   tools/lrti_dump.py                         # на ноутбуке: таблица LongRun + CPUID
    python3 tools/hd.py      FILE 0x1000:0x40           # hex-дамп
    python3 tools/crusoe_dis.py IMAGE 0xa6798 0xa6920      # листинг нативного кода CMS
    python3 tools/crusoe_dis.py IMAGE 0xa6798 0xa6920 -c   # то же псевдо-C
    python3 tools/crusoe_asm.py SRC.s -o OUT.bin --org A   # ассемблер (синтаксис = листинг)
    python3 tools/crusoe_asm.py --selftest IMAGE           # dis→asm всего CMS, 0 расхождений
    python3 tools/crusoe_emu.py IMAGE --selftest           # исполнить код CMS, проверить семантику ISA
    python3 tools/cms_patch.py IMAGE OUT --family6 --vendor GenuineIntel   # правки данных CPUID
    python3 tools/cru_pack.py ORIG NEW OUT.cru             # репак образа обратно в .cru (без подписи)
    python3 tools/cms_abi.py IMAGE                         # восстановить соглашение о вызовах
    python  tools/crusoe_probe.py                          # на ноутбуке: MSR/LongRun/northbridge
    python3 tools/cms_flash_read.py --sizes                # на ноутбуке: области флеша CMS/OCT

`IMAGE` — распакованный CMS: `python3 tools/cru.py cms4.4.03raptor.cru work/cms/`.
SoftPaq качается так: `curl -O https://ftp.hp.com/pub/softpaq/sp23501-24000/sp23689.exe`
(имя строчными буквами). Документы Transmeta — `https://datasheets.chipdb.org/Transmeta/`.

Зависимости для softpaq/cru: `pip install cabarchive olefile`; для ctx — `capstone`.

## Файлы

Бинарники (BIOS Sony, SP23689 и всё из него, даташиты) в git не кладутся — см. `.gitignore`,
лежат локально в `work/`. Провенанс и sha256 — в `docs/`. Исходные BIOS Sony:

    6d6ee35c7972f8cf7159dc8eda34e3fc987ae242020b949fe7105aa8e3097d3c  RB_R0213P1.EXE
    e1fbf696dc7c85531c27428acbff32b25938bc17e8bcec41e2fa725c7fe635b0  R0248E0_UF.EXE
    dd1bc42136178b5a1da37e22990d36ce03a252e3f1b453c67caa48cac8580db2  R0248E0_WP.EXE
    5d81ee1949c42a2a4f6843dc91462eca06464b36feb8660e878717e0ef9c3be5  WINPHLASH_13.EXE
    ab6e80abea21dab20ce30b74cec8441e4fe681b79647253d4589b342c099a903  SP23689.exe (HP, CMS 4.4.03)
    f2644890db044c7517ebecf7ab788c181218c793e4fafcf06856b1553be0d23e  cms4.4.03raptor.cru

## Что нужно от вас

0. **Вывод `tools/crusoe_probe.py`** с каждой машины (Linux, root) и `cms_flash_read.py --sizes`.

1. **Версии CMS** на каждой машине: строка «Code Morphing Software revision …» из
   `dmesg` (Linux) или BIOS Setup.
2. **Дамп CMS / фото плат**: маркировка последовательного флеша на линиях SROM и
   конфигурационного EEPROM, какой программатор есть.
3. **BIOS Flybook A33i**, если найдёте, — его ещё не смотрели.
