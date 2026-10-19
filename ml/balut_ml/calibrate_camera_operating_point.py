"""Choose a development operating point without hiding low coverage or weak group support."""
from collections import Counter
import copy
import numpy as np

CLASSES=["DAY_16","DAY_18","REJECT"]


def calibrate(scores,truth,nearest,flags,rows,folds,quality):
    """Use held-fold scores/similarities, never final-model self-reference similarities."""
    scores,truth,nearest,folds=map(np.asarray,(scores,truth,nearest,folds))
    n=len(rows)
    if (scores.shape!=(n,3) or nearest.shape!=(n,3) or truth.shape!=(n,) or folds.shape!=(n,)
            or len(flags)!=n or set(truth.tolist())!={0,1,2} or set(folds.tolist())!=set(range(5))
            or not np.isfinite(scores).all() or not np.isfinite(nearest).all()
            or (nearest < -1.00001).any() or (nearest > 1.00001).any()):
        raise ValueError("Invalid grouped calibration inputs")
    identities=[("physical",r["physical_egg_id"]) if r.get("physical_egg_id") else ("source",r["duplicate_group"]) for r in rows]
    assignment={}
    for identity,fold in zip(identities,folds,strict=True):
        if assignment.setdefault(identity,int(fold))!=int(fold):raise ValueError("A calibration family crosses folds")
    counts=Counter(identities)
    weights=np.array([(20. if group[0]=="physical" else 1.)/counts[group] for group in identities])
    winner=scores.argmax(1);margin=np.sort(scores,axis=1)[:,-1]-np.sort(scores,axis=1)[:,-2]
    quality_pass=np.array([not reasons for reasons in flags]);nearest=np.clip(nearest,-1,1)
    policy={"schema_version":1,"class_order":CLASSES,"review_required":False,"on_uncertain":"RECAPTURE_REQUIRED",
        "minimum_margin":{},"minimum_training_cosine":{},"quality":copy.deepcopy(quality),
        "calibration_scope":"Grouped out-of-fold development: maximize coverage with family-weighted precision>=97%, image precision>=96%, and five correct groups. Not independent field accuracy or a probability guarantee."}
    reports={}
    for index,label in enumerate(CLASSES):
        similarity=float(np.quantile(nearest[truth==index,index],.01));policy["minimum_training_cosine"][label]=similarity
        eligible=(winner==index)&quality_pass&(margin>0)&(nearest[:,index]>=similarity)
        chosen=None
        for threshold in np.unique(np.concatenate(([0.],margin[eligible]))):
            accepted=eligible&(margin>=threshold);count=int(accepted.sum())
            if not count:continue
            correct=accepted&(truth==index)
            image_precision=float(correct.sum()/count)
            family_precision=float(weights[correct].sum()/weights[accepted].sum())
            required_kind="physical" if index<2 else "source"
            support={identities[i] for i in np.flatnonzero(correct) if identities[i][0]==required_kind}
            if image_precision+1e-12>=.96 and family_precision+1e-12>=.97 and len(support)>=5:
                chosen={"threshold":float(threshold),"accepted_images":count,"correct_images":int(correct.sum()),
                    "image_precision":image_precision,"family_weighted_precision":family_precision,"correct_support_groups":len(support)}
                break
        policy["minimum_margin"][label]=None if chosen is None else chosen["threshold"]
        reports[label]=chosen or {"threshold":None,"accepted_images":0,"correct_images":0,
            "reason":"No development operating point meets precision and independent-group support requirements"}
    return policy,{"classes":reports,"group_integrity_checked":True,"calibration_is_not_independent_evaluation":True,
                   "family_precision_target":.97,"image_precision_target":.96,"minimum_correct_support_groups":5}
