import numpy as np
import pytest
from balut_ml.calibrate_camera_operating_point import calibrate


def examples():
    rows=[];truth=[];folds=[]
    for label in range(3):
        for group in range(5):
            rows.append({"physical_egg_id":f"egg-{label}-{group}" if label<2 else None,"duplicate_group":f"source-{label}-{group}"})
            truth.append(label);folds.append(group)
    scores=np.eye(3)[truth]*3
    return rows,np.array(truth),np.array(folds),scores


def test_low_margin_error_is_recaptured_without_disabling_supported_classes():
    rows,truth,folds,scores=examples()
    rows.append({"physical_egg_id":"extra-day18","duplicate_group":"extra"})
    truth=np.append(truth,1);folds=np.append(folds,0);scores=np.vstack((scores,[1,0,0]))
    policy,report=calibrate(scores,truth,np.ones((16,3)),[[] for _ in rows],rows,folds,{})
    assert policy["minimum_margin"]=={"DAY_16":3.,"DAY_18":0.,"REJECT":0.}
    assert report["classes"]["DAY_16"]["correct_support_groups"]==5


def test_many_views_of_one_egg_do_not_count_as_five_supported_eggs():
    rows,truth,folds,scores=examples()
    for i in range(5):rows[i]["physical_egg_id"]="same-egg";folds[i]=0
    policy,_=calibrate(scores,truth,np.ones((15,3)),[[] for _ in rows],rows,folds,{})
    assert policy["minimum_margin"]["DAY_16"] is None
    folds[1]=1
    with pytest.raises(ValueError,match="crosses folds"):calibrate(scores,truth,np.ones((15,3)),[[] for _ in rows],rows,folds,{})


def test_quality_failures_never_enter_calibration_acceptance():
    rows,truth,folds,scores=examples();flags=[[] for _ in rows];flags[0]=["IMAGE_TOO_BLURRY"]
    policy,report=calibrate(scores,truth,np.ones((15,3)),flags,rows,folds,{})
    assert policy["minimum_margin"]["DAY_16"] is None
    assert report["classes"]["DAY_16"]["accepted_images"]==0
