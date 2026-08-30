"""POST /api/upload + GET /api/state's uploaded_files field.

Reuses the exact server-boot fixture pattern already established in
test_dashboard_interactive.py (_free_port/_mk_dashboard_project/_start_dashboard/
_wait_ready/_get/_post) -- starts dv_harness.dashboard.serve() for real, on a
background daemon thread, bound to a free local port, against a temp project,
and issues real HTTP requests (stdlib urllib only) against it.

Covers: a valid small-file upload round-trip (content actually lands on disk
correctly), rejection of an invalid category, rejection of path-traversal
filenames, rejection of a disallowed-character filename, the duplicate-
filename-gets-a-suffix behavior, the oversized-payload rejection (exercised by
calling the size-check constant/logic directly rather than a real 50MB HTTP
body -- see test_oversized_payload_rejected_without_decoding), and malformed-
base64 rejection. Also confirms GET /api/state's uploaded_files field honestly
reflects what's on disk after a real upload.
"""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

from dv_harness_tests.test_dashboard_interactive import (
    _free_port, _mk_dashboard_project, _start_dashboard, _wait_ready, _get, _post,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- Valid upload round-trip -------------------------------------------------

def test_valid_upload_round_trip_lands_on_disk_with_correct_content():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        content = b"module usb_top(); endmodule\n"
        status, data = _post(base, "/api/upload", {
            "category": "rtl", "filename": "usb_top.v", "content_b64": _b64(content),
        })
        assert status == 200
        assert data["status"] == "OK"
        assert data["category"] == "rtl"
        assert data["saved_filename"] == "usb_top.v"
        assert data["bytes"] == len(content)
        assert data["path"] == ".dv-harness/uploads/rtl/usb_top.v"

        on_disk = tmp / ".dv-harness" / "uploads" / "rtl" / "usb_top.v"
        assert on_disk.exists()
        assert on_disk.read_bytes() == content
    finally:
        shutil.rmtree(tmp)


# --- Category validation -----------------------------------------------------

def test_invalid_category_rejected():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {
            "category": "not_a_real_category", "filename": "x.txt", "content_b64": _b64(b"hi"),
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
        assert not (tmp / ".dv-harness" / "uploads").exists()
    finally:
        shutil.rmtree(tmp)


# --- Filename sanitization ---------------------------------------------------

def test_path_traversal_filename_rejected_forward_slash_style():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {
            "category": "spec", "filename": "../../evil.txt", "content_b64": _b64(b"hi"),
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
        assert not (tmp / ".dv-harness" / "uploads").exists()
    finally:
        shutil.rmtree(tmp)


def test_path_traversal_filename_rejected_backslash_style():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {
            "category": "spec", "filename": "..\\evil.txt", "content_b64": _b64(b"hi"),
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
        assert not (tmp / ".dv-harness" / "uploads").exists()
    finally:
        shutil.rmtree(tmp)


def test_disallowed_character_filename_rejected():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {
            "category": "spec", "filename": "bad$name!.txt", "content_b64": _b64(b"hi"),
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


def test_empty_filename_rejected():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {
            "category": "spec", "filename": "", "content_b64": _b64(b"hi"),
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


def test_hidden_dotfile_filename_rejected():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {
            "category": "spec", "filename": ".hidden", "content_b64": _b64(b"hi"),
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)


# --- Duplicate filename gets a numeric suffix -------------------------------

def test_duplicate_filename_gets_numeric_suffix_neither_overwritten():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status1, data1 = _post(base, "/api/upload", {
            "category": "de_sim", "filename": "sim_result.log", "content_b64": _b64(b"first upload"),
        })
        assert status1 == 200
        assert data1["saved_filename"] == "sim_result.log"

        status2, data2 = _post(base, "/api/upload", {
            "category": "de_sim", "filename": "sim_result.log", "content_b64": _b64(b"second upload"),
        })
        assert status2 == 200
        assert data2["saved_filename"] == "sim_result_1.log"

        cat_dir = tmp / ".dv-harness" / "uploads" / "de_sim"
        assert (cat_dir / "sim_result.log").read_bytes() == b"first upload"
        assert (cat_dir / "sim_result_1.log").read_bytes() == b"second upload"

        status3, data3 = _post(base, "/api/upload", {
            "category": "de_sim", "filename": "sim_result.log", "content_b64": _b64(b"third upload"),
        })
        assert status3 == 200
        assert data3["saved_filename"] == "sim_result_2.log"
        assert (cat_dir / "sim_result_2.log").read_bytes() == b"third upload"
    finally:
        shutil.rmtree(tmp)


# --- Oversized payload rejected before decoding ------------------------------

def test_oversized_payload_rejected_without_decoding():
    # Exercises the size-check logic directly (rather than sending a real
    # ~67MB HTTP body, which would be slow) by calling the dashboard module's
    # own constant/threshold and confirming a b64 string just over it is
    # rejected -- and, via a real (small) HTTP round trip below, that the
    # actual endpoint enforces the same threshold without ever calling
    # base64.b64decode on it (a malformed-but-oversized string would raise
    # binascii.Error if decoded, but must instead be rejected as BAD_REQUEST
    # for being too large, proving the size check runs first).
    from dv_harness import dashboard

    assert dashboard._MAX_UPLOAD_B64_CHARS == 50 * 1024 * 1024 * 4 / 3

    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        # One char over the threshold, and deliberately NOT valid base64
        # ('!' is not a base64 character) -- if the size check did not run
        # BEFORE the base64.b64decode call, this would still fail, but for
        # the wrong reason (malformed base64) rather than "too large". This
        # proves the ordering the spec requires.
        oversized = "!" * (int(dashboard._MAX_UPLOAD_B64_CHARS) + 1)
        status, data = _post(base, "/api/upload", {
            "category": "spec", "filename": "huge.txt", "content_b64": oversized,
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
        assert "large" in data["message"].lower()
        assert not (tmp / ".dv-harness" / "uploads" / "spec" / "huge.txt").exists()
    finally:
        shutil.rmtree(tmp)


# --- Malformed base64 rejection ----------------------------------------------

def test_malformed_base64_rejected_without_crash():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {
            "category": "spec", "filename": "bad.txt", "content_b64": "not-@-valid-base64!!!",
        })
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
        assert not (tmp / ".dv-harness" / "uploads" / "spec" / "bad.txt").exists()

        # Server must still be serving requests afterward.
        status, data = _get(base, "/api/state")
        assert status == 200
    finally:
        shutil.rmtree(tmp)


# --- GET /api/state's uploaded_files field -----------------------------------

def test_state_uploaded_files_reflects_real_disk_state():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _get(base, "/api/state")
        assert status == 200
        uf = data["uploaded_files"]
        for category in ("spec", "rtl", "command_txt", "vip_reference", "de_sim"):
            assert uf[category] == []

        _post(base, "/api/upload", {
            "category": "vip_reference", "filename": "usb_vip_notes.txt",
            "content_b64": _b64(b"reference material"),
        })

        status, data = _get(base, "/api/state")
        assert status == 200
        uf = data["uploaded_files"]
        assert uf["vip_reference"] == [{"filename": "usb_vip_notes.txt", "bytes": len(b"reference material")}]
        assert uf["spec"] == []
        assert uf["rtl"] == []
        assert uf["command_txt"] == []
        assert uf["de_sim"] == []
    finally:
        shutil.rmtree(tmp)


# --- Missing content_b64 -----------------------------------------------------

def test_missing_content_b64_rejected():
    port = _free_port()
    tmp = _mk_dashboard_project(port)
    try:
        base = f"http://127.0.0.1:{port}"
        _start_dashboard(tmp)
        _wait_ready(base)

        status, data = _post(base, "/api/upload", {"category": "spec", "filename": "x.txt"})
        assert status == 400
        assert data["error"] == "BAD_REQUEST"
    finally:
        shutil.rmtree(tmp)
