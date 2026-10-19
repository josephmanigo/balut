import numpy as np

from balut_ml.train_unfertilized import CLASSES, calibrate, fit_weights


def test_effective_classes_balance_without_giving_more_views_more_egg_weight():
    rows = [dict(source_label="DAY_16", physical_egg_id="16-1"),
            dict(source_label="DAY_16", physical_egg_id="16-2"),
            dict(source_label="DAY_16", physical_egg_id="16-2"),
            dict(source_label="DAY_18"), dict(source_label="UNFERTILIZED")]
    weights = fit_weights(rows, 20)
    np.testing.assert_allclose(weights[0], weights[1:3].sum())
    for label in CLASSES:
        np.testing.assert_allclose(sum(w for row,w in zip(rows,weights) if row["source_label"]==label), len(rows)/3)


def test_no_margin_support_disables_a_class_instead_of_forcing_a_prediction():
    truth = np.repeat(np.arange(3), 6)
    features = np.eye(3)[truth]
    scores = features * 3
    scores[0] = [0,7,0]
    quality = dict(minimum_short_side=64,minimum_grayscale_std=8,minimum_edge_variance=20,maximum_clipped_fraction=.85)
    policy = calibrate(scores,truth,features,np.eye(3),np.arange(3),quality)
    assert policy["class_order"] == ["DAY_16","DAY_18","UNFERTILIZED"]
    assert policy["minimum_margin"]["DAY_18"] is None
    assert policy["minimum_margin"]["UNFERTILIZED"] == 0
