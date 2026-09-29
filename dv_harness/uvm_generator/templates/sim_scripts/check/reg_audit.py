"""Audit every pattern's DUT/PHY register writes against the relationships
a vendor scale-down mapping doc defines, and against the DUT's measured
clocks.

GENERIC TEMPLATE: this checker's FRAMEWORK (find CPUWRITE4B calls to a
named register macro, decode named bit-fields, check them against expected
values) is protocol-agnostic. The register macro NAMES it looks for use the
TARGET_IP/IP_PREFIX environment variables (same vocabulary as the Makefile),
defaulting to this template's original USB proving-ground project:

    TARGET_IP=PCIE  python reg_audit.py <UVM_ROOT_PATH>

The actual CHECKS content below (register names GCTL/GUCTL/GFLADJ/
GUSB2PHYCFG/DCFG, bit-field names and expected values like PwrDnScale=3125,
REFCLKPER=0x32) is this template's original USB project's own worked
example, tied to its real DWC_usb31 register map and its DUT's measured
clocks (50 MHz suspend_clk, 20 MHz ref_clk) -- replace CHECKS with the
current DUT's own register map and measured values; do not assume these
numbers apply to a different chip or protocol.

WHY THIS EXISTS
---------------
The VIP timing now follows GCTL[5:4] read out of the RTL, so a pattern that
writes a different GCTL than the rest silently gets a different VIP
configuration -- and nothing else in the environment would notice. The same
applies to the fields the mapping's arithmetic depends on.

WHAT IS CHECKED, and where each requirement comes from (this template's
original USB worked example)

  GCTL[5:4]   SCALEDOWN    every pattern must agree. The value itself is a
                           choice; disagreement between patterns is not,
                           because <ip>_top_cfg reads it back and matches the
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

# Protocol-target parameterization, same vocabulary as the Makefile.
TARGET_IP = os.environ.get('TARGET_IP', 'USB')

def _reg(suffix):
    """This template's original USB project's register-macro naming:
    `<TARGET_IP>_<suffix>. Adjust here if the current DUT's register-access
    macros follow a different convention."""
    return '%s_%s' % (TARGET_IP, suffix)

REG_GCTL, REG_GUCTL, REG_GFLADJ, REG_GUSB2PHYCFG, REG_DCFG = (
    _reg('GCTL'), _reg('GUCTL'), _reg('GFLADJ'), _reg('GUSB2PHYCFG'), _reg('DCFG'))

WRITE = re.compile(
    r'`CPUWRITE4B\s*\(\s*`(' + '|'.join(
        re.escape(r) for r in
        (REG_GCTL, REG_GUCTL, REG_GFLADJ, REG_GUSB2PHYCFG, REG_DCFG)) + r')'
    r'\s*\([^)]*\)\s*,\s*32\'h([0-9a-fA-F_]+)')

def bits(v, hi, lo):
    return (v >> lo) & ((1 << (hi - lo + 1)) - 1)

CHECKS = {
  REG_GCTL: [
      ('PwrDnScale', lambda v: bits(v, 31, 19), 3125,
       'suspend_clk measured 50.00 MHz -> 50000/16'),
      ('SCALEDOWN',  lambda v: bits(v, 5, 4),   None,
       'must agree across patterns; <ip>_top_cfg reads it back'),
  ],
  REG_GUCTL: [
      ('REFCLKPER', lambda v: bits(v, 31, 22), 0x32,
       "'h32 = 50 ns = 20 MHz ref_clk"),
  ],
  REG_GFLADJ: [
      ('240MHZ_DECR', lambda v: bits(v, 30, 24), 12, '240/20 MHz'),
      ('LPM_SEL',     lambda v: bits(v, 23, 23),  1, 'required with the decr fields'),
  ],
  REG_GUSB2PHYCFG: [
      ('XCVRDLY',     lambda v: bits(v, 9, 9),   1,
       'femtoPHY needs 1.6 us after XCVRSEL0 -> HS'),
      ('ULPIAutoRes', lambda v: bits(v, 15, 15), 0, 'must be 0 in device mode'),
  ],
  REG_DCFG: [
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
