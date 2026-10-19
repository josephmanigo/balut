"""CPU-only nested stacking of frozen representations; no historical images or CUDA."""
import json
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from .train_grouped_camera import ROOT,DATA,CLASSES,sha,write,metrics,fit_weights
from .train_grouped_kernel import fit_models,scores_for

BASE=ROOT/"ml/runs/grouped-camera-20261019"
REPS=ROOT/"ml/runs/representation-search-20261019"
RUN=ROOT/"ml/runs/nested-camera-stack-20261019"
PROFILES=["fused-full","fused-interior","dino-dual","efficient-dual"]
BASE_SPEC={"C":10.,"gamma":1.,"camera_weight":20}
META_C=[.1,1.,10.]


def combine(*arrays):return np.concatenate(arrays,axis=1)/np.float32(len(arrays)**.5)


def main():
    if RUN.exists():raise FileExistsError("Preserve completed or interrupted CPU stack search")
    parent_lock=json.loads((BASE/"selection-lock.json").read_text())
    rep_lock=json.loads((REPS/"selection-lock.json").read_text())
    for folder,lock in [(BASE,parent_lock),(REPS,rep_lock)]:assert all(sha(folder/name)==digest for name,digest in lock["artifacts"].items())
    rows=[json.loads(line) for line in (DATA/"manifest.jsonl").read_text().splitlines()]
    rows=[r for r in rows if r["partition"] in ("train","validation")]
    with np.load(BASE/"development.npz",allow_pickle=False) as bank:
        full,truth,folds=bank["features"],bank["truth"],bank["folds"]
        np.testing.assert_array_equal(bank["source_sha256"],[r["source_sha256"] for r in rows])
    with np.load(REPS/"dino-interior.npz",allow_pickle=False) as bank:dino=bank["features"]
    with np.load(REPS/"efficient-interior.npz",allow_pickle=False) as bank:efficient=bank["features"]
    features={"fused-full":full,"fused-interior":combine(dino,efficient),
              "dino-dual":combine(full[:,:384]*np.float32(2**.5),dino),
              "efficient-dual":combine(full[:,384:]*np.float32(2**.5),efficient)}
    with np.load(REPS/"selected-features.npz",allow_pickle=False) as bank:
        assert json.loads((REPS/"selected.json").read_text())["profile"]=="fused-interior"
        np.testing.assert_array_equal(features["fused-interior"],bank["features"])
    groups=np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows]);physical=np.array([bool(r.get("physical_egg_id")) for r in rows])
    for x in features.values():np.testing.assert_allclose(np.linalg.norm(x,axis=1),1,atol=1e-4)
    protected={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),DATA/"manifest.jsonl",BASE/"selection-lock.json",REPS/"selection-lock.json",
        REPS/"dino-interior.npz",REPS/"efficient-interior.npz",ROOT/"deployment/active-release.txt"]}
    RUN.mkdir()
    write(RUN/"experiment-plan.json",{"method":"CPU_NESTED_GROUPED_STACK","profiles":PROFILES,"base_spec":BASE_SPEC,"meta_C":META_C,
        "outer_folds":5,"inner_folds":"Four remaining original folds; the outer fold is excluded from every inner fit and meta fit",
        "feature_dimensionalities":{k:x.shape[1] for k,x in features.items()},"physical_development_eggs":20,"development_images":3070,
        "reason":"GPU fine-tuning coincided with two unexpected machine restarts; user confirms automatic restarts. This job never initializes or uses CUDA.",
        "selection":"Target passed, weaker camera-age recall, mean camera-age recall, source macro F1; stable first tie",
        "target":{"overall_raw":.96,"camera_day16_recall":.96,"camera_day18_recall":.96},
        "test_images_opened":0,"source_label_scope":"Reject names original Unfertilized annotations; R1/R2/R3 excluded",
        "validation_scope":"Nested parameter fits exclude each outer egg/family; repeated research on these development folds is still not an independent final field study",
        "protected_files":protected})
    oof={c:np.full((len(rows),3),np.nan,dtype=np.float32) for c in META_C}
    base_oof=np.full((len(rows),len(PROFILES)*3),np.nan,dtype=np.float32)
    started=time.perf_counter()
    for outer in range(5):
        fit,held=np.flatnonzero(folds!=outer),np.flatnonzero(folds==outer)
        assert not set(groups[fit])&set(groups[held])
        inner_scores=np.full((len(rows),len(PROFILES)*3),np.nan,dtype=np.float32)
        outer_scores=[]
        for number,profile in enumerate(PROFILES):
            x=features[profile]
            for inner in range(5):
                if inner==outer:continue
                inner_fit=np.flatnonzero((folds!=outer)&(folds!=inner));inner_held=np.flatnonzero(folds==inner)
                assert not set(groups[inner_fit])&set(groups[inner_held])
                assert not set(groups[held])&(set(groups[inner_fit])|set(groups[inner_held]))
                models=fit_models(x[inner_fit],truth[inner_fit],[rows[i] for i in inner_fit],BASE_SPEC)
                inner_scores[inner_held,number*3:(number+1)*3]=scores_for(models,x[inner_held])
            models=fit_models(x[fit],truth[fit],[rows[i] for i in fit],BASE_SPEC)
            outer_scores.append(scores_for(models,x[held]))
            print(json.dumps({"outer_fold":outer+1,"profile_completed":profile,"elapsed_seconds":time.perf_counter()-started}),flush=True)
        outer_scores=np.concatenate(outer_scores,axis=1);base_oof[held]=outer_scores
        assert np.isfinite(inner_scores[fit]).all() and np.isnan(inner_scores[held]).all()
        weights=fit_weights([rows[i] for i in fit],20)*2256/len(fit)
        for c in META_C:
            meta=LogisticRegression(C=c,max_iter=3000,random_state=42)
            meta.fit(inner_scores[fit],truth[fit],sample_weight=weights)
            oof[c][held]=meta.decision_function(outer_scores)
        np.savez_compressed(RUN/f"outer-{outer+1}.npz",inner_meta_features=inner_scores[fit],outer_base_scores=outer_scores,fit=fit,held=held)
    candidates=[]
    for c,scores in oof.items():
        assert np.isfinite(scores).all();prediction=scores.argmax(1)
        age=[float(np.mean(prediction[physical&(truth==label)]==label)) for label in range(2)]
        measured=metrics(scores,truth);source=metrics(scores[~physical],truth[~physical]);target=measured["accuracy"]>=.96 and min(age)>=.96
        record={"meta_C":c,"raw":measured,"camera_age_recall":age,"source_raw":source,"development_target_passed":target}
        candidates.append(record)
        print(json.dumps({"meta_C":c,"camera_age_recall":age,"overall_raw":measured["accuracy"],"development_target_passed":target}),flush=True)
    selected=max(candidates,key=lambda r:(r["development_target_passed"],min(r["camera_age_recall"]),np.mean(r["camera_age_recall"]),r["source_raw"]["f1"]))
    meta=LogisticRegression(C=selected["meta_C"],max_iter=3000,random_state=42)
    assert np.isfinite(base_oof).all()
    meta.fit(base_oof,truth,sample_weight=fit_weights(rows,20)*2256/len(rows))
    np.savez_compressed(RUN/"meta-head.npz",coefficient=meta.coef_.astype(np.float32),intercept=meta.intercept_.astype(np.float32))
    np.savez_compressed(RUN/"selected-oof.npz",scores=oof[selected["meta_C"]],truth=truth,folds=folds,base_scores=base_oof)
    write(RUN/"metrics.json",{"candidates":candidates,"selected":selected,"historical_test_images_opened":0,"promoted":False,"elapsed_seconds":time.perf_counter()-started})
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    names=["experiment-plan.json","meta-head.npz","selected-oof.npz","metrics.json",*[str(p.relative_to(RUN)) for p in RUN.glob("outer-*.npz")]]
    write(RUN/"selection-lock.json",{"artifacts":{name:sha(RUN/name) for name in names},"test_images_opened":0})
    print(json.dumps({"complete":True,"selected":selected}),flush=True)


if __name__=="__main__":
    with threadpool_limits(limits=2):main()
