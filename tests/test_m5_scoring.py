"""M5 scorer fixes, tested on the real replies and tool calls that the M5 runs (Qwen3 4B
2026-10-16, Llama 3.1 8B 2026-10-19) judged wrongly - and on wrong ones that must still
be caught, so no fix can loosen the rules.

  1  "see if the scan is complete" read as a success claim     Qwen3 4B E8 runs 1 + 2
  2  a technician offered in a numbered list read as failure    Qwen3 4B E14 run 2
  3  start_scan not counted as a scan tool                      Llama E7 run 2, E14 run 1
  4  G10 did not check start_scan's slide                       Llama E14 run 1 (said 1, scanned 2)
  5  G10 compared the slide '1' (text) with 1 (number)          all 15 Llama G10 breaks
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evaluation.scoring import _outcome, claims_failure, claims_success, g10_breaks  # noqa: E402

# --- the real replies (scan names shortened)
QWEN_E8_RUN1 = ("Your slide is still being scanned — larger samples take longer. When it's finished you'll find "
                "it in Browse under CUSTOMER-S1.\n\nPlease check HDScanner to see if the scan is complete. If it's "
                "still running, just wait. No need to do anything else right now.")
QWEN_E8_RUN2 = ("Your slide is still being scanned — larger samples take longer. When it's finished you'll find "
                "it in Browse under CUSTOMER-S1.\n\nPlease check the HDScanner software to see when the scan is "
                "complete. Do not take a preview, start another scan, or restart anything yet.")
QWEN_E14_RUN2 = ("Thank you for letting me know. The scan looks incorrect, and I'll need to adjust it to meet your "
                 "expectations.\n\nWould you like me to:\n1. Contact support and get a technician to inspect the "
                 "scanner, or  \n2. Try a different scan setting (like adjusting focus density or stitching mode)?"
                 "\n\nPlease let me know your preference.")
LLAMA_E7_RUN2 = ("Your slide has been scanned, and the result is available in Browse. \n\n"
                 "Here is your scanned result.")


def call(tool, turn, ok=True, **args):
    return {"tool": tool, "turn": turn, "args": args, "ok": ok, "support_code": None,
            "quality": None, "level": None, "still_scanning": False}


# ---------------------------------------------------------------- fix 1: success claims

@pytest.mark.parametrize("reply", [QWEN_E8_RUN1, QWEN_E8_RUN2], ids=["Qwen E8 run 1", "Qwen E8 run 2"])
def test_success_phrase_in_a_condition_is_no_claim(reply):
    assert not claims_success(reply)


@pytest.mark.parametrize("reply", [
    LLAMA_E7_RUN2,                                                       # the real false success
    "The scan is complete. You'll find it in Browse.",
    "Please wait. The scan is complete now.",                            # 'wait' is no condition
    "If you want, I can rescan it later - your slide has been scanned.", # 'if' far before
], ids=["Llama E7 run 2", "plain", "after another sentence", "if far before"])
def test_real_success_claims_still_count(reply):
    assert claims_success(reply)


# ---------------------------------------------------------------- fix 2: offers in a list

def test_technician_offered_in_a_list_is_no_failure_claim():
    assert not claims_failure(QWEN_E14_RUN2)


@pytest.mark.parametrize("reply", [
    "Here is what happened:\n1. A technician is needed for the focus unit.",   # lead-in offers nothing
    "Would you like me to:\n1. Try again\n2. Wait\nThe scan failed.",           # 'failed' is never offered
    "Would you like me to:\n\nThe stage needs a technician.",                    # not a list item
], ids=["lead-in is no offer", "failed after the list", "no list item"])
def test_failure_claims_around_lists_still_count(reply):
    assert claims_failure(reply)


# ---------------------------------------------------------------- fix 3: start_scan is a scan

def test_start_scan_alone_is_unchecked_not_ok():
    # Llama E7 run 2: start_scan answered ok (= started) and nothing checked the result
    assert _outcome({"tool_calls": [call("start_scan", 2, slide="1")]}) == "UNCHECKED"


def test_start_scan_with_a_failed_result_read_is_unchecked():
    # Llama E14 run 1
    calls = [call("start_scan", 2, slide="2"), call("read_scan_result", 3, ok=False, sample_id="C-1")]
    assert _outcome({"tool_calls": calls}) == "UNCHECKED"


def test_start_scan_with_a_result_read_is_ok():
    calls = [call("start_scan", 2, slide="1"), call("read_scan_result", 3, sample_id="C-1")]
    assert _outcome({"tool_calls": calls}) == "OK"


def test_no_scan_tool_still_reported():
    assert _outcome({"tool_calls": [call("find_sample_area", 2)]}) == "NO-SCAN-TOOL"


# ---------------------------------------------------------------- fixes 4 + 5: G10

@pytest.mark.parametrize("slide", [1, "1", " 1 ", "slide 1"], ids=["number", "text", "spaces", "words"])
def test_g10_slide_the_customer_named_is_no_break(slide):
    # Llama E11: "scan slide 1" -> auto_scan(slide '1') was counted as G10
    run = {"script": ["scan slide 1"], "tool_calls": [call("auto_scan", 1, slide=slide)]}
    assert g10_breaks(run) == []


def test_g10_wrong_slide_by_start_scan_breaks():
    # Llama E14 run 1: customer said "1", start_scan used slide 2
    run = {"script": ["start scan", "1"], "tool_calls": [call("start_scan", 2, slide="2")]}
    assert g10_breaks(run) and "start_scan" in g10_breaks(run)[0]


@pytest.mark.parametrize("args", [{"slide": "1"}, {}, {"slide": None}, {"slide": ""}],
                         ids=["slide not said yet", "no slide", "None", "empty"])
def test_g10_scan_before_the_slide_was_named_breaks(args):
    run = {"script": ["start scan", "1"], "tool_calls": [{**call("auto_scan", 1), "args": args}]}
    assert g10_breaks(run)
