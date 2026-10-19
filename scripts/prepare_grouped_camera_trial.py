"""Seal the development-selected nonlinear camera classifier without activating it."""
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"ml"),str(ROOT/"apps/edge_api")]
import numpy as np
import onnx
import onnxruntime as ort
import torch
from torch import nn
from PIL import Image
from balut_ml.feature_models import load_classifier,build_head
from balut_api.model_service import ModelService,preprocess,decode_jpeg,sha256_file as sha
from balut_api.selective_gate import decide

RUN=ROOT/"ml/runs/grouped-kernel-20261019"
CACHE=ROOT/"ml/runs/grouped-camera-20261019"
BASE=ROOT/"deployment/releases/unfertilized-trial-20261019"
RELEASE=ROOT/"deployment/releases/grouped-camera-trial-20261019"
PARTS=ROOT/"deployment/model-parts/grouped-camera-20261019"
CLASSES=["DAY_16","DAY_18","REJECT"]


def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


class DoubleKernelHead(nn.Module):
    def __init__(self,head):super().__init__();self.head=head.double()
    def forward(self,features):return self.head(features.to(torch.float64)).to(torch.float32)


def main():
    if RELEASE.exists() or PARTS.exists():raise FileExistsError("Preserve the completed or interrupted release")
    torch.set_num_threads(4)
    lock=json.loads((RUN/"selection-lock.json").read_text())
    assert all(sha(RUN/name)==digest for name,digest in lock["artifacts"].items())
    cache_lock=json.loads((CACHE/"selection-lock.json").read_text())
    assert all(sha(CACHE/name)==digest for name,digest in cache_lock["artifacts"].items())
    measured=json.loads((RUN/"metrics.json").read_text());assert measured["kernel_wins_development_selection"]
    protected={str(p.relative_to(BASE)):sha(p) for p in BASE.rglob("*") if p.is_file()}
    payload=torch.load(RUN/"selected-head.pt",weights_only=True,map_location="cpu")
    head=build_head(payload["spec"]).double();head.load_state_dict(payload["state_dict"])
    model,config=load_classifier(ROOT/"ml/runs/selective-v2/best.pt")
    model.head=DoubleKernelHead(head);model.eval()
    directory=RELEASE/"egg-grade";directory.mkdir(parents=True)
    torch.onnx.export(model,(torch.zeros(1,3,224,224),),str(directory/"best.onnx"),opset_version=18,dynamo=False,
        input_names=["images"],output_names=["decision_scores","embedding"],dynamic_axes={"images":{0:"batch"},"decision_scores":{0:"batch"},"embedding":{0:"batch"}})
    onnx.checker.check_model(onnx.load(directory/"best.onnx"))
    del model
    for name in ["gate-policy.json","training-references.npz","selection-lock.json"]:shutil.copyfile(RUN/name,directory/name)
    # Publish aggregate metrics only; per-egg records and camera photographs remain local.
    write(directory/"metrics.json",{"scope":"DEVELOPMENT_GROUPED_CV_NOT_FIELD_ACCURACY","candidate_count":24,
          "selected_spec":measured["selected"]["spec"],"camera_age_recall":measured["selected"]["camera_age_recall"],
          "raw":measured["selected"]["raw"],"physical_development_eggs":20,"test_images_opened":0,
          "claim_99_percent_supported":False,"physical_unfertilized_check_performed":False})
    cfg=json.loads((RUN/"config.json").read_text())
    policy=json.loads((RUN/"gate-policy.json").read_text())
    assert all(policy["minimum_margin"][label] is not None for label in CLASSES)
    config.update(status="EXPLORATORY_FROZEN_FEATURE_CLASSIFIER",task="THREE_CLASS_EGG_APPEARANCE",class_order=CLASSES,
        head=cfg["head"],operational_use_authorized=False,experimental=True,display_name="Day 16/18 + Reject - grouped camera experimental",
        training_method=cfg["training_method"],manifest_sha256=cfg["dataset_sha256"],selection_lock_sha256=sha(RUN/"selection-lock.json"),
        gate_policy_sha256=sha(directory/"gate-policy.json"),references_sha256=sha(directory/"training-references.npz"),
        physical_training_eggs=20,development_folds=5,
        limitations=["Reject names original Unfertilized annotations; not a general defect or food-safety diagnosis",
          "Known eggs/families are fold-disjoint; public source egg/batch identities remain incomplete",
          "Out-of-fold development selection/calibration is not fresh independent field accuracy",
          "No confirmed physical Unfertilized egg was available; uncertain inputs request recapture"])
    config.pop("epochs_completed",None);config.pop("selected_epoch",None)
    write(directory/"config.json",config)
    options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(directory/"best.onnx"),sess_options=options,providers=["CPUExecutionProvider"])
    inputs=json.loads((CACHE/"serving-inputs.json").read_text())
    with np.load(CACHE/"development.npz",allow_pickle=False) as bank:x,truth=bank["features"],bank["truth"]
    maximum_score_error=0.;maximum_embedding_error=0.
    # Fixed development sample checks both private camera inputs and public-source JPEG conversion.
    indexes=np.sort(np.random.default_rng(42).choice(len(x),64,replace=False))
    for start in range(0,len(indexes),8):
        chosen=indexes[start:start+8];bodies=[Path(inputs[i]["path"]).read_bytes() for i in chosen]
        scores,embedding=session.run(None,{"images":np.concatenate([preprocess(body,config) for body in bodies])})
        with torch.inference_mode():expected=head(torch.from_numpy(x[chosen]).double()).numpy().astype(np.float32)
        maximum_score_error=max(maximum_score_error,float(np.max(np.abs(scores-expected))))
        maximum_embedding_error=max(maximum_embedding_error,float(np.max(np.abs(embedding-x[chosen]))))
        assert np.array_equal(scores.argmax(1),expected.argmax(1))
    assert maximum_score_error<1e-4 and maximum_embedding_error<1e-4
    with np.load(directory/"training-references.npz",allow_pickle=False) as bank:references,labels=bank["features"],bank["labels"]
    rows=[json.loads(line) for line in (ROOT/"data/local/retained-camera-epochs-reject-20261019/manifest.jsonl").read_text().splitlines()]
    public={r["source_sha256"]:r["training_label"] for r in rows if not r.get("physical_egg_id") and r["partition"]!="test"}
    artifact=lambda p:{"path":p.relative_to(RELEASE).as_posix(),"sha256":sha(p)}
    def inspect(body):
        scores,embedding=session.run(None,{"images":preprocess(body,config)})
        return scores[0],decide(scores[0],embedding[0],decode_jpeg(body),policy,references,labels)
    examples=[]
    for label in CLASSES:
        for item in inputs:
            if public.get(item["source_sha256"])!=label:continue
            body=Path(item["path"]).read_bytes();scores,result=inspect(body)
            if result["sourcePrediction"]!=label:continue
            target=directory/(label.lower()+".jpg");target.write_bytes(body)
            examples.append({"file":artifact(target),"expected_scores":scores.tolist(),"expected_prediction":label,
                "expected_analysis_outcome":"CLASSIFIED","expected_recapture_reasons":[],"partition":"public development software fixture"})
            break
        else:raise RuntimeError("No supported public software fixture for "+label)
    dark=directory/"too-dark.jpg";Image.new("RGB",(224,224),"black").save(dark,"JPEG")
    scores,result=inspect(dark.read_bytes());assert result["sourcePrediction"] is None and "LOW_CONTRAST" in result["recaptureReasons"]
    examples.append({"file":artifact(dark),"expected_scores":scores.tolist(),"expected_prediction":None,
        "expected_analysis_outcome":"RECAPTURE_REQUIRED","expected_recapture_reasons":result["recaptureReasons"],"partition":"synthetic software fixture"})
    PARTS.mkdir();parts={"sha256":sha(directory/"best.onnx"),"bytes":(directory/"best.onnx").stat().st_size,"parts":[]}
    with (directory/"best.onnx").open("rb") as stream:
        for index in range(8):
            body=stream.read(20*1024*1024)
            if not body:break
            path=PARTS/f"best.onnx.part{index:02}";path.write_bytes(body)
            parts["parts"].append({"name":path.name,"bytes":len(body),"sha256":sha(path)})
        assert not stream.read(1)
    write(PARTS/"manifest.json",parts)
    entry={"id":"egg-grade","model":{**artifact(directory/"best.onnx"),"parts_revision":PARTS.name},"config":artifact(directory/"config.json"),
        "gate_policy":artifact(directory/"gate-policy.json"),"training_references":artifact(directory/"training-references.npz"),
        "known_answer":examples[0]["file"],"expected_scores":examples[0]["expected_scores"],"expected_prediction":"DAY_16",
        "input_description":"Day 16, Day 18 and Reject (source Unfertilized); grouped-CV kernel classifier; three paused views or one photo"}
    registry={"schema_version":1,"scope":"SOURCE_LABEL_SHADOW_ONLY","release_id":RELEASE.name,"default_analysis_model":"egg-grade",
              "models":[entry],"software_test_examples":examples}
    write(RELEASE/"registry.json",registry);digest=sha(RELEASE/"registry.json")
    (RELEASE/"registry.sha256").write_bytes((digest+"\n").encode());shutil.copytree(BASE/"licenses",RELEASE/"licenses")
    service=ModelService()
    try:
        service.load(RELEASE/"registry.json",digest)
        for example in examples:
            for camera in (False,True):
                actual=service._predict("egg-grade",(RELEASE/example["file"]["path"]).read_bytes(),camera=camera)
                assert actual["sourcePrediction"]==example["expected_prediction"] and actual["recaptureReasons"]==example["expected_recapture_reasons"]
    finally:service.close()
    assert all(sha(BASE/name)==digest for name,digest in protected.items())
    write(RELEASE/"verification.json",{"software_checks_passed":True,"release":RELEASE.name,"registry_sha256":digest,
          "model_sha256":parts["sha256"],"model_bytes":parts["bytes"],"cpu_parity_images":64,"cpu_parity_score_maximum_error":maximum_score_error,
          "cpu_parity_embedding_maximum_error":maximum_embedding_error,"source_camera_photos_published":0,"test_images_opened":0,
          "promoted":False,"physical_unfertilized_validation_passed":False,"claim_99_percent_supported":False})
    print((RELEASE/"verification.json").read_text(),flush=True)


if __name__=="__main__":main()
