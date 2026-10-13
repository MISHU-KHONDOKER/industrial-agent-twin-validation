# Synced from the private co-pilot by tools/sync_from_private.py - change it there, then re-sync.
"""Customer mode — keep the scanner's live config.ini equal to the known-good file.

  compare_config()       READ-ONLY: which settings differ from the good file (step 4a)
  restore_good_config()  back up → close HDScanner → write the good values → start
                         HDScanner → wait for it → compare again (step 4b).
                         CUSTOMER MODE ONLY — Training never restarts the scanner.
  lower_xspeed_in_good_file()  "same area again and again": X-speed of the lens in
                         use -> 10000 in the GOOD file (backup first), so it sticks.

Which files:
  live  = HDSCANNER_CONFIG from .env, else <HDSCANNER_DIR>/config.ini
  good  = good_config_for(mode): one file per machine per mode, from .env —
          GOOD_CONFIG_BF (Brightfield) / GOOD_CONFIG_FLUO (fluorescence
          and the simulator; on the dev PC a copy of the SIMULATOR's own good config).
          Never the other mode's file. (GOOD_CONFIG below = old single-file setting,
          only for the standalone command line.)

Run standalone:  python customer_config.py [live.ini] [good.ini]     (compare only)
                 python customer_config.py --restore                  (restore + restart)
"""
import configparser
import re
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

from scanner_paths import HDSCANNER_DIR, HDSCANNER_EXE

load_dotenv()

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_CONFIG = os.getenv("HDSCANNER_CONFIG") or os.path.join(HDSCANNER_DIR, "config.ini")
GOOD_CONFIG = os.path.join(   # a relative .env path is relative to the project folder
    _PROJECT_DIR,
    os.getenv("GOOD_CONFIG") or os.path.join("knowledge", "fluorescence_known_good_config.ini"))


# Every backup the copilot makes goes into this folder NEXT TO the file it backs up
# (HDScanner's folder for config.ini, knowledge\ for a good file) — not loose beside
# config.ini, where they piled up (Mishu, 2026-10-08). File names are unchanged.
BACKUP_DIR_NAME = "copilot_config_backup"


