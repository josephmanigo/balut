"""Run actual image fine-tuning epochs with known-egg-disjoint development folds."""
import argparse
import json
import os
from pathlib import Path
import random
import shutil
import time
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG",":4096:8")

import numpy as np
import torch
from torch import nn
from torch.utils.data import Dataset,DataLoader
from torchvision import transforms
from PIL import Image,ImageOps
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from .train_grouped_camera import ROOT,DATA,CLASSES,sha,metrics,fit_weights
from .train_grouped_kernel import fit_models,scores_for
from .camera_representation import load_representation,unfreeze_tail,patch_state,restore_patch
from .feature_models import MEAN,STD

CACHE=ROOT/"ml/runs/grouped-camera-20261019"
SEARCH=ROOT/"ml/runs/representation-search-20261019"


def write(path,value):
    pending=path.with_name(path.name+".pending")
    pending.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    pending.replace(path)


class EggImages(Dataset):
    def __init__(self,images,truth,indexes,transform,weights=None):
        self.images,self.truth,self.indexes,self.transform=images,truth,indexes,transform
        self.weights=np.ones(len(indexes),dtype=np.float32) if weights is None else weights.astype(np.float32)
    def __len__(self):return len(self.indexes)
    def __getitem__(self,index):
        source=int(self.indexes[index])
        return self.transform(self.images[source]),int(self.truth[source]),float(self.weights[index])


class Classifier(nn.Module):
    def __init__(self,encoder,dim):super().__init__();self.encoder=encoder;self.head=nn.Linear(dim,3)
    def forward(self,images):
        features=self.encoder(images)
        return self.head(features),features


def infer(model,dataset,batch_size):
    values=[];features=[]
    with torch.inference_mode():
        for images,_,_ in DataLoader(dataset,batch_size=batch_size,shuffle=False,num_workers=0,pin_memory=True):
            scores,embedding=model(images.cuda(non_blocking=True));values.extend(scores.cpu().numpy());features.extend(embedding.cpu().numpy())
    return np.asarray(values),np.asarray(features)


