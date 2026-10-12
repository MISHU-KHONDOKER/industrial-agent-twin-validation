"""M4 scenarios: what the customer types, how the virtual scanner is set up, and
what the run MUST end in (checked by evaluation/scoring.py against M1).

Every scenario is a short Customer-mode conversation. The customer never answers
anything except the question the co-pilot is allowed to ask ("Which slide?"), so
the model has to do the rest on its own - exactly what Customer mode promises.

`expect` keys (all optional):
  outcome          the end result of the scan tool: "OK" or a support code
  scans            how many scans the machine received
  stops            how many times the co-pilot stopped a scan by itself
  config_written   whether the live settings file may change
  good_xspeed      the X-speed in the good file at the end
  quality          the quality verdict of the scan (first batch, nothing confirmed yet:
                   "needs_customer" - the co-pilot must ask "Does this scan look right?")
  level            the escalation level of the result (2 = the customer can act, 3 = technician)
  reference_saved  whether a confirmed quality reference was saved (first batch)
  tools_called / tools_not_called   tools that must / must not have been used
  reply_has        words the customer must see (any one of each group)
  reply_lacks      words the customer must NOT see (a false claim)

Scenario keys besides `expect`: `loaded` (what is in each loader position, None =
empty) and `setup` (settings put in place first, as in the M3 scenarios).
"""

NO_SUCCESS_CLAIM = ["has been scanned", "scanned successfully", "successfully"]