def _backup_path(original: str, tag: str) -> str:
    """<folder of original>\\copilot_config_backup\\<name>.<tag>-<time>; the folder is
    created when missing (an OSError here is handled like a failed copy)."""
    folder = os.path.join(os.path.dirname(original), BACKUP_DIR_NAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{os.path.basename(original)}.{tag}-{datetime.now():%Y%m%d-%H%M%S}")


def good_config_for(mode):
    """The good config for the chat MODE on THIS machine, or None when it is not set.

    One file per machine per mode, named after the machine (e.g.
    knowledge/known_good_bf_scanner-A.ini), set in that PC's .env:
      Brightfield                          -> GOOD_CONFIG_BF
      anything else (fluorescence, the sim) -> GOOD_CONFIG_FLUO
    NEVER falls back to the other mode's file or to a default — a missing one is
    None, and the caller refuses with a clear message (2026-09-30: one file per
    machine made Customer mode 'repair' a Brightfield session to fluorescence).
    A relative path is relative to the project folder."""
    name = "GOOD_CONFIG_BF" if mode == "brightfield" else "GOOD_CONFIG_FLUO"
    value = (os.getenv(name) or "").strip()
    return os.path.join(_PROJECT_DIR, value) if value else None


SOCKET_HOST, SOCKET_PORT = "127.0.0.1", 58207   # HDScanner's remote-control socket

# Keys that are ALLOWED to differ from the good file — never compared; on restore
# the live file's own value is kept. (Socket is NOT here: the good file says
# Socket=true, so a live Socket=false is a real fault and gets restored.)
IGNORED_KEYS = {
    # Machine keys: belong to this PC's setup; overwriting them cuts the copilot off.
    ("Scan", "InputPath"),
    ("Scan", "ResultsPath"),
    # This scanner's licence key: another machine's key -> "access security key
    # invalid" (Scanner A got Scanner B's, 2026-09-30).
    ("Controller", "Key"),
    # The scan box: set_scan_area changes these on every scan (Setup → Slide → Scan Region).
    ("Slide", "ScanLeft"),
    ("Slide", "ScanTop"),
    ("Slide", "ScanWidth"),
    ("Slide", "ScanHeight"),
}
# Whole groups of keys that are per-slide data, not settings: [Focus] F0, F1, …
# are focus points saved from whatever slide was scanned last. Never compared, and
# a restore never writes old points back (the live file's own points are kept).
IGNORED_PATTERNS = [("Focus", re.compile(r"F\d+"))]


def _ignored(section: str, key: str) -> bool:
    return ((section, key) in IGNORED_KEYS
            or any(section == s and pat.fullmatch(key or "") for s, pat in IGNORED_PATTERNS))


# Fix A (Scanner A 2026-10-09): CALIBRATION RESULTS — values HDScanner writes when someone
# calibrates the machine (stitching, lens hole focus, field width, slide/stage slope).
# Mishu ran a stitching calibration by hand; the next auto_scan saw [StageSlope20X]
# differ from the good file and put the OLD values back. So these are never restored
# (a restore keeps the live value) and never make the settings "wrong" — they are only
# REPORTED as calibration_differences. The good file gets new calibration values only
# when a person decides they are right.
CALIBRATION_PATTERNS = [
    (re.compile(r"StageSlope\w*"), re.compile(r".+")),                      # [StageSlope20X] …
    (re.compile(r"Lens"), re.compile(r"HoleFocus[XYZ]\d+")),                # lens calibration points
    (re.compile(r"Camera\d*"), re.compile(r"FieldWidth")),                  # field width (auto detect)
    (re.compile(r"Stage"), re.compile(r"SlideSlope[XY]\d+|StageSlope[XY]")),
]


def _calibration(section: str, key: str) -> bool:
    return any(sp.fullmatch(section or "") and kp.fullmatch(key or "")
               for sp, kp in CALIBRATION_PATTERNS)


def _read_ini(path: str) -> configparser.RawConfigParser:
    """Read an HDScanner (Qt) ini file. Keys keep their exact case (Qt is case-
    sensitive), duplicate keys don't crash, and '%' in values is taken literally."""
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    with open(path, "r", encoding="utf-8-sig") as f:   # -sig: tolerate a BOM
        cp.read_file(f)
    return cp


def compare_config(live_path: str = LIVE_CONFIG, good_path: str = GOOD_CONFIG) -> dict:
    """Compare every key of the GOOD file with the LIVE file (ignoring IGNORED_KEYS).
    Keys only in the live file are not checked — HDScanner may add extras.
    Never raises. Returns:
      ok          False only if a file could not be read (see 'error')
      match       True when nothing differs
      checked     how many keys were compared
      differences [{section, key, live, good}]  value is different
      missing     [{section, key, good}]        key absent from the live file
      calibration_differences [{section, key, live, good}]  calibration results that
                  differ — reported only, never part of `match` (fix A)
    """
    try:
        good = _read_ini(good_path)
        live = _read_ini(live_path)
    except (OSError, configparser.Error) as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "live_path": live_path, "good_path": good_path}

    differences, missing, calibration, checked = [], [], [], 0
    for section in good.sections():
        for key, good_value in good.items(section):
            if _ignored(section, key):
                continue
            if _calibration(section, key) and live.has_option(section, key):
                live_value = live.get(section, key)
                if live_value.strip() != good_value.strip():
                    calibration.append({"section": section, "key": key,
                                        "live": live_value, "good": good_value})
                continue
            checked += 1
            if not live.has_option(section, key):
                missing.append({"section": section, "key": key, "good": good_value})
                continue
            live_value = live.get(section, key)
            if live_value.strip() != good_value.strip():
                differences.append({"section": section, "key": key,
                                    "live": live_value, "good": good_value})

    return {
        "ok": True,
        "match": not differences and not missing,
        "checked": checked,
        "differences": differences,
        "missing": missing,
        "calibration_differences": calibration,
        "live_path": live_path,
        "good_path": good_path,
    }


