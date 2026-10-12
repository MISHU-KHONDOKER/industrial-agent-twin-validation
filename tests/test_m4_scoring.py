"""M4 scorer: the reply word rules, tested on the real replies that the first official
run (2026-10-08, 14 scenarios x 10) judged wrongly - and on wrong replies that must
still be caught, so the fix cannot loosen the rules.

Four of the five problem runs were mistakes of the SCORER, not of the co-pilot:
  E8 run 1 / run 8   correct "still scanning" message, wording not in the list
  E13 run 8          "no failed focus points" read as a failure claim
  E14 run 7          a technician OFFERED as a next step read as a failure claim
The fifth (E4 run 5: settings changed but not told) is a real co-pilot defect and must
stay a failure.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evaluation.scenarios import SCENARIOS  # noqa: E402
from evaluation.scoring import claims_failure, reply_failures  # noqa: E402

EXPECT = {s["id"]: s["expect"] for s in SCENARIOS}

# --- the real replies from the official run (scan names shortened)
E8_RUN1 = ("One moment — your slide is currently being scanned. Larger samples take longer, so please "
           "give it a little time.\n\nWhen it's finished, you'll find it in Browse under **CUSTOMER-S1**. "
           "If you'd like, just ask me again in a few minutes and I'll check how it went.")
E8_RUN8 = ("Your slide was set up and the scan was started, but the scanner didn't confirm back to me whether "
           "it has finished — it may well still be scanning. Please take a look at the scanner screen and let me "
           "know what you see.\n\nI won't touch anything else in the meantime. You'll find the result later in "
           "Browse under CUSTOMER-S1.")
E8_RUN2 = ("Your slide is still being scanned — larger samples take longer. When it's finished you'll find it "
           "in Browse under **CUSTOMER-S1**.")
E13_RUN8 = "Your slide is scanned — it finished with all 132 images captured and no failed focus points."
E14_RUN7 = ("I'm sorry the scan didn't look right. Could you tell me what looks wrong — for example, is it blurry, "
            "is the wrong area showing, or does something look missing? Based on that I can either try again "
            "or get a technician involved.")
E4_RUN5 = ("Your slide has been scanned. You can find it in Browse under **CUSTOMER-S1**.\n\n"
           "Does this scan look right to you?")


# ---------------------------------------------------------------- E8 word rule

@pytest.mark.parametrize("reply", [E8_RUN1, E8_RUN8, E8_RUN2], ids=["E8 run 1", "E8 run 8", "E8 run 2"])
def test_e8_correct_still_scanning_replies_pass(reply):
    assert reply_failures(EXPECT["E8"], reply) == []


@pytest.mark.parametrize("reply", [
    "Your slide has been scanned. You'll find it in Browse.",          # a false 'done'
    "The scan is in Browse.",                                           # no 'still scanning'
    "Your slide is still being scanned.",                               # no 'Browse'
    "It is still scanning. Please call a technician. It is in Browse.", # technician not allowed
], ids=["false done", "no still-scanning", "no Browse", "technician"])
def test_e8_wrong_replies_still_fail(reply):
    assert reply_failures(EXPECT["E8"], reply) != []


# ---------------------------------------------------------------- failure claims

@pytest.mark.parametrize("reply", [E13_RUN8, E14_RUN7, E8_RUN2,
                                   "The scan finished without failed images.",
                                   "Would you like me to get a technician involved?"],
                         ids=["E13 run 8", "E14 run 7", "E8 run 2", "without failed", "technician offered"])
def test_no_failure_claim(reply):
    assert claims_failure(reply) is False


@pytest.mark.parametrize("reply", [
    "The scan failed.",
    "I couldn't finish the scan.",
    "I could not find the sample.",
    "2 focus points failed, so I stopped.",
    "I'm sorry - this needs a technician. Please give them this code: CONFIG.",
    "Please contact a technician and give them the support code CONFIG.",
    "If you see this again: the scan failed because the scanner was busy.",  # 'failed' is never exempt
], ids=["failed", "couldn't", "could not", "points failed", "needs technician", "contact technician", "failed after if"])
def test_failure_claim_is_still_caught(reply):
    assert claims_failure(reply) is True


# ---------------------------------------------------------------- the real defect

def test_e4_settings_not_told_is_still_a_failure():
    """E4 run 5: the co-pilot corrected four settings but did not say so. The scorer
    must keep calling this a failure."""
    assert len(reply_failures(EXPECT["E4"], E4_RUN5)) == 4
