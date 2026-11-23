CRUDIAG - automatic Crusoe diagnostics

1. Boot the laptop from this stick (BIOS boot order: USB HDD / USB first).
2. Wait. It runs everything by itself (2-5 min) and powers off.
   If the screen says DONE but the laptop stays on, switch it off.
3. Plug the stick into any computer. Results are in results\<model>-<N>\
   (one folder per boot). Send the whole folder.

Nothing is written to the laptop. The probes only read CPU/MSR/PCI state.
Optional: put a file crudiag.cfg containing the line READ_FLASH=1 next to this
README to also dump the CMS flash regions (untested, off by default).
