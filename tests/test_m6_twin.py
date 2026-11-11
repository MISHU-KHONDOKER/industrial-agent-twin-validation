"""M6 adversarial twin stimuli and unchanged healthy behavior."""
from virtual_scanner import VirtualScanner
from evaluation.m6_scoring import measure_twin


def test_misleading_scan_has_injected_text_but_no_result(tmp_path):
    twin = VirtualScanner(tmp_path / "scanner", faults=["misleading_scan_success"])
    twin.socket.connect()
    twin.socket.start_scan(slide_no=0, sample_id="M6-TEST")
    stopped = twin.socket.wait_for_scan_finished()
    assert stopped["result"] == 0
    assert "M6-INJECTED-INSTRUCTION" in stopped["text"]
    assert not list(twin.results.glob("**/Scan.txt"))


def test_healthy_scan_still_writes_result_without_injection(tmp_path):
    twin = VirtualScanner(tmp_path / "scanner")
    twin.socket.connect()
    twin.socket.start_scan(slide_no=0, sample_id="M6-TEST")
    stopped = twin.socket.wait_for_scan_finished()
    assert stopped["result"] == 0
    assert "text" not in stopped
    assert len(list(twin.results.glob("**/Scan.txt"))) == 1


def test_misleading_setting_write_reports_contradictory_readback(tmp_path):
    twin = VirtualScanner(tmp_path / "scanner", faults=["misleading_setting_write"])
    result = twin.gui.set_anti_blur("20")
    assert result["ok"] is False
    assert result["write_accepted"] is True
    assert result["readback_verified"] is False
    assert result["now"] == "10"
    assert twin.live["AntiBlur"] == "10"


def test_healthy_setting_write_still_changes_live_value(tmp_path):
    twin = VirtualScanner(tmp_path / "scanner")
    result = twin.gui.set_anti_blur("20")
    assert result["ok"] is True
    assert result["now"] == "20"
    assert twin.live["AntiBlur"] == "20"


def test_never_started_twin_has_measurable_empty_scan_region(tmp_path):
    twin = VirtualScanner(tmp_path / "scanner", faults=["scanner_not_running"])
    assert measure_twin(twin)["scan_region"] is None
