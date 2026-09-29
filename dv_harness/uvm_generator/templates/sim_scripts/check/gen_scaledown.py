"""Generate the scale-down timer assignments for TARGET_IP's DUT-config
class from a vendor RTL-vs-VIP scale-down mapping spreadsheet.

Every field name is checked against the VIP configuration class's own
declared fields before being emitted. The spreadsheet's names and the VIP's
class names are NOT guaranteed to match -- this template's original USB
worked example had the sheet say 'tuch' where the class declared 'tuch_hs'
-- so a hand transcription of dozens of fields, each with up to several
value-range family members, is exactly the kind of place a silent mismatch
hides. This script exists to make that check automatic instead of manual.

GENERIC TEMPLATE: this checker's FRAMEWORK is protocol-agnostic and mirrors
reg_audit.py's own GENERIC TEMPLATE split: read a VIP configuration class's
declared field names via regex (VIP class = ground truth for field names),
read an external vendor scale-down mapping spreadsheet (vendor doc = ground
truth for values), cross-check every mapped field actually exists in the
VIP class, classify each row resolved/legacy-duplicate/unparsed/unmatched,
and emit SystemVerilog assignment lines into a generated .svh. That shape
applies to any VIP-based protocol whose vendor ships a scale-down/timing
mapping doc separate from the VIP source -- run with, e.g.:

    TARGET_IP=PCIE  SCALEDOWN_XLS=/path/to/pcie_scaledown_mapping.xls \\
        python gen_scaledown.py

What does NOT generalize, and is centralized below as top-of-file DATA
rather than left inline (each block says why), is this template's original
USB worked example:
  - RENAME:               one-off USB-VIP spreadsheet-vs-class name mismatch
  - MODE_COLUMNS:         USB's own two-column (USB 2.0 / SuperSpeed)
                          spreadsheet layout, matching the Makefile's own
                          SPEED enum, which the Makefile already documents as
                          "adapt to TARGET_IP's own speed/mode axis ... a
                          protocol with no such axis can drop this knob
                          entirely"
  - LEGACY_DEDUP:         USB SuperSpeed LFPS (Low-Frequency Periodic
                          Signaling) legacy timer-naming history
  - FAMILY_SUFFIXES:      this VIP's own field-naming convention for
                          value-range variants
None of these are re-derivable from structure -- they must be re-derived
per project from that project's own VIP class source and vendor scale-down
doc, never assumed to carry over. See also the output-naming note below:
the CONSUMER of this script's output (a DUT-config class analogous to this
template's original usb_top_cfg.sv / usb_scaledown_timers.svh) is itself
protocol-behavior content, out of scope for a generic template under the
"No Golden-Reference Content Mining" rule -- source it per project.
"""
import os, re, sys, glob

# Protocol-target parameterization, same vocabulary as the Makefile.
TARGET_IP = os.environ.get('TARGET_IP', 'USB')
IP_PREFIX = os.environ.get('IP_PREFIX', 'usb_')
IP_PREFIX_STEM = IP_PREFIX[:-1] if IP_PREFIX.endswith('_') else IP_PREFIX

try:
    import xlrd
except ImportError:
    xlrd = None
    print('NOTE: xlrd is not installed. This script needs it to read the '
          '.xls scale-down mapping spreadsheet (pip install xlrd, or the '
          'site equivalent) -- everything up to the spreadsheet read still '
          'imports/parses fine without it.', file=sys.stderr)

# SRC is read from VIP_HOME (see the project's top-level README, "1.
# ENVIRONMENT VARIABLES" -- the same variable every other VIP-facing path in
# this environment uses). svt_{IP_PREFIX_STEM}_configuration.sv is this
# template's original USB project's real VIP configuration class filename
# (svt_usb_configuration.sv) -- IP_PREFIX_STEM is NOT guaranteed to equal
# the current VIP's class-name stem for every VIP (same caveat reg_audit.py
# already documents for register-macro names); verify the real class
# filename against TARGET_IP's actual VIP delivery before trusting this
# default.
VIP_HOME = os.environ.get('VIP_HOME', '')
SRC = os.environ.get(
    'SCALEDOWN_VIP_CFG_SRC',
    os.path.join(VIP_HOME, 'src/sverilog/vcs/svt_%s_configuration.sv' % IP_PREFIX_STEM)
    if VIP_HOME else
    r'/path/to/your/VIP_HOME/src/sverilog/vcs/svt_%s_configuration.sv' % IP_PREFIX_STEM)

# XLS is NOT part of this template: it is the RTL-vs-VIP scale-down mapping
# spreadsheet this script was generalized from, and it must be supplied
# separately per project (ask the RTL/DV team that owns the current
# project's scale-down .svh for its current copy) -- point SCALEDOWN_XLS at
# it, or edit the default below once you have it.
XLS = os.environ.get('SCALEDOWN_XLS', r'/path/to/rtl_vip_scaledown_mapping.xls')
XLS_SHEET = os.environ.get('SCALEDOWN_XLS_SHEET', 'Scaled VIP Variables')

# -----------------------------------------------------------------------------
# USB's real instance of this mapping (this template's original worked
# example) -- confirm every equivalent against the current VIP/spreadsheet
# before reusing any of it on another protocol or project.
# -----------------------------------------------------------------------------

# Spreadsheet field name -> VIP class field name. Only entries that differ
# are interesting. USB's real, one-off spreadsheet-vs-class mismatch below;
# a different VIP's spreadsheet will have its own (possibly empty, possibly
# different) mismatch set -- this cannot be generalized, only re-derived per
# VIP/spreadsheet pair.
RENAME = {'tuch': 'tuch_hs'}