def merge_good_with_live(good_path: str, live: configparser.RawConfigParser) -> str:
    """The good file's text, line for line (same order, comments, line endings),
    except that every ignored key (IGNORED_KEYS / IGNORED_PATTERNS) is taken from
    the live config: its live value is kept, and if the live file doesn't have it,
    the good file's line is dropped (so old per-slide focus points never come back).
    A kept key the good file doesn't have is inserted right under its section header."""
    with open(good_path, "r", encoding="utf-8-sig", newline="") as f:
        lines = f.read().splitlines(keepends=True)
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    good = _read_ini(good_path)

    # Ignored keys AND calibration results keep their live value (fix A); a calibration
    # key missing from the live file still gets the good file's line.
    keep = {(s, k): v for s in live.sections() for k, v in live.items(s)
            if _ignored(s, k) or (_calibration(s, k) and good.has_option(s, k))}
    out, section = [], None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            out.append(line)
            for (s, k), v in keep.items():          # kept keys the good file lacks
                if s == section and not good.has_option(s, k):
                    out.append(f"{k}={v}{nl}")
            continue
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if (section, key) in keep:
            out.append(f"{key}={keep[(section, key)]}{nl}")
        elif key and _ignored(section, key):
            continue                                 # ignored, and not in the live file
        else:
            out.append(line)
    for s in sorted({s for (s, _) in keep if not good.has_section(s)}):   # whole missing sections
        out.append(f"{nl}[{s}]{nl}")
        out.extend(f"{k}={v}{nl}" for (ss, k), v in keep.items() if ss == s)
    return "".join(out)


def _hdscanner_running() -> bool:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq HDScanner.exe", "/NH"],
                       capture_output=True, text=True)
    return "HDScanner.exe" in r.stdout


def stop_hdscanner(timeout_s: float = 15) -> bool:
    """FORCE-close every HDScanner.exe (the window and the -mcp helper). Force, not a
    normal close: HDScanner rewrites config.ini from memory when it exits normally,
    which would overwrite the file we are about to write. True when all are gone."""
    subprocess.run(["taskkill", "/F", "/IM", "HDScanner.exe"], capture_output=True)
    end = time.time() + timeout_s
    while time.time() < end:
        if not _hdscanner_running():
            return True
        time.sleep(0.5)
    return False


def close_hdscanner_normally(timeout_s: float = 30):
    """Close HDScanner like clicking its X, so it WRITES everything it is using —
    including changes made in its window — into config.ini (proven on the real
    scanner 2026-09-26: Focus Density changed in the window to 10, closed with X,
    config.ini said 10; no pop-up). Returns True when the window closed, None when
    no HDScanner window was open (nothing to save), False when it would not close."""
    try:
        import win32con
        import win32gui
    except ImportError:
        return False
    found = []

    def _cb(hwnd, _):
        title = win32gui.GetWindowText(hwnd) or ""
        if win32gui.IsWindowVisible(hwnd) and title.startswith("HDScanner") and "Microscope" in title:
            found.append(hwnd)
    win32gui.EnumWindows(_cb, None)
    if not found:
        return None
    hwnd = found[0]
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    end = time.time() + timeout_s
    while time.time() < end:
        if not win32gui.IsWindow(hwnd):
            time.sleep(2)   # let it finish writing config.ini and exit
            return True
        time.sleep(0.5)
    return False


# Close HDScanner normally before comparing, so changes made in its window are
# checked too (costs a restart, ~1 min, per customer scan). CUSTOMER_LIVE_CHECK=0
# in .env compares the saved file only.
LIVE_CHECK = os.getenv("CUSTOMER_LIVE_CHECK", "1") != "0"


def _socket_up() -> bool:
    try:
        with socket.create_connection((SOCKET_HOST, SOCKET_PORT), timeout=2):
            return True
    except OSError:
        return False


def _wait_for_socket(timeout_s: float) -> bool:
    end = time.time() + timeout_s
    while time.time() < end:
        if _socket_up():
            return True
        time.sleep(2)
    return False


