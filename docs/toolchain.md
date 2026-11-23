# Статический конвейер правки CMS

Всё работает на распакованном образе, без железа. Для заливки на чип нужен либо программатор
SROM (минует подпись DSA), либо патч CMS в RAM — оба требуют доступа к машине.

    cru.py FILE out/            # .cru -> out/FILE.image (+ .dsasig)
    crusoe_dis.py IMAGE ...     # дизассемблер / псевдо-C / --stats / --histogram
    crusoe_emu.py IMAGE ADDR    # исполнить фрагмент, проверить семантику (--selftest)
    cms_patch.py IMG OUT ...    # правки данных CPUID (--tfms/--family6/--vendor/--dump)
    crusoe_asm.py SRC -o BIN    # ассемблер (--patch IMAGE для врезки кода по адресу)
    cru_pack.py ORIG NEW OUT    # собрать образ обратно в .cru (по умолчанию без подписи)

Пример (сообщать family 6 и вендор GenuineIntel), проверено эмулятором и репаком:

    python3 tools/cms_patch.py work/cms/....image /tmp/p.image --family6 --vendor GenuineIntel
    python3 tools/crusoe_emu.py /tmp/p.image 0xa6798 --eax 1     # -> eax=00000643
    python3 tools/cru_pack.py work/sp/F1980_cms4.4.03raptor.cru /tmp/p.image /tmp/p.cru

Предупреждения для заливки (проверять на железе):
- Пересобранный .cru без подписи штатный MSR-апдейт отвергнет (проверка DSA в самом CMS).
- Слово `+0x00` заголовка (`magic`, 0x795b6151) не расшифровано и оставляется как есть; если
  загрузчик сверяет его с телом, при прошивке программатором его придётся пересчитать.
- Патчить безопаснее только основную копию во флеше: при незагрузке watchdog поднимет recovery.
