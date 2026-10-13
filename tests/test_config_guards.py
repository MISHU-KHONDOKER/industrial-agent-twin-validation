"""Group B - configuration safety guards (customer_config.py).

Rules from M1: G5 machine identity, G6 mode separation, G7 backup before write,
G10 no silent defaults. Failure modes: F01 (another machine's config and licence
key), F02 (the other imaging mode), F23 (per-slide data treated as settings).
"""
import hashlib
from pathlib import Path

import customer_config as cc
from conftest import base_config, write_ini


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------ F01 / G5

def test_F01_config_from_another_machine_is_refused_before_anything_is_written(tmp_path):
    live = write_ini(tmp_path / "live.ini", base_config(key="AAAA1111FAKE"))
    good = base_config(key="BBBB2222FAKE")
    good["Setup"]["FocusDensity"] = "10"            # a real difference, so a restore WOULD act
    good = write_ini(tmp_path / "good.ini", good)
    before = _sha(live)

    result = cc.restore_good_config(live, good, exe="unused", live_check=False)

    assert result["ok"] is False and result["restored"] is False
    assert "ANOTHER" in result["error"]
    assert _sha(live) == before                     # live config untouched
    assert not list(tmp_path.glob("live.ini.customer-backup-*"))


def test_F01_licence_key_is_never_compared(tmp_path):
    live = write_ini(tmp_path / "live.ini", base_config(key="AAAA1111FAKE"))
    good = write_ini(tmp_path / "good.ini", base_config(key="BBBB2222FAKE"))
    assert cc.compare_config(live, good)["match"] is True


def test_F01_restore_text_keeps_this_machines_licence_key(tmp_path):
    live = write_ini(tmp_path / "live.ini", base_config(key="AAAA1111FAKE"))
    good = write_ini(tmp_path / "good.ini", base_config(key="BBBB2222FAKE"))
    merged = cc.merge_good_with_live(good, cc._read_ini(live))
    assert "Key=AAAA1111FAKE" in merged
    assert "BBBB2222FAKE" not in merged


def test_F01_missing_key_cannot_be_judged_and_is_allowed(tmp_path):
    no_key = base_config()
    del no_key["Controller"]
    live = write_ini(tmp_path / "live.ini", no_key)
    good = write_ini(tmp_path / "good.ini", base_config(key="BBBB2222FAKE"))
    assert cc._other_machine(live, good) is None


# ------------------------------------------------------------------ F02 / G6

def test_F02_fluorescence_file_is_refused_in_a_brightfield_session(tmp_path):
    live = write_ini(tmp_path / "live.ini", base_config(fluo="false"))
    good = write_ini(tmp_path / "good.ini", base_config(fluo="true"))
    before = _sha(live)

    result = cc.restore_good_config(live, good, exe="unused", live_check=False, mode="brightfield")

    assert result["ok"] is False and result["restored"] is False
    assert "fluorescence file" in result["error"]
    assert _sha(live) == before


def test_F02_brightfield_file_is_refused_in_a_fluorescence_session(tmp_path):
    good = write_ini(tmp_path / "good.ini", base_config(fluo="false"))
    assert "brightfield file" in cc._wrong_mode(good, "fluorescence")


def test_F02_matching_mode_is_allowed(tmp_path):
    bf = write_ini(tmp_path / "bf.ini", base_config(fluo="false"))
    fl = write_ini(tmp_path / "fl.ini", base_config(fluo="true"))
    assert cc._wrong_mode(bf, "brightfield") is None
    assert cc._wrong_mode(fl, "fluorescence") is None


def test_F02_simulator_config_is_exempt_from_the_mode_check(tmp_path):
    sim = write_ini(tmp_path / "sim.ini", base_config(fluo="true", camera="CameraSim"))
    assert cc._wrong_mode(sim, "brightfield") is None


def test_F02_good_file_per_mode_never_falls_back_to_the_other_mode(monkeypatch):
    monkeypatch.setenv("GOOD_CONFIG_BF", "configs/bf.ini")
    monkeypatch.delenv("GOOD_CONFIG_FLUO", raising=False)
    assert cc.good_config_for("brightfield").endswith("bf.ini")
    assert cc.good_config_for("fluorescence") is None


# ------------------------------------------------------------------ G7 / G10

def test_G10_no_good_file_for_this_mode_is_refused(tmp_path):
    live = write_ini(tmp_path / "live.ini", base_config())
    result = cc.restore_good_config(live, None, exe="unused", live_check=False)
    assert result["ok"] is False and result["restored"] is False
    assert "No good config" in result["error"]


def test_G9_unreadable_file_is_reported_not_raised(tmp_path):
    good = write_ini(tmp_path / "good.ini", base_config())
    result = cc.compare_config(str(tmp_path / "does-not-exist.ini"), good)
    assert result["ok"] is False and "error" in result


