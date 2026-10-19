"""Compare six nonlinear heads on the locked development folds before historical use."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from .train_grouped_camera import ROOT, DATA, BASE, CLASSES, gate_policy, outcomes, metrics, sha, write, fit_weights

PARENT = ROOT / "ml/runs/grouped-camera-20261019"
RUN = ROOT / "ml/runs/grouped-kernel-20261019"
GRID = [{"C":c,"gamma":g,"camera_weight":20} for c in (1.,10.,100.) for g in (1.,5.)]


def fit_models(features, truth, rows, spec):
    weights=fit_weights(rows,spec["camera_weight"])
    models=[]
    for label in range(3):
        positive=truth==label;balanced=weights.copy()
        for subset in (positive,~positive):balanced[subset]*=1128/balanced[subset].sum()
        model=SVC(C=spec["C"],gamma=spec["gamma"],kernel="rbf",cache_size=256)
        model.fit(features,positive,sample_weight=balanced)
        models.append(model)
    return models


def scores_for(models,features):return np.stack([model.decision_function(features) for model in models],axis=1).astype(np.float32)


def main():
    if RUN.exists():raise FileExistsError("Preserve the completed or interrupted kernel comparison")
    import torch
    from .feature_models import portable_head
    lock=json.loads((PARENT/"selection-lock.json").read_text())
    assert all(sha(PARENT/name)==digest for name,digest in lock["artifacts"].items())
    rows=[json.loads(line) for line in (DATA/"manifest.jsonl").read_text().splitlines()]
    rows=[r for r in rows if r["partition"] in ("train","validation")]
    with np.load(PARENT/"development.npz",allow_pickle=False) as bank:
        x,truth,folds=bank["features"],bank["truth"],bank["folds"]
        np.testing.assert_array_equal(bank["source_sha256"],[r["source_sha256"] for r in rows])
    with np.load(PARENT/"fold-nearest.npz",allow_pickle=False) as bank:nearest=bank["nearest"]
    groups=np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows]);physical=np.array([bool(r.get("physical_egg_id")) for r in rows])
    inputs=json.loads((PARENT/"serving-inputs.json").read_text());quality=json.loads((PARENT/"gate-policy.json").read_text())["quality"]
    from PIL import Image
    from balut_api.selective_gate import image_quality,validate_policy
    flags=[]
    for item in inputs:
        assert sha(Path(item["path"]))==item["serving_jpeg_sha256"]
        with Image.open(item["path"]) as image:flags.append(image_quality(image,{"quality":quality})[1])
    RUN.mkdir()
    write(RUN/"experiment-plan.json",{"method":"FROZEN_ENCODER_GROUPED_CV_RBF_HEAD","grid":GRID,"folds":5,
          "parent_lock_sha256":sha(PARENT/"selection-lock.json"),"development_images":len(rows),"physical_eggs":20,
          "reason":"Linear grouped comparison plateaued; no historical test images opened before this comparison.",
          "selection":"Same mean physical-egg recall, minimum age recall, worst camera fold recall, source macro F1 as linear comparison; select between the two only on development.",
          "fixed_effective_binary_weights":"1128 positive + 1128 negative per binary classifier",
          "gate_scope":"Development out-of-fold calibration; not independent accepted accuracy or field accuracy",
          "historical_test_images_opened":0})
    chosen=None;best=None
    for number,spec in enumerate(GRID,1):
        scores=np.full((len(rows),3),np.nan,dtype=np.float32)
        for fold in range(5):
            fit,held=np.flatnonzero(folds!=fold),np.flatnonzero(folds==fold)
            assert not set(groups[fit])&set(groups[held])
            models=fit_models(x[fit],truth[fit],[rows[i] for i in fit],spec)
            scores[held]=scores_for(models,x[held])
        assert np.isfinite(scores).all()
        pred=scores.argmax(1)
        egg_recall={egg:float(np.mean(pred[groups==egg]==truth[groups==egg])) for egg in sorted(set(groups[physical]))}
        age_recall=[float(np.mean(pred[physical&(truth==label)]==label)) for label in range(2)]
        fold_recall=[float(np.mean([np.mean(pred[physical&(truth==label)&(folds==fold)]==label) for label in range(2)])) for fold in range(5)]
        source=metrics(scores[~physical],truth[~physical])
        key=(round(float(np.mean(list(egg_recall.values()))),12),min(age_recall),min(fold_recall),source["f1"])
        policy=gate_policy(scores,truth,nearest,quality);matrix=outcomes(scores,truth,nearest,flags,policy)
        record={"number":number,"spec":spec,"selection_key":key,"raw":metrics(scores,truth),"camera_age_recall":age_recall,
                "fold_camera_age_recall":fold_recall,"physical_egg_recall":egg_recall,"source_raw":source,
                "development_calibrated_matrix":matrix.tolist(),"calibration_is_not_independent":True}
        with (RUN/"search.jsonl").open("a") as stream:stream.write(json.dumps(record,allow_nan=False)+"\n")
        if best is None or key>best:
            best=key;chosen=record;np.savez_compressed(RUN/"selected-oof.npz",scores=scores,truth=truth)
            write(RUN/"gate-policy.json",policy)
        print(json.dumps({"candidate":number,"spec":spec,"age_recall":age_recall,"key":key,"calibrated_matrix":matrix.tolist()}),flush=True)
    spec=chosen["spec"];models=fit_models(x,truth,rows,spec)
    head,head_spec=portable_head(SimpleNamespace(estimators_=models,n_features_in_=1664),"rbf_ovr")
    head.double()
    with torch.inference_mode():portable=head(torch.from_numpy(x).double()).numpy()
    native=scores_for(models,x);error=float(np.max(np.abs(portable-native)))
    assert error<1e-4 and np.array_equal(portable.argmax(1),native.argmax(1))
    torch.save({"state_dict":head.state_dict(),"spec":head_spec},RUN/"selected-head.pt")
    np.savez_compressed(RUN/"training-references.npz",features=x,labels=truth)
    validate_policy(json.loads((RUN/"gate-policy.json").read_text()),x,truth)
    linear=json.loads((PARENT/"metrics.json").read_text())["selected"]
    linear_key=[round(linear["selection_key"][0],12),*linear["selection_key"][1:]]
    wins=tuple(chosen["selection_key"])>tuple(linear_key)
    write(RUN/"metrics.json",{"selected":chosen,"linear_control":linear,"kernel_wins_development_selection":wins,
          "native_portable_score_maximum_error":error,"test_images_opened":0,"promoted":False,"field_accuracy_established":False})
    write(RUN/"config.json",{"status":"EXPLORATORY_FROZEN_FEATURE_CLASSIFIER","training_method":"FROZEN_ENCODER_GROUPED_CV_RBF_HEAD",
          "class_order":CLASSES,"head":head_spec,"head_computation":"float64 kernel then float32 scores",
          "dataset_sha256":sha(DATA/"manifest.jsonl"),"physical_training_eggs":20,"test_images_opened":0,"operational_use_authorized":False})
    assert all(sha(PARENT/name)==digest for name,digest in lock["artifacts"].items())
    names=["experiment-plan.json","search.jsonl","selected-oof.npz","gate-policy.json","selected-head.pt","training-references.npz","config.json","metrics.json"]
    write(RUN/"selection-lock.json",{"artifacts":{name:sha(RUN/name) for name in names},"test_images_opened":0})
    print(json.dumps({"complete":True,"kernel_wins_development_selection":wins,"selected":spec,"camera_age_recall":chosen["camera_age_recall"],"policy":json.loads((RUN/"gate-policy.json").read_text())}),flush=True)


if __name__=="__main__":
    with threadpool_limits(limits=4):main()