def start_hdscanner(exe: str, timeout_s: float = 90, settle_s: float = 25) -> bool:
    """Start HDScanner as its own process (it keeps running if the copilot server
    stops) and wait until its remote-control socket answers. HDScanner relaunches
    itself ~20 s after a normal start, so after the first answer we wait settle_s and
    check the socket again. True when it is up and staying up."""
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe], cwd=os.path.dirname(exe), creationflags=flags, close_fds=True)
    if not _wait_for_socket(timeout_s):
        return False
    time.sleep(settle_s)
    return _wait_for_socket(timeout_s)


def _other_machine(live_path, good_path):
    """Error text when the good file belongs to ANOTHER scanner (its licence key
    differs from this PC's) — a restore would copy that machine's key and
    calibration here. None = same machine (or a key missing, can't tell)."""
    try:
        live_key = _read_ini(live_path).get("Controller", "Key", fallback=None)
        good_key = _read_ini(good_path).get("Controller", "Key", fallback=None)
    except Exception:
        return None
    if live_key and good_key and live_key.strip() != good_key.strip():
        return (f"The good config ({os.path.basename(good_path)}) belongs to ANOTHER "
                "scanner (different licence key) — nothing restored. Check "
                "GOOD_CONFIG_BF / GOOD_CONFIG_FLUO in .env.")
    return None


def _wrong_mode(good_path, mode):
    """Error text when the good file is the OTHER mode's ([Setup] ImagingFluo:
    true = fluorescence, false = Brightfield). None = right mode, or can't tell
    (key missing — e.g. Scanner B's build), or the SIMULATOR ([Camera]
    Model=CameraSim: no real optics, its mode flag means nothing)."""
    try:
        good = _read_ini(good_path)
    except Exception:
        return None
    flag = good.get("Setup", "ImagingFluo", fallback=None)
    if flag is None or good.get("Camera", "Model", fallback="").strip() == "CameraSim":
        return None
    file_mode = "fluorescence" if flag.strip().lower() == "true" else "brightfield"
    want = "brightfield" if mode == "brightfield" else "fluorescence"
    if file_mode != want:
        return (f"The good config ({os.path.basename(good_path)}) is a {file_mode} file, "
                f"but this is a {want} session — nothing restored. Check "
                "GOOD_CONFIG_BF / GOOD_CONFIG_FLUO in .env.")
    return None


