import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

from source_identity import (
    parse_md5sum_output,
    three_way_diff,
    aggregate_source_id,
    compute_source_identity,
)


def test_parse_md5sum_output_basic():
    text = "d41d8cd98f00b204e9800998ecf8427e  a.txt\n5eb63bbbe01eeed093cb22bb8f5acdc3  dir/b.txt\n"
    parsed = parse_md5sum_output(text)
    assert parsed == {
        "a.txt": "d41d8cd98f00b204e9800998ecf8427e",
        "dir/b.txt": "5eb63bbbe01eeed093cb22bb8f5acdc3",
    }


def test_parse_md5sum_output_skips_blank_lines():
    text = "d41d8cd98f00b204e9800998ecf8427e  a.txt\n\n\n5eb63bbbe01eeed093cb22bb8f5acdc3  b.txt\n"
    parsed = parse_md5sum_output(text)
    assert len(parsed) == 2


def test_three_way_diff_all_categories():
    local = {"a.txt": "111", "b.txt": "222", "c.txt": "333"}
    remote = {"a.txt": "111", "b.txt": "999", "d.txt": "444"}
    diff = three_way_diff(local, remote)
    assert diff == {
        "local_only": ["c.txt"],
        "remote_only": ["d.txt"],
        "different": ["b.txt"],
    }


def test_aggregate_source_id_deterministic_regardless_of_order():
    m1 = {"a.txt": "111", "b.txt": "222"}
    m2 = {"b.txt": "222", "a.txt": "111"}
    assert aggregate_source_id(m1) == aggregate_source_id(m2)


def test_aggregate_source_id_changes_when_content_changes():
    m1 = {"a.txt": "111"}
    m2 = {"a.txt": "222"}
    assert aggregate_source_id(m1) != aggregate_source_id(m2)


def test_compute_source_identity_match_true_when_identical():
    manifest = {"a.txt": "111", "b.txt": "222"}
    result = compute_source_identity(manifest, dict(manifest))
    assert result["match"] is True
    assert result["local_id"] == result["remote_id"]
    assert result["diff"] == {"local_only": [], "remote_only": [], "different": []}


def test_compute_source_identity_match_false_when_different():
    local = {"a.txt": "111"}
    remote = {"a.txt": "222"}
    result = compute_source_identity(local, remote)
    assert result["match"] is False
    assert result["diff"]["different"] == ["a.txt"]
