"""Audit every pattern's DUT/PHY register writes against the relationships
DOC/rtl_vip_scaledown_mapping.xls defines, and against the DUT's measured
clocks.

WHY THIS EXISTS
---------------
The VIP timing now follows GCTL[5:4] read out of the RTL, so a pattern that
writes a different GCTL than the rest silently gets a different VIP
configuration -- and nothing else in the environment would notice. The same
applies to the fields the mapping's arithmetic depends on.

WHAT IS CHECKED, and where each requirement comes from

  GCTL[5:4]   SCALEDOWN    every pattern must agree. The value itself is a
                           choice; disagreement between patterns is not,
                           because usb_top_cfg reads it back and matches the
                           VIP to whatever it finds.
  GCTL[31:19] PwrDnScale   = f(suspend_clk)/16 kHz. suspend_clk measured
                           50.00 MHz (USB_CLK_SURVEY) -> 3125.
                           usb31pg.txt:6549,6557
  GUSB2PHYCFG[9] XCVRDLY   must be SET. femtophy.txt:1346-1349: the HS
                           transmitter needs 1.6 us after XCVRSEL0 goes to HS
                           before a high-speed packet may be sent.
  GUSB2PHYCFG[15] ULPIAutoRes  must be 0 in device mode.
  GUCTL[31:22] REFCLKPER   ref_clk period in ns. 'h32 = 50 ns = 20 MHz.
                           usb31pg.txt:8049
  GFLADJ[30:24] 240MHZ_DECR = 240/ref_clk_MHz -> 12 for 20 MHz
  GFLADJ[23]   REFCLK_LPM_SEL must be 1 when the decr fields are used
  DCFG[2:0]    DEVSPD      100=Gen1 101=Gen2 000=HS 001=FS. No LS.
"""
import re, sys, os, glob

ROOT = sys.argv[1] if len(sys.argv) > 1 else 'uvm/tb'

WRITE = re.compile(
    r'`CPUWRITE4B\s*\(\s*`(USB_GCTL|USB_GUCTL|USB_GFLADJ|USB_GUSB2PHYCFG|USB_DCFG)'
    r'\s*\([^)]*\)\s*,\s*32\'h([0-9a-fA-F_]+)')

def bits(v, hi, lo):
    return (v >> lo) & ((1 << (hi - lo + 1)) - 1)

CHECKS = {
  'USB_GCTL': [
      ('PwrDnScale', lambda v: bits(v, 31, 19), 3125,
       'suspend_clk measured 50.00 MHz -> 50000/16'),
      ('SCALEDOWN',  lambda v: bits(v, 5, 4),   None,
       'must agree across patterns; usb_top_cfg reads it back'),
  ],
  'USB_GUCTL': [
      ('REFCLKPER', lambda v: bits(v, 31, 22), 0x32,
       "'h32 = 50 ns = 20 MHz ref_clk"),
  ],
  'USB_GFLADJ': [
      ('240MHZ_DECR', lambda v: bits(v, 30, 24), 12, '240/20 MHz'),
      ('LPM_SEL',     lambda v: bits(v, 23, 23),  1, 'required with the decr fields'),
  ],
  'USB_GUSB2PHYCFG': [
      ('XCVRDLY',     lambda v: bits(v, 9, 9),   1,
       'femtoPHY needs 1.6 us after XCVRSEL0 -> HS'),
      ('ULPIAutoRes', lambda v: bits(v, 15, 15), 0, 'must be 0 in device mode'),
  ],
  'USB_DCFG': [
      ('DEVSPD', lambda v: bits(v, 2, 0), None, '100=Gen1 101=Gen2 000=HS 001=FS'),
  ],
}

rows = []
for f in sorted(glob.glob(os.path.join(ROOT, '**', '*.txt'), recursive=True) +
                glob.glob(os.path.join(ROOT, '**', '*.svh'), recursive=True)):
    if 'pattern_list' in f:
        continue
    txt = open(f, encoding='utf-8', errors='replace').read()
    for ln, line in enumerate(txt.split('\n'), 1):
        if line.lstrip().startswith('//'):
            continue
        m = WRITE.search(line)
        if not m:
            continue
        reg, val = m.group(1), int(m.group(2).replace('_', ''), 16)
        rows.append((f.replace('\\', '/'), ln, reg, val))

bad = 0
spread = {}
for f, ln, reg, val in rows:
    for name, get, want, why in CHECKS[reg]:
        got = get(val)
        spread.setdefault((reg, name), {}).setdefault(got, []).append((f, ln))
        if want is not None and got != want:
            bad += 1
            print('%-58s:%-5d %s.%-12s = %d (0x%x), want %d -- %s'
                  % (f, ln, reg, name, got, got, want, why))

print('\n%d register writes inspected, %d violations' % (len(rows), bad))
print('\nvalue spread per field (a field with more than one value is a')
print('disagreement between patterns, whatever the values are):')
for (reg, name), d in sorted(spread.items()):
    tag = '  <-- DISAGREEMENT' if len(d) > 1 else ''
    print('  %s.%-12s %s%s'
          % (reg, name, ' '.join('%d(x%d)' % (k, len(v)) for k, v in sorted(d.items())), tag))
    if len(d) > 1:
        for k, v in sorted(d.items()):
            print('      = %d : %s' % (k, ', '.join('%s:%d' % (a.split('/')[-1], b)
                                                    for a, b in v[:6])))
