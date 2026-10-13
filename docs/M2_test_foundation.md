# M2 — Test foundation

**Milestone:** M2 of the [roadmap](../ROADMAP.md) · **Builds on:** [M1 — Definition of "correct"](M1_definition_of_correct.md)

M2 tests every part of the co-pilot that can be checked **without the LLM and
without the scanner**: deterministic logic where the same input must always give
the same output. Each test is named after the M1 rule (`G…`) or failure mode
(`F…`) it proves, so a failing test points straight at the requirement it breaks.

```
python -m pytest        # all pass, 1 expected failure (F20), ~15 s
```

The same tests and the leak check run on GitHub Actions on every push.

---

## What is tested

| Group | Module (in `copilot_core/`) | Tests | Proves |
|---|---|---|---|
| B. Config safety guards | `customer_config.py` | 16 | Another machine's config or licence key is refused **before anything is written** (F01); the other imaging mode is refused, with no silent fallback (F02); per-slide data is not treated as settings (F23); missing or unreadable files are reported, not raised (G9, G10) |
| C. Scan result reading | `scan_reader.py` | 8 | The status flag is reported raw, never as a verdict (F03); results are found in this machine's folder (F04); missing fields stay missing (G1) |
| D. Geometry and bounds | `scanner_sample_area.py` | 8 | Scale comes from the machine's own slide size, separately per axis (F24); boxes never leave the slide (G8); no sample means no box (G3) |
| E. Focus point chooser | `scanner_focus_points_bf.py` | 12 | Points lie on the safe part of the sample and inside the scan box (F10, G8); 3 points form a triangle, never a line; no disc means no points (G3) |
| F. Sample finder | `scanner_find_samples_bf.py`, `scanner_find_samples_fluo.py` | 8 | The sample is found where it is; a printed logo is not taken for a sample (F19); empty and very faint slides give "not found", never a guess (G3, F20) |
| Safety of the suite | — | 4 | A test can never close, kill or start a real program |

**Coverage of M1:** 9 of the 27 failure modes (F01, F02, F03, F04, F10, F19,
F20, F23, F24) and 8 of the 12 global rules (G1, G2, G3, G5, G6, G8, G9, G10)
are covered by unit tests. The rest
depend on how the **machine** behaves (events, dialogs, timing, GUI) and are
tested in M3/M4 against the virtual instrument and the real scanner.

## Design decisions

- **Synthetic data only.** Configs with made-up keys, previews drawn by the test
  (a slightly darker disc with small dark "cells", a printed mark, a magenta
  square). No real scanner file is used: the tests run anywhere and leak nothing.
- **Open problems stay visible.** F20 (very faint samples are missed) is open.
  It has a test marked *expected to fail* (`xfail`, strict). When someone fixes
  F20, that test starts passing, pytest reports it, and the marker must be
  removed. An open problem cannot be quietly forgotten.
- **The suite cannot touch a machine.** `customer_config.py` can force-close and
  restart the scanner software. `tests/conftest.py` replaces every process call
  with one that fails the test, and `test_safety_block.py` proves the block works.
- **Copies, not history.** The modules are copied from the private co-pilot by
  [`tools/sync_from_private.py`](../tools/sync_from_private.py), which rewrites
  machine-specific names and refuses to write anything that fails the leak check.
  Git history is never shared, because old commits can contain secrets.

## Proof that a test works

[Mutation-test demo](demo_mutation_test.md): the F01 guard is switched off in a
temporary copy, and the F01 test fails, exactly as it should. CI repeats this on
every push (`tools/demo_mutation_test.py`).

## What the tests found

No defect in the co-pilot code. One test had wrong test data (a box that
actually stuck out of the slide); the code was right and the test was fixed.
That is a reminder that tests need reviewing too.
