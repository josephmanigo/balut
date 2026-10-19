import numpy as np
import pytest
from balut_ml.train_grouped_camera import CLASSES, feature_view, full_head, grouped_folds, outcomes


def test_portable_view_head_matches_selected_features():
    from sklearn.linear_model import LogisticRegression
    rng=np.random.default_rng(3);x=rng.normal(size=(30,1664)).astype(np.float32);y=np.tile([0,1,2],10)
    for view in ("fused","dino","efficient"):
        estimator=LogisticRegression().fit(feature_view(x,view),y)
        coefficient,intercept=full_head(estimator,view)
        np.testing.assert_allclose(x@coefficient.T+intercept,estimator.decision_function(feature_view(x,view)),atol=1e-5,rtol=1e-5)


def test_folds_keep_every_view_of_known_eggs_together():
    rows=[];truth=[]
    for label in range(3):
        for group in range(10):
            for view in range(2):
                rows.append({"physical_egg_id":f"{label}-{group}" if label<2 else None,"duplicate_group":f"source-{label}-{group}"})
                truth.append(label)
    folds,groups=grouped_folds(rows,np.array(truth))
    for group in set(groups):assert len(set(folds[groups==group]))==1
    assert set(folds)==set(range(5))
    rows[0]["physical_egg_id"]="extra-egg"
    with pytest.raises(ValueError,match="ten development eggs"):grouped_folds(rows,np.array(truth))


def test_development_gate_keeps_quality_and_unsupported_class_recaptures():
    truth=np.repeat([0,1,2],6);scores=np.eye(3)[truth]*3
    policy={"minimum_margin":dict.fromkeys(CLASSES,1.),"minimum_training_cosine":dict.fromkeys(CLASSES,.5)}
    nearest=np.ones((18,3));flags=[[] for _ in truth]
    flags[0]=["IMAGE_TOO_BLURRY"]
    policy["minimum_margin"]["DAY_18"]=None
    matrix=outcomes(scores,truth,nearest,flags,policy)
    assert matrix.tolist()==[[5,0,0,1],[0,0,0,6],[0,0,6,0]]
