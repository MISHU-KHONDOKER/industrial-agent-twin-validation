"""Which M4 scenario a RECORDED real conversation follows (tools/m4_real_recorded.py).

Selection must be mechanical: the customer's messages match the scenario script, and a
slide number 1-4 matches any slide number - alone ("2") or inside a sentence ("scan slide 2").
Anything else is not the scenario and must not be counted as one.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from m4_real_recorded import matches  # noqa: E402


@pytest.mark.parametrize("script, users", [
    (["start scan", "1"], ["start scan", "2"]),                    # E1 on slide 2
    (["start scan", "1"], ["Start scan ", "3", "thanks"]),          # case, spaces, a later message
    (["scan slide 1"], ["scan slide 2"]),                           # E11: number inside the sentence
    (["开始扫描", "1"], ["开始扫描", "2"]),                          # E12
], ids=["E1 slide 2", "E1 case and extra", "E11 slide 2", "E12 slide 2"])
def test_follows_the_script(script, users):
    assert matches(script, users)


@pytest.mark.parametrize("script, users", [
    (["start scan", "1"], ["start scan"]),                          # script not finished
    (["start scan", "1"], ["start scan on slide 3", "3"]),          # different words
    (["scan slide 1"], ["scan slide 2 please"]),                    # extra words
    (["scan slide 1"], ["scan slide 12"]),                          # not a slide number
    (["start scan", "1"], ["start scan", "5"]),                     # no such slide
], ids=["unfinished", "other words", "extra words", "12", "slide 5"])
def test_does_not_follow_the_script(script, users):
    assert not matches(script, users)
