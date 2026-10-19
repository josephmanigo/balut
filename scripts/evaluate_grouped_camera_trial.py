"""One locked historical regression of the development-selected grouped classifier."""
import hashlib
import io
import json
from pathlib import Path
from datetime import datetime,timezone

from evaluate_epoch_regression import ROOT,sha,write,summarize,ModelService,Image,ImageOps

RUN=ROOT/"ml/runs/grouped-kernel-20261019"
OUT=ROOT/"ml/runs/grouped-camera-historical-20261019"
RELEASE=ROOT/"deployment/releases/grouped-camera-trial-20261019"
DATA=ROOT/"data/local/retained-camera-epochs-reject-20261019"
CLASSES=["DAY_16","DAY_18","REJECT"]


def main():
    if OUT.exists():raise FileExistsError("Preserve the completed or interrupted regression")
    lock=json.loads((RUN/"selection-lock.json").read_text())
    assert all(sha(RUN/name)==digest for name,digest in lock["artifacts"].items())
    assert json.loads((RELEASE/"verification.json").read_text())["software_checks_passed"]
    registry=RELEASE/"registry.json";digest=(RELEASE/"registry.sha256").read_text().strip();assert sha(registry)==digest
    assert sha(RELEASE/"egg-grade/selection-lock.json")==sha(RUN/"selection-lock.json")
    manifest=DATA/"manifest.jsonl";audit=json.loads((DATA/"audit.json").read_text());assert sha(manifest)==audit["manifest_sha256"]
    rows=[json.loads(line) for line in manifest.read_text().splitlines()];test=[r for r in rows if r["partition"]=="test"]
    assert len(test)==649 and len({r["physical_egg_id"] for r in test if r.get("physical_egg_id")})==10
    protected={str(p.relative_to(ROOT)):sha(p) for p in [registry,RELEASE/"egg-grade/best.onnx",RUN/"selection-lock.json",Path(__file__)]}
    OUT.mkdir()
    write(OUT/"evaluation-plan.json",{"started_at":datetime.now(timezone.utc).isoformat(),"protected_files":protected,"class_order":CLASSES,
          "protocol":"One pass of all historical images through actual ONNX CPU serving; no fitting, threshold changes, retries or candidate selection afterward",
          "historical_role":"Previously inspected regression, not untouched independent field confirmation","images":649,
          "development_candidates":24,"known_physical_eggs_excluded_from_fitting":10,
          "promotion_checks":"Raw age correct not lower; gated correct each class not lower; wrong each age not higher; total coverage not lower"})
    service=ModelService();records=[]
    try:
        service.load(registry,digest);assert service.describe()["models"][0]["classOrder"]==CLASSES
        with (OUT/"outcomes.jsonl").open("x") as stream:
            for index,row in enumerate(test):
                path=Path(row["image_path"]);assert sha(path)==row["source_sha256"];body=path.read_bytes()
                with Image.open(io.BytesIO(body)) as image:
                    if image.format!="JPEG":
                        encoded=io.BytesIO();ImageOps.exif_transpose(image).convert("RGB").save(encoded,"JPEG",quality=95);body=encoded.getvalue()
                result=service._predict("egg-grade",body,camera=True);scores=result["sourceClassDecisionScores"]
                record={"source_sha256":row["source_sha256"],"serving_jpeg_sha256":hashlib.sha256(body).hexdigest(),"truth":row["training_label"],
                    "physical_egg_id":row.get("physical_egg_id"),"source_dataset":row["source_dataset"],"duplicate_group":row["duplicate_group"],
                    "raw_prediction":max(scores,key=scores.get),**{key:result[key] for key in ["sourcePrediction","recaptureRequested","recaptureReasons","sourceClassDecisionScores","modelReleaseId","modelSha256"]}}
                assert record["recaptureRequested"]==(record["sourcePrediction"] is None)
                records.append(record);stream.write(json.dumps(record,allow_nan=False)+"\n");stream.flush()
                if (index+1)%100==0 or index+1==len(test):print(json.dumps({"evaluated":index+1,"total":len(test)}),flush=True)
    finally:service.close()
    groups={};eggs={}
    for row in records:
        groups.setdefault(("camera:" if row["physical_egg_id"] else "source:")+row["truth"],[]).append(row)
        if row["physical_egg_id"]:eggs.setdefault(row["physical_egg_id"],[]).append(row)
    measured=summarize(records)
    old=json.loads((ROOT/"ml/runs/unfertilized-heldout-20261019-v1/metrics.json").read_text())["overall"]
    raw,prior=measured["raw_confusion_matrix"],old["raw_confusion_matrix"]
    gated,baseline=measured["selective_confusion_matrix"],old["selective_confusion_matrix"]
    checks={"raw_age_correct_not_lower":sum(raw[i][i] for i in range(2))>=sum(prior[i][i] for i in range(2)),
            "correct_each_class_not_lower":all(gated[i][i]>=baseline[i][i] for i in range(3)),
            "wrong_each_age_not_higher":all(sum(gated[i][:3])-gated[i][i]<=sum(baseline[i][:3])-baseline[i][i] for i in range(2)),
            "coverage_not_lower":measured["classified"]>=old["classified"]}
    assert all(sha(ROOT/name)==expected for name,expected in protected.items())
    write(OUT/"metrics.json",{"scope":"LOCKED_HISTORICAL_REGRESSION_NOT_NEW_FIELD_TEST","class_order":CLASSES,"overall":measured,
        "groups":{k:summarize(v) for k,v in groups.items()},"physical_eggs":{k:summarize(v) for k,v in eggs.items()},
        "baseline":old,"promotion_checks":checks,"regression_passed":all(checks.values()),"test_images_opened":len(records),"model_or_policy_changed":False})
    write(OUT/"evaluation-lock.json",{"artifacts":{name:sha(OUT/name) for name in ["evaluation-plan.json","outcomes.jsonl","metrics.json"]}})
    print((OUT/"metrics.json").read_text(),flush=True)


if __name__=="__main__":main()
