"""Select a regularized head with known-egg-disjoint folds; keep test images closed."""
from collections import Counter
import io
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageOps
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from threadpoolctl import threadpool_limits

from .train_epoch_head import ROOT, PARENT, DATA, CLASSES, sha, write, target_rows, metrics
from .train_unfertilized import fit_weights
from balut_api.model_service import preprocess
from balut_api.selective_gate import image_quality, validate_policy

RUN = ROOT / "ml/runs/grouped-camera-20261019"
BASE = ROOT / "deployment/releases/unfertilized-trial-20261019"
GRID = [{"view": v, "C": c, "camera_weight": w} for v in ("fused", "dino", "efficient")
        for c in (1., 10., 100.) for w in (20, 100)]


def feature_view(features, view):
    if view == "fused": return features
    if view == "dino": return features[:, :384] * np.float32(2**.5)
    if view == "efficient": return features[:, 384:] * np.float32(2**.5)
    raise ValueError("Unknown feature view")


def full_head(estimator, view):
    coefficient = np.zeros((3, 1664), dtype=np.float32)
    assert estimator.classes_.tolist() == [0, 1, 2]
    if view == "fused": coefficient[:] = estimator.coef_
    elif view == "dino": coefficient[:, :384] = estimator.coef_ * 2**.5
    elif view == "efficient": coefficient[:, 384:] = estimator.coef_ * 2**.5
    else: raise ValueError("Unknown feature view")
    return coefficient, estimator.intercept_.astype(np.float32)


def grouped_folds(rows, truth):
    groups = np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows])
    assigned = np.full(len(rows), -1)
    public = np.array([i for i, r in enumerate(rows) if not r.get("physical_egg_id")])
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    for fold, (_, held) in enumerate(splitter.split(public, truth[public], groups[public])): assigned[public[held]] = fold
    rng = np.random.default_rng(42)
    for label in range(2):
        eggs = sorted({r["physical_egg_id"] for i,r in enumerate(rows) if r.get("physical_egg_id") and truth[i] == label})
        if len(eggs) != 10: raise ValueError("Expected ten development eggs per age")
        rng.shuffle(eggs)
        for index, egg in enumerate(eggs): assigned[groups == egg] = index % 5
    if (assigned < 0).any(): raise ValueError("Missing fold assignment")
    for fold in range(5):
        fit, held = np.flatnonzero(assigned != fold), np.flatnonzero(assigned == fold)
        if set(groups[fit]) & set(groups[held]): raise ValueError("An egg or family crosses folds")
        if set(truth[fit]) != {0,1,2} or set(truth[held]) != {0,1,2}: raise ValueError("Missing fold class")
        for label in range(2):
            assert len({rows[i]["physical_egg_id"] for i in held if rows[i].get("physical_egg_id") and truth[i] == label}) == 2
    return assigned, groups


def gate_policy(scores, truth, nearest, quality):
    winner = scores.argmax(1); margins = np.sort(scores, axis=1)[:,-1] - np.sort(scores, axis=1)[:,-2]
    policy = {"schema_version":1,"class_order":CLASSES,"review_required":False,"on_uncertain":"RECAPTURE_REQUIRED",
              "minimum_margin":{},"minimum_training_cosine":{},"quality":quality,
              "calibration_scope":"Grouped out-of-fold development calibration; not independent gate accuracy or field evidence"}
    for i,label in enumerate(CLASSES):
        wrong = (winner == i) & (truth != i)
        margin = float(margins[wrong].max()) + .001 if wrong.any() else 0.
        policy["minimum_margin"][label] = margin if ((winner == i) & (margins >= margin)).sum() >= 5 else None
        policy["minimum_training_cosine"][label] = float(np.quantile(nearest[truth == i, i], .01))
    return policy


def outcomes(scores, truth, nearest, flags, policy):
    winner=scores.argmax(1);margin=np.sort(scores,axis=1)[:,-1]-np.sort(scores,axis=1)[:,-2]
    matrix=np.zeros((3,4),dtype=int)
    for i, label in enumerate(winner):
        threshold=policy["minimum_margin"][CLASSES[label]]
        accepted=not flags[i] and threshold is not None and margin[i]>0 and margin[i]>=threshold and nearest[i,label]>=policy["minimum_training_cosine"][CLASSES[label]]
        matrix[truth[i],label if accepted else 3]+=1
    return matrix