def restore_good_config(live_path: str = LIVE_CONFIG, good_path: str = GOOD_CONFIG,
                        exe: str = HDSCANNER_EXE, live_check: bool = LIVE_CHECK,
                        mode=None) -> dict:
    """Make the scanner run the good settings. Never raises.

    Refuses up front (nothing closed, nothing written) when there is no good
    file for this mode, when it belongs to another scanner (licence key), or —
    with `mode` given — when it is the other mode's file.

    live_check (default): first close HDScanner NORMALLY so it writes what it is
    really using (window changes included) into config.ini; the helper process is
    then force-closed. Then compare every value with the good file:
      - different: back up, write the good values (keeping IGNORED_KEYS), start
        HDScanner, wait, compare again;
      - same: just start HDScanner again (if we closed it).
    Without live_check only the saved file is compared (window changes are missed),
    and HDScanner is force-closed only when something must be restored.

    CUSTOMER MODE ONLY. When HDScanner was restarted ('restarted' or 'restored'),
    the copilot's scanner connections are stale — the caller must reconnect.

    Returns: ok, restored, restarted, fixed (how many settings were changed),
    backup_path, hdscanner_up, after (compare_config after the restart), note/error."""
    t0 = time.time()
    if not good_path:
        return {"ok": False, "restored": False, "restarted": False,
                "error": "No good config is set for this mode on this machine — nothing "
                         "restored. Set GOOD_CONFIG_BF / GOOD_CONFIG_FLUO in .env."}
    wrong = _other_machine(live_path, good_path)
    if not wrong and mode is not None:
        wrong = _wrong_mode(good_path, mode)
    if wrong:
        return {"ok": False, "restored": False, "restarted": False, "error": wrong}
    closed = None
    if live_check:
        closed = close_hdscanner_normally()
        if closed is False:
            return {"ok": False, "restored": False, "restarted": False,
                    "error": "HDScanner would not close normally — settings not checked."}
        stop_hdscanner()        # the windowless -mcp helper, and anything left over

    before = compare_config(live_path, good_path)
    if not before["ok"]:
        up = start_hdscanner(exe) if closed else None
        return {"ok": False, "restored": False, "restarted": bool(closed),
                "hdscanner_up": up, "error": before["error"]}
    # Calibration results that differ from the good file: kept as they are, reported (fix A).
    calib = [f"[{d['section']}] {d['key']}: {d['live']} (good file: {d['good']})"
             for d in before.get("calibration_differences", [])]
    if before["match"]:
        if closed:
            up = start_hdscanner(exe)
            return {"ok": up, "restored": False, "restarted": True, "fixed": 0,
                    "calibration_kept": calib,
                    "hdscanner_up": up, "seconds": round(time.time() - t0, 1),
                    "note": ("All settings match the good file (checked what HDScanner "
                             "was really using); HDScanner started again."
                             if up else "Settings match, but HDScanner did not come back.")}
        return {"ok": True, "restored": False, "restarted": False, "fixed": 0,
                "calibration_kept": calib,
                "note": "Config already matches the good file — nothing to do."}

    try:
        backup_path = _backup_path(live_path, "customer-backup")
        shutil.copy2(live_path, backup_path)
    except OSError as e:   # no backup → do not touch anything
        up = start_hdscanner(exe) if closed else None
        return {"ok": False, "restored": False, "restarted": bool(closed),
                "hdscanner_up": up, "error": f"Backup failed, nothing changed: {e}"}

    if not closed and not stop_hdscanner():
        return {"ok": False, "restored": False, "backup_path": backup_path,
                "error": "HDScanner would not close — config not changed."}

    try:
        live = _read_ini(live_path)
        text = merge_good_with_live(good_path, live)
        with open(live_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except (OSError, configparser.Error) as e:
        shutil.copy2(backup_path, live_path)   # put the old file back before restarting
        start_hdscanner(exe)
        return {"ok": False, "restored": False, "backup_path": backup_path,
                "error": f"Writing the good config failed, old file put back: {e}"}

    up = start_hdscanner(exe)
    after = compare_config(live_path, good_path)
    return {
        "ok": up and after.get("match", False),
        "restored": True,
        "restarted": True,
        "fixed": len(before["differences"]) + len(before["missing"]),
        "fixed_settings": [f"[{d['section']}] {d['key']}: {d['live']} -> {d['good']}"
                           for d in before["differences"]]
                          + [f"[{m['section']}] {m['key']}: missing -> {m['good']}"
                             for m in before["missing"]],
        "calibration_kept": calib,
        "backup_path": backup_path,
        "hdscanner_up": up,
        "after": after,
        "seconds": round(time.time() - t0, 1),
        "note": ("Restored and HDScanner is back." if up and after.get("match")
                 else "HDScanner did not come back." if not up
                 else "HDScanner is back but the config still differs after its restart."),
    }


# "Scans the same area again and again": the scan keeps starting over from the first row.
# Fix: lower the X-speed of the lens in use to a safe value, in one go.
# (How the safe value is worked out is field know-how and kept private.)
# The value below is the one used on our scanners.
SAFE_XSPEED = 10000


def lower_xspeed_in_good_file(good_path, target=SAFE_XSPEED) -> dict:
    """Write the safe X-speed for the lens IN USE into the GOOD file, so the next
    restore_good_config puts it into the scanner and every later scan keeps it (only
    the live file = the problem comes back on the next restore). Never raises.

    Lens in use = [Lens] CurrentHole -> HoleMag<n> (e.g. 20X) -> [Stage] SpeedX20X.
    Backs the good file up first (copilot_config_backup/<good>.speedfix-backup-<time>); changes ONLY that
    one line, everything else stays byte for byte.

    Returns ok, changed, lens, key, old, new, backup_path, error:
      changed=True   the value was above target and is now target
      changed=False  already at/below target -> X-speed is not the cause (USB cable)"""
    if not good_path or not os.path.exists(good_path):
        return {"ok": False, "changed": False,
                "error": "No good config for this mode on this machine — X-speed not changed."}
    try:
        good = _read_ini(good_path)
    except (OSError, configparser.Error) as e:
        return {"ok": False, "changed": False, "error": f"Could not read the good config: {e}"}
    hole = good.get("Lens", "CurrentHole", fallback="").strip()
    lens = good.get("Lens", f"HoleMag{hole}", fallback="").strip() if hole else ""
    key = f"SpeedX{lens}"
    if not lens or not good.has_option("Stage", key):
        return {"ok": False, "changed": False, "lens": lens or None, "key": key,
                "error": f"Could not tell the X-speed of the lens in use (CurrentHole={hole!r}, "
                         f"lens={lens!r}, no [Stage] {key}) — nothing changed."}
    old_text = good.get("Stage", key).strip()
    try:
        old = float(old_text)
    except ValueError:
        return {"ok": False, "changed": False, "lens": lens, "key": key,
                "error": f"[Stage] {key}={old_text!r} is not a number — nothing changed."}
    result = {"ok": True, "lens": lens, "key": key, "old": old_text, "new": old_text}
    if old <= target:
        return {**result, "changed": False}

    try:
        backup_path = _backup_path(good_path, "speedfix-backup")
        shutil.copy2(good_path, backup_path)
    except OSError as e:     # no backup -> do not touch the good file
        return {**result, "ok": False, "changed": False,
                "error": f"Backup of the good config failed, nothing changed: {e}"}
    try:
        with open(good_path, "r", encoding="utf-8-sig", newline="") as f:
            lines = f.read().splitlines(keepends=True)
        out, section, done = [], None, False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1]
            elif (section == "Stage" and not done and "=" in line
                  and line.split("=", 1)[0].strip() == key):
                ending = line[len(line.rstrip("\r\n")):]
                line, done = f"{key}={target}{ending}", True
            out.append(line)
        with open(good_path, "w", encoding="utf-8", newline="") as f:
            f.write("".join(out))
        now = _read_ini(good_path).get("Stage", key).strip()
    except (OSError, configparser.Error) as e:
        shutil.copy2(backup_path, good_path)     # put the old good file back
        return {**result, "ok": False, "changed": False, "backup_path": backup_path,
                "error": f"Writing the good config failed, old file put back: {e}"}
    if not done or now != str(target):
        shutil.copy2(backup_path, good_path)
        return {**result, "ok": False, "changed": False, "backup_path": backup_path,
                "error": f"[Stage] {key} did not read back as {target} — old file put back."}
    return {**result, "changed": True, "new": now, "backup_path": backup_path}


