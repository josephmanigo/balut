import numpy as np
import pytest
from balut_ml.scientific_metrics import classification_metrics, repeatability, cluster_intervals


def attempt(scores, prediction="DAY_16", recapture=False):
    return {"score_vector": scores, "result": {"sourcePrediction": prediction,
            "analysisOutcome": "RECAPTURE_REQUIRED" if recapture else "CLASSIFIED", "recaptureRequested": recapture}}


def test_metrics_match_actual_baseline_counts_and_keep_abstentions_separate():
    value = classification_metrics([[249,36,0],[63,227,0],[0,0,74]], [[165,3,0,117],[18,201,0,71],[0,0,57,17]])
    assert value["raw_accuracy"] == 550/649 and value["accepted_accuracy"] == 423/444
    assert value["correct_over_all"] == 423/649 and value["coverage"] == 444/649
    assert value["per_class"][0] == {"class_index":0,"support":285,"TP":249,"FP":63,"FN":36,"TN":301,
                                      "precision":249/312,"recall":249/285,"f1":498/597}
    assert value["weighted_f1"] == pytest.approx((285*498/597+290*454/553+74)/649)


def test_any_score_change_fails_even_when_class_and_winning_score_do_not_change():
    a = attempt([5.,1.,0.]*3); b = attempt([5.,1.,0.]*2 + [5.,1.,1e-12])
    measured = repeatability([a,b],2)
    assert measured["class_agreement"] == measured["decision_agreement"] == 1.
    assert measured["maximum_score_difference"] == 1e-12 and not measured["strict_zero_gap_passed"]
    assert repeatability([a,a],2)["strict_zero_gap_passed"]
    assert not repeatability([a,a,{"error":"capture failed"}],3)["strict_zero_gap_passed"]


def test_zero_denominators_and_population_mismatch_are_explicit():
    value = classification_metrics([[1,0,0],[0,0,0],[0,0,0]], [[0,0,0,1],[0,0,0,0],[0,0,0,0]])
    assert value["accepted_accuracy"] is None and not value["all_classes_represented"]
    with pytest.raises(ValueError,match="populations"):
        classification_metrics(np.eye(3),np.zeros((3,4)))


def test_cluster_bootstrap_keeps_repeated_egg_views_together():
    rows=[]
    for egg,correct in [("a",True),("b",False)]:
        rows += [{"physical_egg_id":egg,"truth":"DAY_16","raw_prediction":"DAY_16" if correct else "DAY_18",
                  "sourcePrediction":"DAY_16" if correct else "DAY_18"}]*50
    value=cluster_intervals(rows,["DAY_16","DAY_18","UNFERTILIZED"],repeats=100,seed=42)
    assert value["clusters"] == 2 and value["intervals"]["raw_accuracy"] == {"lower":0.,"upper":1.}