def main():
    if RUN.exists(): raise FileExistsError("Preserve completed or interrupted grouped experiment")
    import onnxruntime as ort
    manifest=DATA/"manifest.jsonl";audit=json.loads((DATA/"audit.json").read_text())
    assert sha(manifest)==audit["manifest_sha256"]
    all_rows=target_rows([json.loads(line) for line in manifest.read_text().splitlines()])
    rows=[r for r in all_rows if r["partition"] in ("train","validation")]
    assert len(rows)==3070 and sum(bool(r.get("physical_egg_id")) for r in rows)==1080
    truth=np.array([CLASSES.index(r["training_label"]) for r in rows])
    folds,groups=grouped_folds(rows,truth)
    registry=json.loads((BASE/"registry.json").read_text());entry=registry["models"][0]
    model=BASE/entry["model"]["path"];config=json.loads((BASE/entry["config"]["path"]).read_text())
    quality=json.loads((BASE/entry["gate_policy"]["path"]).read_text())["quality"]
    assert sha(model)==entry["model"]["sha256"]=="479211e3e587b0bce7d9bb1be1a318c48bdc62f632374f75d980ab1dbceda31e"
    protected={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),manifest,model,BASE/"registry.json",ROOT/"deployment/active-release.txt"]}
    RUN.mkdir()
    write(RUN/"experiment-plan.json",{"method":"FROZEN_ENCODER_GROUPED_CV_LOGISTIC_HEAD","seed":42,"folds":5,"grid":GRID,
          "development_images":3070,"physical_development_eggs":20,"physical_held_per_fold_per_age":2,
          "source_manifest_sha256":audit["manifest_sha256"],"encoder_onnx_sha256":sha(model),"protected_files":protected,
          "features":"Actual ONNX CPU embeddings on native JPEG or public PNG converted to JPEG quality95",
          "training":"Train+validation development rows pooled; all ten historical age test eggs remain excluded. One final head uses all 20 development age eggs.",
          "selection":"Mean physical-egg raw recall, minimum camera-age recall, worst fold camera-age balanced recall, source macro F1; stable first tie",
          "fixed_effective_training_weight":2256,"gate_calibration":"Pooled out-of-fold development scores; thresholds and similarity from held groups only; calibration counts are optimistic",
          "promotion":"One locked historical regression only after selection. No decrease in raw age correct or gated correct each class; no increase in wrong per age; no decrease in coverage.",
          "historical_role":"Already-inspected regression, not independent field confirmation. No historical images opened during selection.",
          "third_class":"Reject names original Unfertilized source category; R1/R2/R3 excluded; no general defect or physical Unfertilized validation"})
    write(RUN/"folds.json",{"source_sha256":[r["source_sha256"] for r in rows],"groups":groups.tolist(),"fold":folds.tolist()})
    options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(model),sess_options=options,providers=["CPUExecutionProvider"])
    features=[];flags=[];provenance=[];batch=[];started=time.perf_counter()
    (RUN/"inputs").mkdir()
    for index,row in enumerate(rows):
        path=Path(row["image_path"]);body=path.read_bytes();assert sha(path)==row["source_sha256"]
        with Image.open(io.BytesIO(body)) as image:
            if image.format!="JPEG":
                encoded=io.BytesIO();ImageOps.exif_transpose(image).convert("RGB").save(encoded,"JPEG",quality=95);body=encoded.getvalue()
        target=RUN/"inputs"/(row["source_sha256"]+".jpg");target.write_bytes(body)
        provenance.append({"source_sha256":row["source_sha256"],"path":str(target),"serving_jpeg_sha256":sha(target)})
        with Image.open(io.BytesIO(body)) as image:flags.append(image_quality(image,{"quality":quality})[1])
        batch.append(preprocess(body,config))
        if len(batch)==8 or index+1==len(rows):
            features.extend(session.run(["embedding"],{"images":np.concatenate(batch)})[0]);batch=[]
        if (index+1)%100==0 or index+1==len(rows):print(json.dumps({"cpu_features":index+1,"total":len(rows),"elapsed_seconds":time.perf_counter()-started}),flush=True)
    del session
    x=np.asarray(features,dtype=np.float32);np.testing.assert_allclose(np.linalg.norm(x,axis=1),1,atol=1e-4)
    np.savez_compressed(RUN/"development.npz",features=x,source_sha256=np.array([r["source_sha256"] for r in rows]),truth=truth,folds=folds)
    write(RUN/"serving-inputs.json",provenance)
    nearest=np.zeros((len(rows),3),dtype=np.float32)
    for fold in range(5):
        for label in range(3):nearest[folds==fold,label]=(x[folds==fold]@x[(folds!=fold)&(truth==label)].T).max(1)
    np.savez_compressed(RUN/"fold-nearest.npz",nearest=nearest)
    physical=np.array([bool(r.get("physical_egg_id")) for r in rows])
    selected=None;best_key=None
    for number,spec in enumerate(GRID,1):
        view=feature_view(x,spec["view"]);scores=np.full((len(rows),3),np.nan,dtype=np.float32)
        for fold in range(5):
            fit,held=np.flatnonzero(folds!=fold),np.flatnonzero(folds==fold)
            estimator=LogisticRegression(C=spec["C"],max_iter=3000,random_state=42)
            weights=fit_weights([rows[i] for i in fit],spec["camera_weight"])*2256/len(fit)
            estimator.fit(view[fit],truth[fit],sample_weight=weights);assert estimator.n_iter_.max()<3000
            coefficient,intercept=full_head(estimator,spec["view"])
            scores[held]=x[held]@coefficient.T+intercept
            np.testing.assert_allclose(scores[held],estimator.decision_function(view[held]),atol=1e-5,rtol=1e-5)
        assert np.isfinite(scores).all()
        pred=scores.argmax(1)
        egg_recall={egg:float(np.mean(pred[groups==egg]==truth[groups==egg])) for egg in sorted(set(groups[physical]))}
        age_recall=[float(np.mean(pred[physical&(truth==label)]==label)) for label in range(2)]
        fold_recall=[float(np.mean([np.mean(pred[physical&(truth==label)&(folds==fold)]==label) for label in range(2)])) for fold in range(5)]
        source_metrics=metrics(scores[~physical],truth[~physical]);measured=metrics(scores,truth)
        key=(float(np.mean(list(egg_recall.values()))),min(age_recall),min(fold_recall),source_metrics["f1"])
        policy=gate_policy(scores,truth,nearest,quality);matrix=outcomes(scores,truth,nearest,flags,policy)
        record={"number":number,"spec":spec,"selection_key":key,"raw":measured,"camera_age_recall":age_recall,
                "fold_camera_age_recall":fold_recall,"physical_egg_recall":egg_recall,"source_raw":source_metrics,
                "development_calibrated_matrix":matrix.tolist(),"calibration_is_not_independent":True}
        with (RUN/"search.jsonl").open("a") as stream:stream.write(json.dumps(record,allow_nan=False)+"\n")
        if best_key is None or key>best_key:
            best_key=key;selected=record;np.savez_compressed(RUN/"selected-oof.npz",scores=scores,truth=truth)
            write(RUN/"gate-policy.json",policy)
        print(json.dumps({"candidate":number,"total":len(GRID),"spec":spec,"camera_raw_recall":age_recall,"key":key,"calibrated_matrix":matrix.tolist()}),flush=True)
    spec=selected["spec"];estimator=LogisticRegression(C=spec["C"],max_iter=3000,random_state=42)
    estimator.fit(feature_view(x,spec["view"]),truth,sample_weight=fit_weights(rows,spec["camera_weight"])*2256/len(rows))
    assert estimator.n_iter_.max()<3000
    coefficient,intercept=full_head(estimator,spec["view"])
    np.testing.assert_allclose(x@coefficient.T+intercept,estimator.decision_function(feature_view(x,spec["view"])),atol=1e-5,rtol=1e-5)
    np.savez_compressed(RUN/"head.npz",coefficient=coefficient,intercept=intercept)
    np.savez_compressed(RUN/"training-references.npz",features=x,labels=truth)
    policy=json.loads((RUN/"gate-policy.json").read_text());validate_policy(policy,x,truth)
    write(RUN/"config.json",{"status":"EXPLORATORY_FROZEN_FEATURE_CLASSIFIER","class_order":CLASSES,"training_method":"FROZEN_ENCODER_GROUPED_CV_LOGISTIC_HEAD",
          "dataset_sha256":audit["manifest_sha256"],"encoder_onnx_sha256":sha(model),"spec":spec,"folds":5,
          "physical_training_eggs":20,"test_images_opened":0,"operational_use_authorized":False,"epochs_not_used":True})
    write(RUN/"metrics.json",{"selected":selected,"candidate_count":len(GRID),"final_training_images":len(rows),
          "physical_training_eggs":20,"test_images_opened":0,"promoted":False,"field_accuracy_established":False})
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    names=["experiment-plan.json","folds.json","development.npz","serving-inputs.json","fold-nearest.npz","search.jsonl","selected-oof.npz","gate-policy.json","head.npz","training-references.npz","config.json","metrics.json"]
    write(RUN/"selection-lock.json",{"artifacts":{name:sha(RUN/name) for name in names},"historical_test_images_opened":0})
    print(json.dumps({"completed":True,"selected":spec,"camera_age_recall":selected["camera_age_recall"],"policy":policy,"elapsed_seconds":time.perf_counter()-started}),flush=True)


if __name__=="__main__":
    with threadpool_limits(limits=4):main()