def main(args):
    output=args.output.resolve()
    if output.exists():raise FileExistsError("Preserve the completed or interrupted epoch run")
    if not torch.cuda.is_available():raise RuntimeError("CUDA GPU required")
    torch.set_num_threads(4);torch.use_deterministic_algorithms(True);torch.backends.cudnn.benchmark=False
    search_lock=json.loads((SEARCH/"selection-lock.json").read_text())
    assert all(sha(SEARCH/name)==digest for name,digest in search_lock["artifacts"].items())
    selected=json.loads((SEARCH/"selected.json").read_text());assert args.profile==selected["profile"]
    rows=[json.loads(line) for line in (DATA/"manifest.jsonl").read_text().splitlines()]
    rows=[r for r in rows if r["partition"] in ("train","validation")]
    inputs=json.loads((CACHE/"serving-inputs.json").read_text())
    with np.load(CACHE/"development.npz",allow_pickle=False) as bank:truth,folds=bank["truth"],bank["folds"]
    with np.load(SEARCH/"selected-features.npz",allow_pickle=False) as bank:initial_features=bank["features"]
    assert len(rows)==len(inputs)==len(initial_features)==3070
    np.testing.assert_array_equal(truth,[CLASSES.index(r["training_label"]) for r in rows])
    physical=np.array([bool(r.get("physical_egg_id")) for r in rows])
    groups=np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows])
    normalized=transforms.Compose([transforms.ToTensor(),transforms.Normalize(MEAN,STD)])
    augmented=transforms.Compose([
        transforms.RandomAffine(5,translate=(.015,.015),scale=(.97,1.03),interpolation=transforms.InterpolationMode.BILINEAR,fill=(124,116,104)),
        transforms.ColorJitter(brightness=args.brightness,contrast=.15,saturation=.15),transforms.RandomGrayscale(.1),normalized])
    images=[]
    for item in inputs:
        path=Path(item["path"]);assert sha(path)==item["serving_jpeg_sha256"]
        with Image.open(path) as image:images.append(ImageOps.exif_transpose(image).convert("RGB").resize((224,224),Image.Resampling.BILINEAR))
    protected={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/"ml/balut_ml/camera_representation.py",DATA/"manifest.jsonl",SEARCH/"selection-lock.json",ROOT/"deployment/active-release.txt"]}
    output.mkdir(parents=True)
    recipe={"profile":args.profile,"batch_size":16,"max_epochs":args.max_epochs,"patience":args.patience,"encoder_lr":args.encoder_lr,
        "head_lr":args.head_lr,"weight_decay":.01,"seed":42,"label_smoothing":args.smoothing,"brightness_jitter":args.brightness,
        "other_augmentation":"training only: affine +/-5 degrees, translation +/-1.5%, scale97-103%, contrast/saturation +/-15%, grayscale10%",
        "normalization":"All batch-normalization statistics frozen; gradients in declared final encoder blocks and classifier only",
        "head_initialization":"Logistic C10 fitted only on the current fold's training features; scores scaled by0.25",
        "checkpoint_selection":"Weaker camera-age recall, mean camera-age recall, source macro F1, lower validation cross-entropy",
        "linear_and_kernel":"Record both the trained linear head and fixed C100 gamma1 RBF fit on each learned fold representation",
        "development_target":{"overall_raw":.96,"camera_day16_recall":.96,"camera_day18_recall":.96},
        "fold_scope":"Twenty development age eggs, two held per age/fold; all views of an egg and source family stay together",
        "validation_caveat":"Held folds select checkpoints; development estimates are not an independent final field test",
        "test_images_opened":0,"final_fit_policy":"Only after passing grouped target; final epoch count from fold-selected epochs, never historical test labels",
        "protected_files":protected}
    if args.resume_from:
        args.resume_from=args.resume_from.resolve()
        previous=json.loads((args.resume_from/"experiment-plan.json").read_text())
        for key in ["profile","batch_size","max_epochs","patience","encoder_lr","head_lr","weight_decay","seed","label_smoothing","brightness_jitter"]:
            if previous[key]!=recipe[key]:raise ValueError("Resume training recipe differs: "+key)
        source_key=str(Path(__file__).relative_to(ROOT))
        assert sha(args.resume_from/"training-source-original.py")==previous["protected_files"][source_key]
        for name,digest in previous["protected_files"].items():
            if name!=source_key:assert sha(ROOT/name)==digest
        recipe.update(resume_from=str(args.resume_from),resume_protocol="Copy completed folds unchanged; rerun only interrupted folds from their original seed and recipe",
                      original_training_source_sha256=previous["protected_files"][source_key])
    write(output/"experiment-plan.json",recipe)
    linear_oof=np.full((len(rows),3),np.nan,dtype=np.float32);kernel_oof=linear_oof.copy();nearest=np.zeros((len(rows),3),dtype=np.float32)
    summaries=[];started=time.perf_counter()
    for fold in range(5):
        seed=42+fold;random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
        fit,held=np.flatnonzero(folds!=fold),np.flatnonzero(folds==fold)
        assert not set(groups[fit])&set(groups[held])
        folder=output/f"fold-{fold+1}"
        previous_folder=args.resume_from/f"fold-{fold+1}" if args.resume_from else None
        if previous_folder and (previous_folder/"summary.json").exists():
            required=["summary.json","selected.json","best-patch.pt","development.npz","history.jsonl"]
            assert all((previous_folder/name).is_file() for name in required)
            shutil.copytree(previous_folder,folder)
            summary=json.loads((folder/"summary.json").read_text())
            payload=torch.load(folder/"best-patch.pt",weights_only=True,map_location="cpu")
            assert summary["fold"]==fold+1 and payload["epoch"]==summary["selected_epoch"]
            with np.load(folder/"development.npz",allow_pickle=False) as bank:
                features=bank["features"]
                np.testing.assert_array_equal(bank["truth"],truth);np.testing.assert_array_equal(bank["fit"],fit);np.testing.assert_array_equal(bank["held"],held)
            scores=features@payload["patch"]["head.weight"].numpy().T+payload["patch"]["head.bias"].numpy()
            expected=json.loads((folder/"selected.json").read_text())["validation"]["confusion_matrix"]
            assert metrics(scores[held],truth[held])["confusion_matrix"]==expected
            linear_oof[held]=scores[held]
            kernel=fit_models(features[fit],truth[fit],[rows[i] for i in fit],{"C":100.,"gamma":1.,"camera_weight":20})
            kernel_oof[held]=scores_for(kernel,features[held])
            for label in range(3):nearest[held,label]=(features[held]@features[fit[truth[fit]==label]].T).max(1)
            write(folder/"resume-verification.json",{"completed_fold_reused":True,"source":str(previous_folder),
                  "original_files":{name:sha(previous_folder/name) for name in required},"cached_feature_head_classifications_match":True})
            summaries.append(summary)
            print(json.dumps({"completed_fold_reused":fold+1,"selected_epoch":summary["selected_epoch"]}),flush=True)
            continue
        folder.mkdir()
        weights=fit_weights([rows[i] for i in fit],20)*2256/len(fit)
        initializer=LogisticRegression(C=10,max_iter=3000,random_state=42).fit(initial_features[fit],truth[fit],sample_weight=weights)
        encoder=load_representation(args.profile);unfreeze_tail(encoder)
        model=Classifier(encoder,initial_features.shape[1]).cuda().eval()
        with torch.no_grad():
            model.head.weight.copy_(torch.from_numpy(initializer.coef_).cuda()*.25);model.head.bias.copy_(torch.from_numpy(initializer.intercept_).cuda()*.25)
        train=EggImages(images,truth,fit,augmented,weights);validation=EggImages(images,truth,held,normalized)
        loader=DataLoader(train,batch_size=16,shuffle=True,num_workers=0,pin_memory=True,generator=torch.Generator().manual_seed(seed))
        optimizer=torch.optim.AdamW([{"params":[p for p in model.encoder.parameters() if p.requires_grad],"lr":args.encoder_lr},
            {"params":model.head.parameters(),"lr":args.head_lr}],weight_decay=.01)
        scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,args.max_epochs,eta_min=1e-6)
        best=None;stale=0;chosen=None
        for epoch in range(1,args.max_epochs+1):
            model.eval();train_scores=[];train_truth=[];objective=0.
            for batch,(samples,targets,sample_weights) in enumerate(loader,1):
                samples,targets,sample_weights=samples.cuda(non_blocking=True),targets.cuda(),sample_weights.cuda()
                optimizer.zero_grad(set_to_none=True);scores,_=model(samples)
                loss=(nn.functional.cross_entropy(scores,targets,reduction="none",label_smoothing=args.smoothing)*sample_weights).mean()
                loss.backward();nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],5.);optimizer.step()
                train_scores.extend(scores.detach().cpu().numpy());train_truth.extend(targets.cpu().numpy());objective+=float(loss.detach())*len(targets)
                if batch%25==0:write(output/"progress.json",{"fold":fold+1,"epoch":epoch,"batch":batch,"batches":len(loader),"elapsed_seconds":time.perf_counter()-started})
            scores,_=infer(model,validation,16);pred=scores.argmax(1);actual=truth[held];camera=physical[held]
            age=[float(np.mean(pred[camera&(actual==label)]==label)) for label in range(2)]
            measured=metrics(scores,actual);source=metrics(scores[~camera],actual[~camera])
            key=(min(age),float(np.mean(age)),source["f1"],-measured["loss"])
            record={"fold":fold+1,"epoch":epoch,"train":metrics(np.asarray(train_scores),np.asarray(train_truth)),"validation":measured,
                "camera_age_recall":age,"source_validation":source,"weighted_smoothed_optimization_loss":objective/len(fit),
                "encoder_learning_rate":optimizer.param_groups[0]["lr"],"head_learning_rate":optimizer.param_groups[1]["lr"]}
            with (folder/"history.jsonl").open("a") as stream:stream.write(json.dumps(record,allow_nan=False)+"\n")
            if best is None or key>best:
                best=key;stale=0;chosen=record
                pending=folder/"best-patch.pending.pt"
                torch.save({"patch":patch_state(model),"profile":args.profile,"epoch":epoch,"fold":fold+1,"recipe":recipe},pending)
                pending.replace(folder/"best-patch.pt")
                write(folder/"selected.json",record)
            else:stale+=1
            print(json.dumps({"fold":fold+1,"completed_epoch":epoch,"camera_age_recall":age,"validation_accuracy":measured["accuracy"],
                "validation_f1":measured["f1"],"best_epoch":chosen["epoch"],"stale":stale,"elapsed_seconds":time.perf_counter()-started}),flush=True)
            scheduler.step()
            if stale>=args.patience:break
        payload=torch.load(folder/"best-patch.pt",weights_only=True,map_location="cpu");restore_patch(model,payload["patch"])
        scores,features=infer(model,EggImages(images,truth,np.arange(len(rows)),normalized),16)
        np.testing.assert_allclose(np.linalg.norm(features,axis=1),1,atol=1e-4)
        linear_oof[held]=scores[held]
        kernel=fit_models(features[fit],truth[fit],[rows[i] for i in fit],{"C":100.,"gamma":1.,"camera_weight":20})
        kernel_oof[held]=scores_for(kernel,features[held])
        for label in range(3):nearest[held,label]=(features[held]@features[fit[truth[fit]==label]].T).max(1)
        np.savez_compressed(folder/"development.npz",features=features,truth=truth,fit=fit,held=held)
        summary={"fold":fold+1,"epochs_completed":epoch,"selected_epoch":chosen["epoch"],"selected_camera_age_recall":chosen["camera_age_recall"]}
        summaries.append(summary);write(folder/"summary.json",summary)
        del model,encoder,optimizer;torch.cuda.empty_cache()
    np.savez_compressed(output/"oof.npz",linear_scores=linear_oof,kernel_scores=kernel_oof,truth=truth,folds=folds,nearest=nearest)
    candidates=[]
    for kind,scores in [("linear",linear_oof),("rbf",kernel_oof)]:
        assert np.isfinite(scores).all();pred=scores.argmax(1)
        age=[float(np.mean(pred[physical&(truth==label)]==label)) for label in range(2)]
        measured=metrics(scores,truth);target=measured["accuracy"]>=.96 and min(age)>=.96
        candidates.append({"head":kind,"raw":measured,"camera_age_recall":age,"development_target_passed":target})
    chosen=max(candidates,key=lambda c:(c["development_target_passed"],min(c["camera_age_recall"]),np.mean(c["camera_age_recall"]),c["raw"]["f1"]))
    write(output/"metrics.json",{"profile":args.profile,"folds":summaries,"candidates":candidates,"selected":chosen,
        "final_epoch_count_from_cv":int(np.median([r["selected_epoch"] for r in summaries])),"test_images_opened":0,"promoted":False,
        "cpu_serving_validation_pending":True,"fresh_field_accuracy_established":False,"elapsed_seconds":time.perf_counter()-started})
    assert all(sha(ROOT/name)==digest for name,digest in protected.items())
    names=["experiment-plan.json","oof.npz","metrics.json",*[str(p.relative_to(output)) for p in output.glob("fold-*/*") if p.is_file()]]
    write(output/"selection-lock.json",{"artifacts":{name:sha(output/name) for name in names},"test_images_opened":0})
    print(json.dumps({"complete":True,"selected":chosen,"folds":summaries}),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--profile",required=True);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--resume-from",type=Path)
    parser.add_argument("--max-epochs",type=int,default=25);parser.add_argument("--patience",type=int,default=6)
    parser.add_argument("--encoder-lr",type=float,default=3e-5);parser.add_argument("--head-lr",type=float,default=7e-4)
    parser.add_argument("--brightness",type=float,default=.25);parser.add_argument("--smoothing",type=float,default=.03)
    with threadpool_limits(limits=4):main(parser.parse_args())
