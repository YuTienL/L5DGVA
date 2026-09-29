"""Tests for dv_harness/ipxact_register_import.py (DUT-04).

Builds small REAL IP-XACT XML fixtures (both the pre-2014 `spirit:` and the
2014+ `ipxact:` namespace) in this test file and drives the module against
them, mirroring test_register_excel_extract.py's own "build a real fixture,
not a mock" discipline.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dv_harness import env_manifest, ipxact_register_import as ipxact, register_excel_extract as rex


SPIRIT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<spirit:component xmlns:spirit="http://www.accellera.org/XMLSchema/SPIRIT/1685-2009">
  <spirit:vendor>example.com</spirit:vendor>
  <spirit:library>usb_phy</spirit:library>
  <spirit:name>usb_phy_regs</spirit:name>
  <spirit:version>1.0</spirit:version>
  <spirit:memoryMaps>
    <spirit:memoryMap>
      <spirit:name>PHY_REGS</spirit:name>
      <spirit:addressBlock>
        <spirit:name>CTRL_BLOCK</spirit:name>
        <spirit:baseAddress>0x1000</spirit:baseAddress>
        <spirit:register>
          <spirit:name>CTRL0</spirit:name>
          <spirit:description>PHY control register</spirit:description>
          <spirit:addressOffset>0x0</spirit:addressOffset>
          <spirit:size>32</spirit:size>
          <spirit:access>read-write</spirit:access>
          <spirit:field>
            <spirit:name>MODE</spirit:name>
            <spirit:bitOffset>0</spirit:bitOffset>
            <spirit:bitWidth>2</spirit:bitWidth>
            <spirit:access>read-write</spirit:access>
            <spirit:enumeratedValues>
              <spirit:enumeratedValue>
                <spirit:name>IDLE</spirit:name>
                <spirit:value>0</spirit:value>
              </spirit:enumeratedValue>
              <spirit:enumeratedValue>
                <spirit:name>RUN</spirit:name>
                <spirit:value>1</spirit:value>
              </spirit:enumeratedValue>
            </spirit:enumeratedValues>
          </spirit:field>
          <spirit:field>
            <spirit:name>ENABLE</spirit:name>
            <spirit:bitOffset>2</spirit:bitOffset>
            <spirit:bitWidth>1</spirit:bitWidth>
            <spirit:access>read-write</spirit:access>
          </spirit:field>
        </spirit:register>
        <spirit:register>
          <spirit:name>STATUS0</spirit:name>
          <spirit:addressOffset>0x4</spirit:addressOffset>
          <spirit:size>32</spirit:size>
          <spirit:access>read-only</spirit:access>
          <spirit:resetValue>0x0</spirit:resetValue>
        </spirit:register>
      </spirit:addressBlock>
    </spirit:memoryMap>
  </spirit:memoryMaps>
</spirit:component>
"""

IPXACT_2014_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ipxact:component xmlns:ipxact="http://www.accellera.org/XMLSchema/IPXACT/1685-2014">
  <ipxact:vendor>example.com</ipxact:vendor>
  <ipxact:library>eth_mac</ipxact:library>
  <ipxact:name>eth_mac_regs</ipxact:name>
  <ipxact:version>1.0</ipxact:version>
  <ipxact:memoryMaps>
    <ipxact:memoryMap>
      <ipxact:name>MAC_REGS</ipxact:name>
      <ipxact:addressBlock>
        <ipxact:name>MAC_BLOCK</ipxact:name>
        <ipxact:baseAddress>0x2000</ipxact:baseAddress>
        <ipxact:register>
          <ipxact:name>INT_STATUS</ipxact:name>
          <ipxact:addressOffset>0x10</ipxact:addressOffset>
          <ipxact:size>16</ipxact:size>
          <ipxact:access>read-write</ipxact:access>
          <ipxact:field>
            <ipxact:name>TX_DONE</ipxact:name>
            <ipxact:bitOffset>0</ipxact:bitOffset>
            <ipxact:bitWidth>1</ipxact:bitWidth>
            <ipxact:access>read-write</ipxact:access>
            <ipxact:resets>
              <ipxact:reset>
                <ipxact:value>0x0</ipxact:value>
              </ipxact:reset>
            </ipxact:resets>
          </ipxact:field>
        </ipxact:register>
      </ipxact:addressBlock>
    </ipxact:memoryMap>
  </ipxact:memoryMaps>
</ipxact:component>
"""

NOT_XACT_XML = "<root><thing>not ip-xact at all</thing></root>"

NO_MEMORY_MAP_XML = """<?xml version="1.0"?>
<spirit:component xmlns:spirit="http://www.accellera.org/XMLSchema/SPIRIT/1685-2009">
  <spirit:name>bare_component</spirit:name>
</spirit:component>
"""

BAD_REGISTER_XML = """<?xml version="1.0"?>
<spirit:component xmlns:spirit="http://www.accellera.org/XMLSchema/SPIRIT/1685-2009">
  <spirit:memoryMaps>
    <spirit:memoryMap>
      <spirit:name>M</spirit:name>
      <spirit:addressBlock>
        <spirit:name>B</spirit:name>
        <spirit:register>
          <spirit:name>BAD_REG</spirit:name>
          <spirit:addressOffset>not_a_number</spirit:addressOffset>
          <spirit:size>32</spirit:size>
        </spirit:register>
        <spirit:register>
          <spirit:name>GOOD_REG</spirit:name>
          <spirit:addressOffset>0x8</spirit:addressOffset>
          <spirit:size>32</spirit:size>
          <spirit:access>read-write</spirit:access>
        </spirit:register>
      </spirit:addressBlock>
    </spirit:memoryMap>
  </spirit:memoryMaps>