# ------------------------------------------------------------------ compare

def test_compare_finds_a_changed_value(tmp_path):
    live_cfg = base_config()
    live_cfg["Setup"]["FocusDensity"] = "0"
    live = write_ini(tmp_path / "live.ini", live_cfg)
    good = write_ini(tmp_path / "good.ini", base_config())
    result = cc.compare_config(live, good)
    assert result["match"] is False
    assert result["differences"] == [{"section": "Setup", "key": "FocusDensity",
                                      "live": "0", "good": "4"}]


def test_compare_finds_a_missing_setting(tmp_path):
    live_cfg = base_config()
    del live_cfg["Setup"]["StitchMode"]
    live = write_ini(tmp_path / "live.ini", live_cfg)
    good = write_ini(tmp_path / "good.ini", base_config())
    result = cc.compare_config(live, good)
    assert [m["key"] for m in result["missing"]] == ["StitchMode"]


def test_compare_ignores_the_scan_box_and_machine_paths(tmp_path):
    live_cfg = base_config()
    live_cfg["Slide"].update(ScanLeft="1.0", ScanWidth="5.0")
    live_cfg["Scan"].update(InputPath="other", ResultsPath="elsewhere")
    live = write_ini(tmp_path / "live.ini", live_cfg)
    good = write_ini(tmp_path / "good.ini", base_config())
    assert cc.compare_config(live, good)["match"] is True


def test_F23_per_slide_focus_points_are_not_settings(tmp_path):
    live_cfg, good_cfg = base_config(), base_config()
    live_cfg["Focus"] = {"F0": "1/2/3", "F1": "4/5/6"}
    good_cfg["Focus"] = {"F0": "9/9/9"}
    live = write_ini(tmp_path / "live.ini", live_cfg)
    good = write_ini(tmp_path / "good.ini", good_cfg)
    assert cc.compare_config(live, good)["match"] is True
    merged = cc.merge_good_with_live(good, cc._read_ini(live))
    assert "F0=1/2/3" in merged and "9/9/9" not in merged


# ------------------------------------------------------------------ merge

def test_merge_keeps_the_good_files_order_and_line_endings(tmp_path):
    good = tmp_path / "good.ini"
    good.write_bytes(b"[Setup]\r\nFocusDensity=4\r\n; a comment\r\nStitchMode=2\r\n")
    live = write_ini(tmp_path / "live.ini", {"Setup": {"FocusDensity": "0", "StitchMode": "0"}})
    merged = cc.merge_good_with_live(str(good), cc._read_ini(live))
    assert merged == "[Setup]\r\nFocusDensity=4\r\n; a comment\r\nStitchMode=2\r\n"


# ------------------------------------------------------------------ F23 / G7: calibration results

def _with_stage_slope(config, x_of_y):
    config["StageSlope20X"] = {"SlopeXofY": x_of_y, "SlopeYofX": "26"}
    return config


def test_F23_a_fresh_calibration_is_reported_never_called_wrong(tmp_path):
    """Found on the real scanner: after a stitching calibration by hand, the co-pilot
    treated the new calibration values as 'wrong' and put the good file's OLD ones back."""
    live = write_ini(tmp_path / "live.ini", _with_stage_slope(base_config(), "-20"))
    good = write_ini(tmp_path / "good.ini", _with_stage_slope(base_config(), "-19"))
    result = cc.compare_config(live, good)
    assert result["match"] is True                               # not a wrong setting
    assert result["calibration_differences"] == [
        {"section": "StageSlope20X", "key": "SlopeXofY", "live": "-20", "good": "-19"}]


def test_F23_a_restore_keeps_the_live_calibration_and_fixes_the_rest(tmp_path):
    live_cfg = _with_stage_slope(base_config(), "-20")
    live_cfg["Setup"]["FocusDensity"] = "0"                       # a real wrong setting
    live = write_ini(tmp_path / "live.ini", live_cfg)
    good = write_ini(tmp_path / "good.ini", _with_stage_slope(base_config(), "-19"))
    merged = cc.merge_good_with_live(good, cc._read_ini(live))
    assert "SlopeXofY=-20" in merged and "SlopeXofY=-19" not in merged   # calibration kept
    assert "FocusDensity=4" in merged                                     # the wrong one fixed


def test_F23_a_calibration_key_missing_from_the_live_file_gets_the_good_value(tmp_path):
    live = write_ini(tmp_path / "live.ini", base_config())                # no [StageSlope20X]
    good = write_ini(tmp_path / "good.ini", _with_stage_slope(base_config(), "-19"))
    merged = cc.merge_good_with_live(good, cc._read_ini(live))
    assert "SlopeXofY=-19" in merged