if __name__ == "__main__":
    if sys.argv[1:] == ["--restore"]:
        r = restore_good_config()
        print({k: v for k, v in r.items() if k != "after"})
        if "after" in r:
            a = r["after"]
            print(f"after restart: match={a.get('match')} "
                  f"different={len(a.get('differences', []))} missing={len(a.get('missing', []))}")
        sys.exit(0 if r["ok"] else 1)

    live_path = sys.argv[1] if len(sys.argv) > 1 else LIVE_CONFIG
    good_path = sys.argv[2] if len(sys.argv) > 2 else GOOD_CONFIG
    r = compare_config(live_path, good_path)
    print(f"live: {r['live_path']}\ngood: {r['good_path']}")
    if not r["ok"]:
        print("ERROR:", r["error"])
        sys.exit(1)
    print(f"checked {r['checked']} keys -> "
          f"{'MATCH' if r['match'] else 'DIFFERENT'}: "
          f"{len(r['differences'])} different, {len(r['missing'])} missing")
    for d in r["differences"][:15]:
        print(f"  [{d['section']}] {d['key']}: live={d['live']!r}  good={d['good']!r}")
    for m in r["missing"][:5]:
        print(f"  [{m['section']}] {m['key']}: MISSING (good={m['good']!r})")
    extra = max(len(r["differences"]) - 15, 0) + max(len(r["missing"]) - 5, 0)
    if extra > 0:
        print(f"  ... and {extra} more")