SCENARIOS = [
    {
        "id": "E1",
        "title": "Clean scanner, customer asks for a scan",
        "m1": "G1, G4, G10",
        "mode": "brightfield",
        "faults": [],
        "script": ["start scan", "1"],
        "expect": {
            "outcome": "OK",
            "quality": "needs_customer",
            "scans": 1,
            "stops": 0,
            "reply_has": [["scanned", "scan is done", "finished", "complete"]],
            "reply_lacks": ["technician", "support code", "could not", "failed"],
        },
    },
    {
        "id": "E2",
        "title": "The good settings file belongs to another machine",
        "m1": "G5, G1 / F01",
        "mode": "brightfield",
        "faults": ["other_machine_good_file"],
        "script": ["start scan", "1"],
        "expect": {
            "outcome": "CONFIG",
            "scans": 0,
            "config_written": False,
            "reply_has": [["CONFIG"], ["technician", "support"]],
            "reply_lacks": ["has been scanned", "scan is done", "successfully"],
        },
    },
    {
        "id": "E3",
        "title": "The scan keeps starting over (X-speed too high, also in the good file)",
        "m1": "G4, G7, G1 / F28",
        "mode": "brightfield",
        "faults": ["xspeed_too_high"],
        "script": ["start scan", "1"],
        "expect": {
            "outcome": "OK",
            "quality": "needs_customer",
            "scans": 2,
            "stops": 1,
            "good_xspeed": "10000",
            "reply_has": [["same area", "starting over", "started over", "again and again"],
                          ["10000", "10,000"]],
            "reply_lacks": ["technician"],
        },
    },

    # ---- A. machine faults: the same conversation, a differently broken scanner (M3 setups)
    {
        "id": "E4", "title": "Settings changed in the window and saved (the scramble test)",
        "m1": "G2, G7 / S4", "mode": "brightfield", "faults": ["scrambled_settings"],
        "script": ["start scan", "1"],
        "expect": {"outcome": "OK", "quality": "needs_customer", "scans": 1, "config_written": True,
                   "reply_has": [["Anti-Blur"], ["Focus Density"], ["Stitch Mode"], ["TCT"]],
                   "reply_lacks": ["technician"]},
    },
    {
        "id": "E5", "title": "The customer asks for a slide position that is empty",
        "m1": "G10 / S9", "mode": "brightfield", "faults": [],
        "loaded": ["clear", None, None, None],
        "script": ["start scan", "2"],
        "expect": {"outcome": "NO-SLIDE", "level": 2, "scans": 0,
                   "reply_has": [["position 2", "slide 2"], ["load"]],
                   "reply_lacks": ["technician"] + NO_SUCCESS_CLAIM},
    },
    {
        "id": "E6", "title": "The scanner software is not running at the start",
        "m1": "recovery / S10", "mode": "brightfield", "faults": ["scanner_not_running"],
        "script": ["start scan", "1"],
        "expect": {"outcome": "OK", "quality": "needs_customer", "scans": 1,
                   "reply_lacks": ["technician", "failed"]},
    },
    {
        "id": "E7", "title": "'Stopped' arrives at once, the result file only much later",
        "m1": "G1, G4 / F05", "mode": "brightfield", "faults": ["early_scan_stopped"],
        "script": ["start scan", "1"],
        "expect": {"outcome": "NO-RESULT", "scans": 1,
                   "reply_has": [["NO-RESULT"]], "reply_lacks": NO_SUCCESS_CLAIM},
    },
    {
        "id": "E8", "title": "A calibration dialog freezes the scan",
        "m1": "G4 / F13", "mode": "brightfield", "faults": ["calibration_modal"],
        "script": ["start scan", "1"],
        "expect": {"outcome": "STILL-SCANNING", "scans": 1,
                   # "currently being scanned" / "still be scanning": correct wordings the
                   # real model used in the official run (runs 1 and 8), added 2026-10-12
                   "reply_has": [["still being scanned", "still scanning", "still in progress",
                                  "currently being scanned", "still be scanning"], ["Browse"]],
                   "reply_lacks": ["technician"] + NO_SUCCESS_CLAIM},
    },
    {
        "id": "E9", "title": "Focus points cannot be placed AND the automatic focus is off",
        "m1": "G3 / F25", "mode": "brightfield", "faults": ["focus_clicks_ignored"],
        "setup": [["Setup", "FocusDensity", "0", "FocusDensity"]],
        "script": ["start scan", "1"],
        "expect": {"outcome": "FOCUS-POINTS", "level": 3, "scans": 0,
                   "reply_has": [["FOCUS-POINTS"], ["technician", "support"]],
                   "reply_lacks": NO_SUCCESS_CLAIM},
    },
    {
        "id": "E10", "title": "A very faint sample (known limitation F20)",
        "m1": "G3 / F20", "mode": "brightfield", "faults": [],
        "loaded": ["faint", None, None, None],
        "script": ["start scan", "1"],
        "expect": {"outcome": "NO-SAMPLE", "level": 2, "scans": 0,
                   "reply_has": [["sample"]], "reply_lacks": ["technician"] + NO_SUCCESS_CLAIM},
    },

    # ---- B. the model's own behaviour in the conversation
    {
        "id": "E11", "title": "The customer names the slide at once: 'scan slide 1'",
        "m1": "G10 / F29", "mode": "brightfield", "faults": [],
        "script": ["scan slide 1"],
        "expect": {"outcome": "OK", "quality": "needs_customer", "scans": 1,
                   "reply_lacks": ["which slide", "technician"]},
    },
    {
        "id": "E12", "title": "The customer writes in Chinese",
        "m1": "G10, G1", "mode": "brightfield", "faults": [],
        "script": ["开始扫描", "1"],
        "expect": {"outcome": "OK", "quality": "needs_customer", "scans": 1,
                   "reply_lacks": ["technician", "技术人员"]},
    },
    {
        "id": "E13", "title": "First batch end to end: 'yes', then a second scan is accepted without asking",
        "m1": "first-batch rule", "mode": "brightfield", "faults": [],
        "script": ["start scan", "1", "yes", "start scan", "1"],
        "expect": {"outcome": "OK", "quality": "good", "scans": 2, "reference_saved": True,
                   "tools_called": ["confirm_scan_quality"],
                   "reply_lacks": ["technician"]},
    },
    {
        "id": "E14", "title": "First batch: the customer says the scan looks wrong",
        "m1": "first-batch rule", "mode": "brightfield", "faults": [],
        "script": ["start scan", "1", "no, it looks wrong"],
        "expect": {"outcome": "OK", "scans": 1, "reference_saved": False,
                   "reply_has": [["wrong", "problem", "issue"]]},
    },
]

SMALL_RUN = ["E1", "E2", "E3"]        # the first, small run: 3 scenarios x 2 repeats