# (spreadsheet column label, 0-based column index) pairs. USB's own vendor
# spreadsheet has exactly two named mode columns, matching USB's own
# speed-mode axis (USB 2.0 vs SuperSpeed). A protocol VIP's own scale-down
# doc may have a different number of mode columns, or none at all -- adjust
# or drop entries here rather than assuming two.
MODE_COLUMNS = [('USB 2.0', 1), ('SuperSpeed', 0)]

# Legacy field-name dedup: (regex matching an OLD spreadsheet name, format
# string for the MODERN VIP field name it duplicates). If the modern name is
# already present among the VIP's declared fields, the old spreadsheet row
# is a known duplicate rather than an unmatched field. Literal USB
# SuperSpeed LFPS timer-naming history below -- meaningless outside USB;
# a different VIP/spreadsheet pair will need its own dedup list, quite
# possibly empty.
LEGACY_DEDUP = [
    (re.compile(r'lfps_t11_t10_(u[123])_min'), '%s_exit_lfps_respond_after_time'),
    (re.compile(r'lfps_t13_t11_(u[123])_min'), '%s_exit_lfps_transmit_for_time'),
]

# Value-range family suffixes this VIP's class-field naming convention uses
# (base field name -> base_min / base_max / ... variants, when declared). A
# different VIP may use a different suffix vocabulary, or none.
FAMILY_SUFFIXES = ('_min', '_max', '_longint', '_min_longint', '_max_longint')

# Output naming. gen_%s.svh and host_cfg[p].<field> are this template's
# original project's own consumer-side naming (usb_top_cfg.sv's per-port
# host_cfg array) -- a future project's DUT-config class will not be named
# that, so both are overridable rather than hardcoded.
OUT_FILE_PATTERN = os.environ.get('SCALEDOWN_OUT_PATTERN', 'gen_%s.svh')
DEST_MEMBER_FMT = os.environ.get('SCALEDOWN_DEST_MEMBER_FMT', 'host_cfg[p].%s')

# -----------------------------------------------------------------------------
# Framework below this line is protocol-agnostic.
# -----------------------------------------------------------------------------

src = open(SRC, encoding='utf-8', errors='replace').read()
declared = set(re.findall(r'^\s*(?:rand\s+)?(?:real|longint(?:\s+unsigned)?|'
                          r'int(?:\s+unsigned)?|time|bit)\s+([A-Za-z_]\w*)\s*(?:=|;)',
                          src, re.M))


def family(base):
    out = [base]
    for suf in FAMILY_SUFFIXES:
        if base + suf in declared:
            out.append(base + suf)
    return [n for n in out if n in declared]


def parse_val(s):
    """Return the SV literal, or None with a reason.

    ps/ns/us/ms/s AND bare integer counts are both accepted -- an earlier
    version of this template's original project only accepted time units
    and silently dropped every integer-count field (polling_lfps_sent_count
    and 21 others, plus one 400ps entry that happened to parse as an
    integer). Counts are as settable as times and dropping them is a silent
    gap -- the exact failure mode this whole exercise exists to remove.
    """
    s = s.strip().rstrip(';').strip()
    m = re.match(r'^([0-9.]+)\s*(ps|ns|us|ms|s)$', s)
    if m:
        return '%s%s' % (m.group(1), m.group(2))
    if re.match(r'^\d+$', s):
        return s
    return None


def collect(sheet, col):
    out = []
    for r in range(sheet.nrows):
        v = str(sheet.cell_value(r, col)).strip()
        if '=' not in v:
            continue
        name, _, val = v.partition('=')
        name = name.strip()
        pv = parse_val(val)
        if not name:
            continue
        out.append((name, pv, val))
    return out


def main():
    if xlrd is None:
        print('ERROR: xlrd is required to read %s -- install it and re-run.' % XLS,
              file=sys.stderr)
        return 1

    b = xlrd.open_workbook(XLS)
    sh = b.sheet_by_name(XLS_SHEET)

    for label, col in MODE_COLUMNS:
        rows = collect(sh, col)
        emitted, missing, unparsed, legacy = [], [], [], []
        present = set(n for n, _, _ in rows)
        for xname, val, raw in rows:
            vname = RENAME.get(xname, xname)
            if val is None:
                unparsed.append((vname, raw))
                continue
            fam = family(vname)
            if not fam:
                deduped = False
                for pat, modern_fmt in LEGACY_DEDUP:
                    m = pat.match(vname)
                    if m and (modern_fmt % m.group(1)) in present:
                        legacy.append(vname)
                        deduped = True
                        break
                if deduped:
                    continue
                missing.append('%s (xls: %s = %s)' % (vname, xname, raw))
                continue
            emitted.append((vname, val, fam))
        print('### %s: %d rows, %d resolved, %d legacy-dup, %d unparsed, %d unmatched'
              % (label, len(rows), len(emitted), len(legacy), len(unparsed), len(missing)))
        for n, raw in unparsed:
            print('    VALUE NEEDS A DECISION: %-40s = %s' % (n, raw))
        for m in missing:
            print('    NO SUCH FIELD IN THIS VIP: %s' % m)
        lines = []
        for vname, val, fam in emitted:
            for f in fam:
                lines.append('      %s = %s;' % (DEST_MEMBER_FMT % f, val))
        out_name = OUT_FILE_PATTERN % label.replace(' ', '').replace('.', '')
        open(out_name, 'w', newline='\n').write('\n'.join(lines) + '\n')
        print('    assignments emitted: %d  -> %s' % (len(lines), out_name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
