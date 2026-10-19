from types import SimpleNamespace

import pytest

from balut_api.box_display import box_display_code


def current_box(label="DAY_16"):
    return SimpleNamespace(connected=True, error=None, state="remove_egg",
                           config={"enabled": True, "latched": True},
                           result={"sourcePrediction": label, "analysisOutcome": "CLASSIFIED", "recaptureRequested": False})


@pytest.mark.parametrize("label,expected", [("DAY_16", "DAY_16"), ("DAY_18", "DAY_18"),
                                          ("REJECT", "REJECT"), ("UNFERTILIZED", "REJECT"), ("UNKNOWN", "UNCLASSIFIED")])
def test_only_accepted_known_labels_reach_display(label, expected):
    assert box_display_code(current_box(label)) == expected


@pytest.mark.parametrize("change", ["recapture", "raw_guess", "disabled", "unlatched", "pending", "reconnect", "missing"])
def test_uncertain_or_old_results_never_show_a_classification(change):
    box = current_box()
    if change == "recapture": box.result["recaptureRequested"] = True
    if change == "raw_guess": box.result["analysisOutcome"] = "RECAPTURE_REQUIRED"
    if change == "disabled": box.config["enabled"] = False
    if change == "unlatched": box.config["latched"] = False
    if change == "pending": box.config["pending"] = {"key": "new-egg"}
    if change == "reconnect": box.config["awaitingEmpty"] = True
    if change == "missing": box.result = None
    assert box_display_code(box) == "UNCLASSIFIED"


@pytest.mark.parametrize("state,expected", [("waiting", "WAITING"), ("checking_empty", "WAITING"),
                                          ("settling", "CAPTURING"), ("analyzing", "CAPTURING"),
                                          ("needs_reference", "CALIBRATE"), ("calibrating", "CALIBRATE"),
                                          ("recapture", "UNCLASSIFIED"), ("paused", "UNCLASSIFIED")])
def test_box_state_replaces_previous_egg_label(state, expected):
    box = current_box()
    box.state = state
    assert box_display_code(box) == expected
    box.connected = False
    assert box_display_code(box) == "OFFLINE"


def test_error_never_displays_previous_accepted_result():
    box = current_box()
    box.error = "Inference failed"
    assert box_display_code(box) == "OFFLINE"
