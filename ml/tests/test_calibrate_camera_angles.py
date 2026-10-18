from balut_ml.calibrate_camera_angles import tighten_margins


def test_calibration_only_raises_the_margin_for_a_wrongly_accepted_label():
    policy = {"minimum_margin": {"DAY_16": 2.6, "DAY_18": 2.7, "REJECT": 0}, "quality": {"unchanged": True}}
    outcomes = [{"sourcePrediction": "DAY_18", "source_label": "DAY_16", "decisionMargin": 3.1},
                {"sourcePrediction": "DAY_16", "source_label": "DAY_16", "decisionMargin": 9},
                {"sourcePrediction": None, "source_label": "DAY_18", "decisionMargin": 10}]
    calibrated = tighten_margins(policy, outcomes)
    assert policy["minimum_margin"]["DAY_18"] == 2.7
    assert calibrated["minimum_margin"] == {"DAY_16": 2.6, "DAY_18": 3.1001000000000003, "REJECT": 0}
    assert calibrated["quality"] == policy["quality"]
