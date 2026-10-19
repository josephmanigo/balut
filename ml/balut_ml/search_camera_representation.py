"""Compare fixed image representations on grouped development folds only."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from threadpoolctl import threadpool_limits

from .train_grouped_camera import ROOT, DATA, CLASSES, sha, write, metrics
from .train_grouped_kernel import fit_models,scores_for

PARENT=ROOT/"ml/runs/grouped-camera-20261019"
RUN=ROOT/"ml/runs/representation-search-20261019"
GRID=[{"C":c,"gamma":g,"camera_weight":20} for c in (1.,10.,100.) for g in (1.,5.)]
# Fixed from development-camera geometry; exclude the PC background and holder edges.
INTERIOR=(44,48,208,180)


def interior_view(images):
    import torch.nn.functional as F
    left,top,right,bottom=INTERIOR
    return F.interpolate(images[:,:,top:bottom,left:right],size=(224,224),mode="bilinear",align_corners=False)


def fused(*features):return np.concatenate(features,axis=1)/np.float32(len(features)**.5)


def main():
    if RUN.exists():raise FileExistsError("Preserve the completed or interrupted representation search")
    import torch
    from .feature_models import FeatureEncoder,build_backbone,portable_head
    from balut_api.model_service import preprocess
    torch.set_num_threads(4)
    if not torch.cuda.is_available():raise RuntimeError("CUDA GPU required for this fixed feature pass")
    parent_lock=json.loads((PARENT/"selection-lock.json").read_text())
    assert all(sha(PARENT/name)==digest for name,digest in parent_lock["artifacts"].items())
    rows=[json.loads(line) for line in (DATA/"manifest.jsonl").read_text().splitlines()]
    rows=[r for r in rows if r["partition"] in ("train","validation")]
    inputs=json.loads((PARENT/"serving-inputs.json").read_text())
    with np.load(PARENT/"development.npz",allow_pickle=False) as bank:
        original,truth,folds=bank["features"],bank["truth"],bank["folds"]
        np.testing.assert_array_equal(bank["source_sha256"],[r["source_sha256"] for r in rows])
    groups=np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows]);physical=np.array([bool(r.get("physical_egg_id")) for r in rows])
    for fold in range(5):assert not set(groups[folds==fold])&set(groups[folds!=fold])
    checkpoints={name:ROOT/"ml/runs/accuracy-v2"/(name+"-encoder.pt") for name in ["convnext_tiny","dinov2_vits14","efficientnet_b0"]}
    protected={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),DATA/"manifest.jsonl",PARENT/"selection-lock.json",ROOT/"deployment/active-release.txt",*checkpoints.values()]}
    profiles=["fused-full","dino-full","efficient-full","convnext-full","convnext-interior","dino-interior","efficient-interior",
              "fused-interior","convnext-dual","efficient-dual","dino-dual","convnext-efficient-interior"]
    RUN.mkdir()
    write(RUN/"experiment-plan.json",{"method":"FIXED_REPRESENTATION_GROUPED_CV","profiles":profiles,"classifier_grid":GRID,
        "interior_crop_224_coordinates":INTERIOR,"physical_development_eggs":20,"development_images":3070,"folds":5,
        "crop_reason":"Development-only image inspection shows PC lights/background. Fixed interior crop excludes that context; it is identical for every label.",
        "selection":"Mean camera-egg raw recall, minimum age recall, worst camera fold recall, source macro F1; stable first tie",
        "target":{"raw_overall":.96,"camera_day16_recall":.96,"camera_day18_recall":.96},
        "historical_policy":"No historical images opened during this loop. A development target alone is not a deployable accuracy claim.",
        "input_semantics":"Exact canonical serving JPEG; normalized 224 full image then optional fixed tensor crop/resize",
        "augmentation":"Retained horizontal-flip feature averaging; no new random augmentations or label changes",
        "source_labels":"Reject names public Unfertilized annotations; vendor R1/R2/R3 remain excluded",
        "gpu_cpu_scope":"New representations extracted with frozen CUDA models. Selected representation must later pass actual CPU/ONNX parity and CPU validation before any deployment.",
        "protected_files":protected})
    features={"fused-full":original,"dino-full":original[:,:384]*np.float32(2**.5),"efficient-full":original[:,384:]*np.float32(2**.5)}
    config={"normalization_mean":[.485,.456,.406],"normalization_std":[.229,.224,.225]}
    for name,profile in [("convnext_tiny","full"),("convnext_tiny","interior"),("dinov2_vits14","interior"),("efficientnet_b0","interior")]:
        prefix={"convnext_tiny":"convnext","dinov2_vits14":"dino","efficientnet_b0":"efficient"}[name]
        encoder=FeatureEncoder(build_backbone(name)).eval()
        encoder.load_state_dict(torch.load(checkpoints[name],weights_only=True,map_location="cpu"));encoder.cuda()
        result=[]
        with torch.inference_mode():
            for start in range(0,len(inputs),32):
                batch=inputs[start:start+32]
                for item in batch:assert sha(Path(item["path"]))==item["serving_jpeg_sha256"]
                images=torch.from_numpy(np.concatenate([preprocess(Path(item["path"]).read_bytes(),config) for item in batch])).cuda()
                if profile=="interior":images=interior_view(images)
                result.extend(encoder(images).cpu().numpy())
                if (start//32)%15==0:print(json.dumps({"extracting":prefix+"-"+profile,"images":min(start+32,len(inputs)),"total":len(inputs)}),flush=True)
        values=np.asarray(result,dtype=np.float32);np.testing.assert_allclose(np.linalg.norm(values,axis=1),1,atol=1e-4)
        features[prefix+"-"+profile]=values
        np.savez_compressed(RUN/(prefix+"-"+profile+".npz"),features=values)
        del encoder;torch.cuda.empty_cache()
    features["fused-interior"]=fused(features["dino-interior"],features["efficient-interior"])
    for prefix in ["convnext","efficient","dino"]:features[prefix+"-dual"]=fused(features[prefix+"-full"],features[prefix+"-interior"])
    features["convnext-efficient-interior"]=fused(features["convnext-interior"],features["efficient-interior"])
    best=None;selected=None
    for profile in profiles:
        x=features[profile];np.testing.assert_allclose(np.linalg.norm(x,axis=1),1,atol=1e-4)
        for spec in GRID:
            scores=np.full((len(rows),3),np.nan,dtype=np.float32)
            for fold in range(5):
                fit,held=np.flatnonzero(folds!=fold),np.flatnonzero(folds==fold)
                models=fit_models(x[fit],truth[fit],[rows[i] for i in fit],spec);scores[held]=scores_for(models,x[held])
            assert np.isfinite(scores).all();prediction=scores.argmax(1)
            age=[float(np.mean(prediction[physical&(truth==label)]==label)) for label in range(2)]
            fold_scores=[float(np.mean([np.mean(prediction[physical&(truth==label)&(folds==fold)]==label) for label in range(2)])) for fold in range(5)]
            source=metrics(scores[~physical],truth[~physical]);measured=metrics(scores,truth)
            key=(round(float(np.mean(age)),12),min(age),min(fold_scores),source["f1"])
            target=measured["accuracy"]>=.96 and min(age)>=.96
            record={"profile":profile,"spec":spec,"selection_key":key,"camera_age_recall":age,"fold_camera_recall":fold_scores,
                "raw":measured,"source_raw":source,"development_target_passed":target,"not_independent_field_accuracy":True}
            with (RUN/"search.jsonl").open("a") as stream:stream.write(json.dumps(record,allow_nan=False)+"\n")
            if best is None or key>best:
                best=key;selected=record;np.savez_compressed(RUN/"selected-oof.npz",scores=scores,truth=truth,folds=folds)
                np.savez_compressed(RUN/"selected-features.npz",features=x,truth=truth)
                write(RUN/"selected.json",selected)
            print(json.dumps({"profile":profile,"spec":spec,"camera_age_recall":age,"overall_raw":measured["accuracy"],"development_target_passed":target}),flush=True)
    x=features[selected["profile"]];models=fit_models(x,truth,rows,selected["spec"])
    head,head_spec=portable_head(SimpleNamespace(estimators_=models,n_features_in_=x.shape[1]),"rbf_ovr");head.double()
    with torch.inference_mode():portable=head(torch.from_numpy(x).double()).numpy()
    native=scores_for(models,x);error=float(np.max(np.abs(portable-native)))
    assert error<1e-4 and np.array_equal(portable.argmax(1),native.argmax(1))
    torch.save({"state_dict":head.state_dict(),"spec":head_spec},RUN/"selected-head.pt")
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    write(RUN/"metrics.json",{"selected":selected,"candidates":len(profiles)*len(GRID),"native_portable_max_error":error,"test_images_opened":0,"promoted":False})
    names=["experiment-plan.json","search.jsonl","selected.json","selected-oof.npz","selected-features.npz","selected-head.pt","metrics.json"]
    write(RUN/"selection-lock.json",{"artifacts":{name:sha(RUN/name) for name in names},"historical_test_images_opened":0})
    print(json.dumps({"complete":True,"selected":selected["profile"],"camera_age_recall":selected["camera_age_recall"],"overall_raw":selected["raw"]["accuracy"],"development_target_passed":selected["development_target_passed"]}),flush=True)


if __name__=="__main__":
    with threadpool_limits(limits=4):main()