</spirit:component>
"""


@pytest.fixture()
def spirit_xml(tmp_path):
    p = tmp_path / "usb_phy_regs.xml"
    p.write_text(SPIRIT_XML, encoding="utf-8")
    return p


def test_spirit_namespace_extracts_registers_fields_and_enums(spirit_xml):
    result = ipxact.extract_register_map_from_ipxact(spirit_xml)
    assert result.status == rex.STATUS_OK, result.reason
    assert result.row_errors == []
    names = [r.register_name for r in result.registers]
    assert names == ["CTRL0", "STATUS0"]

    ctrl0 = result.registers[0]
    assert ctrl0.block == "CTRL_BLOCK"
    assert ctrl0.offset == 0x0
    assert ctrl0.absolute_address == 0x1000
    assert ctrl0.width == 32
    assert ctrl0.access_type == "RW"
    assert ctrl0.access_in_current_schema is True
    assert ctrl0.notes == "PHY control register"
    mode, enable = ctrl0.fields
    assert mode.bit_offset == 0 and mode.bit_width == 2
    assert mode.enum_values == [{"value": 0, "name": "IDLE"}, {"value": 1, "name": "RUN"}]
    assert enable.enum_values is None

    status0 = result.registers[1]
    assert status0.access_type == "RO"
    assert status0.reset_value == 0x0


def test_spirit_bridges_into_register_map_schema(spirit_xml):
    result = ipxact.extract_register_map_from_ipxact(spirit_xml)
    bridged = rex.to_register_map_document(result, source_description="ip_xact_conversion")
    doc = bridged["document"]
    env_manifest.validate_register_map(doc)
    block = doc["blocks"][0]
    assert block["name"] == "CTRL_BLOCK"
    # register_excel_extract.to_register_map_document() is a SHARED bridge --
    # it never threads a per-block base_address into the document (an
    # existing limitation of that bridge, not something this importer
    # invents); the real 0x1000 base address IS captured, on
    # RegisterIR.absolute_address at the ExtractionResult level (see
    # test_spirit_namespace_extracts_registers_fields_and_enums).
    assert block["base_address"] == "0x0"
    ctrl0 = next(r for r in block["registers"] if r["name"] == "CTRL0")
    mode = next(f for f in ctrl0["fields"] if f["name"] == "MODE")
    assert mode["enum_values"] == [{"name": "IDLE", "value": "0x0"}, {"name": "RUN", "value": "0x1"}]


def test_ipxact_2014_namespace_and_resets_structure(tmp_path):
    p = tmp_path / "eth_mac_regs.xml"
    p.write_text(IPXACT_2014_XML, encoding="utf-8")
    result = ipxact.extract_register_map_from_ipxact(p)
    assert result.status == rex.STATUS_OK, result.reason
    reg = result.registers[0]
    assert reg.register_name == "INT_STATUS"
    assert reg.width == 16
    assert reg.block == "MAC_BLOCK"
    field = reg.fields[0]
    assert field.name == "TX_DONE"
    assert field.reset_value == 0x0
    assert field.access_type == "RW"


def test_missing_file_is_not_available(tmp_path):
    result = ipxact.extract_register_map_from_ipxact(tmp_path / "nope.xml")
    assert result.status == rex.STATUS_NOT_AVAILABLE
    assert "not found" in result.reason


def test_non_wellformed_xml_is_parse_error(tmp_path):
    p = tmp_path / "broken.xml"
    p.write_text("<component><unterminated>", encoding="utf-8")
    result = ipxact.extract_register_map_from_ipxact(p)
    assert result.status == rex.STATUS_PARSE_ERROR
    assert "well-formed" in result.reason


def test_wellformed_but_not_ipxact_is_parse_error(tmp_path):
    p = tmp_path / "not_xact.xml"
    p.write_text(NOT_XACT_XML, encoding="utf-8")
    result = ipxact.extract_register_map_from_ipxact(p)
    assert result.status == rex.STATUS_PARSE_ERROR
    assert "not a recognized IP-XACT" in result.reason


def test_real_component_with_no_memory_map_is_not_available(tmp_path):
    p = tmp_path / "bare.xml"
    p.write_text(NO_MEMORY_MAP_XML, encoding="utf-8")
    result = ipxact.extract_register_map_from_ipxact(p)
    assert result.status == rex.STATUS_NOT_AVAILABLE
    assert "no <memoryMap>" in result.reason


def test_bad_register_is_excluded_but_good_register_survives(tmp_path):
    p = tmp_path / "bad_register.xml"
    p.write_text(BAD_REGISTER_XML, encoding="utf-8")
    result = ipxact.extract_register_map_from_ipxact(p)
    assert result.status == rex.STATUS_PARTIAL
    names = [r.register_name for r in result.registers]
    assert names == ["GOOD_REG"]
    assert any("BAD_REG" in str(e) for e in result.row_errors)


def test_cli_exit_code_zero_on_clean_document(spirit_xml):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.ipxact_register_import", str(spirit_xml), "--json"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '"status": "OK"' in proc.stdout


def test_cli_exit_code_two_on_missing_file(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "dv_harness.ipxact_register_import", str(tmp_path / "nope.xml")],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
