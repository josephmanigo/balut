"""Seal the epoch-trained Reject output while preserving source annotations."""
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import onnx
from onnx import numpy_helper
import onnxruntime as ort
from PIL import Image

from prepare_multiview_trial import ROOT, read, write
from balut_api.model_service import ModelService, decode_jpeg, preprocess, sha256_file
from balut_api.selective_gate import decide

RUN = ROOT / "ml/runs/retained-epochs-selective-reject-20261019"
BASE = ROOT / "deployment/releases/unfertilized-trial-20261019"
RELEASE = ROOT / "deployment/releases/epochs-reject-trial-20261019"
PARTS = ROOT / "deployment/model-parts/epochs-reject-20261019"
CLASSES = ["DAY_16", "DAY_18", "REJECT"]


def main():
    if RELEASE.exists() or PARTS.exists():
        raise FileExistsError("Preserve the prepared or interrupted Unfertilized release")
    lock, adapted = read(RUN/"selection-lock.json"), read(RUN/"config.json")
    assert adapted["class_order"] == CLASSES
    assert all(sha256_file(RUN/name)==digest for name,digest in lock["artifacts"].items())
    protected={str(p.relative_to(BASE)):sha256_file(p) for p in BASE.rglob("*") if p.is_file()}
    old_parts=ROOT/"deployment/model-parts"
    protected_parts={p.name:sha256_file(p) for p in old_parts.iterdir() if p.is_file()}
    base_registry=read(BASE/"registry.json")
    old_model=BASE/base_registry["models"][0]["model"]["path"]
    assert sha256_file(old_model)==adapted["encoder_onnx_sha256"]
    with np.load(RUN/"head.npz",allow_pickle=False) as bank:
        coefficient,intercept=bank["coefficient"],bank["intercept"]
    assert coefficient.shape==(3,1664) and intercept.shape==(3,)
    graph=onnx.load(old_model)
    changed=set()
    for tensor in graph.graph.initializer:
        replacement={"head.linear.weight":coefficient,"head.linear.bias":intercept}.get(tensor.name)
        if replacement is not None:
            assert list(tensor.dims)==list(replacement.shape)
            changed.add(tensor.name)
            tensor.CopyFrom(numpy_helper.from_array(replacement.astype(np.float32),tensor.name))
    assert changed=={"head.linear.weight","head.linear.bias"}
    onnx.checker.check_model(graph)
    directory=RELEASE/"egg-grade"
    directory.mkdir(parents=True)
    onnx.save(graph,directory/"best.onnx")
    for name in ("head.npz","gate-policy.json","training-references.npz","metrics.json","selection-lock.json"):
        shutil.copyfile(RUN/name,directory/name)
    audit=read(ROOT/"data/local/retained-camera-unfertilized-20261019/audit.json")
    config={"status":"EXPLORATORY_FROZEN_FEATURE_CLASSIFIER","task":"THREE_CLASS_EGG_APPEARANCE",
            "class_order":CLASSES,"selective_inference":True,"operational_use_authorized":False,
            "input_size":224,"normalization_mean":[.485,.456,.406],"normalization_std":[.229,.224,.225],
            "backbones":["dinov2_vits14","efficientnet_b0"],"head":{"kind":"logistic","feature_dim":1664,"outputs":3},
            "experimental":True,"display_name":"Day 16/18 + Reject · epoch-trained experimental",
            "manifest_sha256":adapted["dataset_sha256"],"selection_lock_sha256":sha256_file(RUN/"selection-lock.json"),
            "gate_policy_sha256":sha256_file(directory/"gate-policy.json"),
            "references_sha256":sha256_file(directory/"training-references.npz"),
            "training_method": "MINIBATCH_EPOCH_CLASSIFIER_HEAD", "epochs_completed": 57, "selected_epoch": 37, "limitations":["Reject is the requested name for source Unfertilized examples; no general defect condition is established", "Source and physical egg families keep their original partitions", "No independent biological or food-safety validation"]+["No confirmed Unfertilized physical egg is available for a live camera check."]}
    write(directory/"config.json",config)
    options=ort.SessionOptions(); options.intra_op_num_threads=4; options.inter_op_num_threads=1
    session=ort.InferenceSession(str(directory/"best.onnx"),sess_options=options,providers=["CPUExecutionProvider"])
    with np.load(directory/"training-references.npz",allow_pickle=False) as bank:
        references,labels=bank["features"],bank["labels"]
    policy=read(directory/"gate-policy.json")
    inputs={r["source_sha256"]:r for r in read(RUN/"validation-inputs.json")}
    outcomes=read(RUN/"validation-outcomes.json")
    artifacts=lambda p:{"path":p.relative_to(RELEASE).as_posix(),"sha256":sha256_file(p)}

    def inspect(body):
        scores,embedding=session.run(None,{"images":preprocess(body,config)})
        np.testing.assert_allclose(scores,embedding@coefficient.T+intercept,atol=1e-4,rtol=1e-4)
        return scores[0],decide(scores[0],embedding[0],decode_jpeg(body),policy,references,labels)

    examples=[]
    for label in CLASSES:
        selected=[r for r in outcomes if r["source_label"]==r["sourcePrediction"]==label]
        assert selected
        item=inputs[selected[0]["source_sha256"]]
        source=Path(item["path"])
        assert sha256_file(source)==item["serving_jpeg_sha256"]
        target=directory/(label.lower()+".jpg")
        shutil.copyfile(source,target)
        scores,result=inspect(target.read_bytes())
        assert result["sourcePrediction"]==label and not result["recaptureReasons"]
        examples.append({"file":artifacts(target),"expected_scores":scores.tolist(),"expected_prediction":label,
                         "expected_analysis_outcome":"CLASSIFIED","expected_recapture_reasons":[],
                         "partition":"development validation software fixture"})
    dark=directory/"too-dark.jpg"
    Image.new("RGB",(224,224),"black").save(dark,"JPEG")
    scores,result=inspect(dark.read_bytes())
    assert result["sourcePrediction"] is None and "LOW_CONTRAST" in result["recaptureReasons"]
    examples.append({"file":artifacts(dark),"expected_scores":scores.tolist(),"expected_prediction":None,
                     "expected_analysis_outcome":"RECAPTURE_REQUIRED","expected_recapture_reasons":result["recaptureReasons"],
                     "partition":"synthetic software fixture"})
    PARTS.mkdir()
    chunk_manifest={"sha256":sha256_file(directory/"best.onnx"),"bytes":(directory/"best.onnx").stat().st_size,"parts":[]}
    with (directory/"best.onnx").open("rb") as stream:
        for number in range(8):
            body=stream.read(20*1024*1024)
            if not body: break
            path=PARTS/f"best.onnx.part{number:02}"
            path.write_bytes(body)
            chunk_manifest["parts"].append({"name":path.name,"bytes":len(body),"sha256":sha256_file(path)})
        assert not stream.read(1)
    write(PARTS/"manifest.json",chunk_manifest)
    camera_answers=[{"file":e["file"],"expected_scores":e["expected_scores"],"expected_prediction":e["expected_prediction"],
                     "expected_recapture_reasons":e["expected_recapture_reasons"]} for e in examples]
    registry={"schema_version":1,"scope":"SOURCE_LABEL_SHADOW_ONLY","release_id":RELEASE.name,"default_analysis_model":"egg-grade",
              "models":[{"id":"egg-grade","model":{**artifacts(directory/"best.onnx"),"parts_revision":PARTS.name},
                         "config":artifacts(directory/"config.json"),"gate_policy":artifacts(directory/"gate-policy.json"),
                         "training_references":artifacts(directory/"training-references.npz"),"known_answer":examples[0]["file"],
                         "expected_scores":examples[0]["expected_scores"],"expected_prediction":examples[0]["expected_prediction"],
                         "input_description":"Day 16, Day 18 and Reject (source Unfertilized examples); epoch-trained head; three paused views or one attached photo",
                         "camera_head":{"capture_contract":"three-paused-views-v1","head":artifacts(directory/"head.npz"),
                                        "gate_policy":artifacts(directory/"gate-policy.json"),"training_references":artifacts(directory/"training-references.npz"),
                                        "known_answers":camera_answers}}],"software_test_examples":examples}
    write(RELEASE/"registry.json",registry)
    digest=sha256_file(RELEASE/"registry.json")
    (RELEASE/"registry.sha256").write_bytes((digest+"\n").encode())
    shutil.copytree(BASE/"licenses",RELEASE/"licenses")
    service=ModelService()
    try:
        service.load(RELEASE/"registry.json",digest)
        assert service.describe()["models"][0]["classOrder"]==CLASSES
        for example in examples:
            body=(RELEASE/example["file"]["path"]).read_bytes()
            for camera in (False,True):
                result=service._predict("egg-grade",body,camera=camera)
                assert result["sourcePrediction"]==example["expected_prediction"]
                assert result["recaptureReasons"]==example["expected_recapture_reasons"]
    finally:
        service.close()
    assert all(sha256_file(BASE/name)==digest for name,digest in protected.items())
    assert all(sha256_file(old_parts/name)==digest for name,digest in protected_parts.items())
    report={"software_serving_checks_passed":True,"release":RELEASE.name,"registry_sha256":digest,
            "model_sha256":chunk_manifest["sha256"],"camera_head_sha256":sha256_file(directory/"head.npz"),
            "class_order":CLASSES,"vendor_reject_eggs_excluded":["R1","R2","R3"],"vendor_reject_views_excluded":150,
            "reject_labels_reinterpreted_as_unfertilized":0,"test_images_opened":0,"physical_unfertilized_check_performed":False,"general_reject_condition_validated":False,"third_class_source":"UNFERTILIZED",
            "previous_releases_and_model_parts_preserved":True,"claim_99_percent_supported":False}
    write(RELEASE/"verification.json",report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=="__main__":
    main()
