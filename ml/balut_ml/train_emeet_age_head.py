"""Fit an egg-interior age head on the fixed development split. Never open test images."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'ml'), str(ROOT/'apps/edge_api')]
import numpy as np
import onnxruntime as ort
import torch
from torch import nn
from torch.nn import functional as F
from balut_ml.train_emeet_mobilenetv2 import MobileNetEgg, MEAN, STD, measured, plot_history, load_development, training_weights
from balut_api.model_service import preprocess
from balut_api.selective_gate import validate_policy
from scripts.capture_emeet_egg import sha, verify_candidate, write
from scripts.seal_emeet_candidate import CLASSES


class InteriorAge(nn.Module):
    def __init__(self):
        super().__init__()
        self.cnn = MobileNetEgg(representation='egg-roi')
        self.register_buffer('center', torch.zeros(16))
        self.register_buffer('scale', torch.ones(16))
        self.age = nn.Linear(16, 1)

    def photometry(self, x):
        rgb = (x[:,:, :, 88:136] * self.cnn.input_std + self.cnn.input_mean).clamp(0, 1)
        values = []
        for a,b in ((36,74),(76,114),(116,154),(156,192)):
            p = rgb[:,:,a:b]; r,g = p[:,0],p[:,1]
            red = torch.log1p(255*r); mean = red.mean((1,2))
            values.extend((mean, (red - mean[:,None,None]).abs().mean((1,2)),
                           (red-torch.log1p(255*g)).mean((1,2)), (r/(r+.08)).mean((1,2))))
        return torch.stack(values, dim=1)

    def combine(self, features, cnn_scores):
        z = ((features-self.center)/self.scale).clamp(-4,4)
        difference = self.age(z)
        age = torch.cat((-difference, difference), dim=1) / 2
        age = age - age.amax(1,keepdim=True)
        reject = cnn_scores[:,2:3] - cnn_scores[:,:2].amax(1,keepdim=True)
        scores = torch.cat((age, reject), dim=1)
        reference = torch.cat((z.tanh(), 3*(reject/3).tanh(), torch.ones_like(reject)*2),1)
        return scores,F.normalize(reference,dim=1)

    def forward(self,x):
        return self.combine(self.photometry(x),self.cnn(x)[0])


def train(dataset, parent, output):
    original = verify_candidate(dataset)
    original_run = Path(original['run'])
    if output.exists():
        raise FileExistsError('Keep previous runs and physical evidence immutable')
    output.mkdir(parents=True)
    torch.set_num_threads(4); torch.manual_seed(42)
    plan = {'model':'Frozen egg-ROI MobileNetV2 Reject decision; learned 16-feature binary age head',
            'fit':'18 development training eggs only; equal total weight per age and per egg within age',
            'validation':'Six separate development eggs; select checkpoint by worst age recall, then mean age recall, then binary validation loss',
            'physical_retest':'Fresh EMEET acquisitions only, both candidates scored on the same views; six previously examined reserved eggs; ten attempts each',
            'comparison':'Report first scans and all attempts. Day 18 improvement requires more correct Day 18 decisions; also report Day 16 loss and false Day 18 decisions',
            'gate':'Retain quality limits. Learn cosine floors from validation (1st percentile). Lowest margin with >=80% precision and >=5 predictions per class on supported validation rows, otherwise abstain.',
            'maximum_epochs':50,'patience':8,'optimizer':'Full-batch Adam, lr .03, L2 penalty .025 on standardized feature coefficients',
            'test_images_used_for_fitting_or_selection':0,'prior_physical_results_known':True,'fresh_independent_cohort':False,
            'original_candidate_sha256':sha(dataset/'candidate-lock.json'),'parent_training_sha256':sha(parent/'training-lock.json')}
    write(output/'protocol.json',plan)
    rows=load_development(dataset)
    trained=json.loads((parent/'training-lock.json').read_text())['artifacts']
    if any(sha(parent/name)!=digest for name,digest in trained.items()): raise ValueError('Frozen parent changed')
    parent_rows=json.loads((parent/'development-manifest.json').read_text())
    if rows!=parent_rows or rows!=json.loads((original_run/'development-manifest.json').read_text()): raise ValueError('Development data/order mismatch')
    write(output/'development-manifest.json',rows)
    source=json.loads((original_run/'calibration/serving-inputs.json').read_text())
    model=InteriorAge().eval()
    model.cnn.load_state_dict(torch.load(parent/'best.pt',weights_only=True,map_location='cpu')['state_dict'])
    model.cnn.requires_grad_(False); nn.init.zeros_(model.age.weight); nn.init.zeros_(model.age.bias)
    opts=ort.SessionOptions(); opts.intra_op_num_threads=4; opts.inter_op_num_threads=1
    parent_sess=ort.InferenceSession(str(parent/'best.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
    cfg={'normalization_mean':MEAN,'normalization_std':STD}
    photos,logits=[],[]; parity_inputs=[]
    with torch.inference_mode():
        for start in range(0,len(rows),32):
            batch=[]
            for row,item in zip(rows[start:start+32],source[start:start+32],strict=True):
                path=Path(item['path'])
                if item['source_sha256']!=row['source_sha256'] or sha(path)!=item['serving_sha256']: raise ValueError('Development input changed')
                batch.append(preprocess(path.read_bytes(),cfg))
            x=np.concatenate(batch); photos.append(model.photometry(torch.from_numpy(x)).numpy()); logits.append(parent_sess.run(None,{'images':x})[0])
            if start%512==0: parity_inputs.append(x[:2].copy())
            if start%1024==0: print('Development frames:',start,'/',len(rows),flush=True)
    features=torch.from_numpy(np.concatenate(photos)); cnn=torch.from_numpy(np.concatenate(logits))
    truth=torch.tensor([CLASSES.index(r['source_label']) for r in rows]); fit=torch.tensor([r['partition']=='train' for r in rows]); val=~fit
    age_fit=fit&(truth<2); age_val=val&(truth<2)
    all_weights=torch.from_numpy(training_weights([r for r,t in zip(rows,fit) if t])); weights=all_weights[truth[fit]<2]; weights/=weights.sum()
    with torch.no_grad():
        model.center.copy_((features[age_fit]*weights[:,None]).sum(0))
        model.scale.copy_(((features[age_fit]-model.center).square()*weights[:,None]).sum(0).sqrt().clamp_min(.05))
    z=((features-model.center)/model.scale).clamp(-4,4)
    optim=torch.optim.Adam(model.age.parameters(),lr=.03); best=None; stale=0
    for epoch in range(1,51):
        optim.zero_grad(); d=model.age(z[age_fit]).flatten()
        loss=(F.binary_cross_entropy_with_logits(d,truth[age_fit].float(),reduction='none')*weights).sum()+.025*model.age.weight.square().sum()
        loss.backward(); optim.step()
        with torch.no_grad():
            scores=model.combine(features,cnn)[0].numpy()
            tm=measured(scores[fit],truth[fit].numpy()); vm=measured(scores[val],truth[val].numpy())
            age_loss=float(F.binary_cross_entropy_with_logits(model.age(z[age_val]).flatten(),truth[age_val].float()))
        recalls=[v['recall'] for v in vm['per_class'][:2]]; key=(min(recalls),sum(recalls)/2,-age_loss)
        row={'epoch':epoch,'train':tm,'validation':vm,'age_validation_loss':age_loss}
        with (output/'history.jsonl').open('a') as f: f.write(json.dumps(row)+'\n')
        if best is None or key>best:
            best=key; state=copy.deepcopy(model.age.state_dict()); selected=epoch; stale=0
        else: stale+=1
        if stale>=8: break
    model.age.load_state_dict(state); model.eval(); torch.save(model.state_dict(),output/'best.pt')
    with torch.no_grad(): scores,emb=model.combine(features,cnn); scores=scores.numpy(); emb=emb.numpy()
    torch.onnx.export(model,torch.zeros(1,3,224,224),str(output/'best.onnx'),input_names=['images'],output_names=['decision_scores','embedding'],opset_version=17,dynamo=False,dynamic_axes={'images':{0:'batch'},'decision_scores':{0:'batch'},'embedding':{0:'batch'}})
    sess=ort.InferenceSession(str(output/'best.onnx'),sess_options=opts,providers=['CPUExecutionProvider']); parity=0.
    for x in parity_inputs:
        with torch.inference_mode(): native=model(torch.from_numpy(x))
        for a,b in zip(native,sess.run(None,{'images':x}),strict=True):
            np.testing.assert_allclose(a.numpy(),b,atol=1e-4,rtol=1e-4); parity=max(parity,float(np.abs(a.numpy()-b).max()))
    truth=truth.numpy(); fit=fit.numpy(); val=val.numpy(); folder=output/'calibration';folder.mkdir()
    policy=json.loads((original_run/'calibration/gate-policy.json').read_text()); vs=scores[val]; labels=truth[val]; winners=vs.argmax(1); margins=np.sort(vs,axis=1)[:,-1]-np.sort(vs,axis=1)[:,-2]
    similarities=np.stack([(emb[val]@emb[fit&(truth==i)].T).max(1) for i in range(3)],1)
    original_val=json.loads((original_run/'calibration/validation-outcomes.json').read_text())
    if len(original_val)!=len(labels) or any(o['row_index']!=j for o,j in zip(original_val,np.flatnonzero(val))): raise ValueError('Quality validation order changed')
    quality=np.asarray([not (set(o['recaptureReasons']) & {'IMAGE_TOO_SMALL','LOW_CONTRAST','IMAGE_TOO_BLURRY','EXPOSURE_CLIPPED'}) for o in original_val])
    accepted=np.zeros(len(labels),dtype=bool)
    for i,label in enumerate(CLASSES):
        cosine=float(np.quantile(similarities[labels==i,i],.01)); policy['minimum_training_cosine'][label]=cosine
        mask=(winners==i)&(similarities[:,i]>=cosine)&quality&(margins>0); threshold=None
        for t in np.unique(np.r_[0.,margins[mask]]):
            ok=mask&(margins>=t)
            if ok.sum()>=5 and np.mean(labels[ok]==i)>=.8: threshold=float(t); accepted|=ok; break
        policy['minimum_margin'][label]=threshold
    validate_policy(policy,emb[fit],truth[fit]); write(folder/'gate-policy.json',policy)
    np.savez_compressed(folder/'training-references.npz',features=emb[fit],labels=truth[fit])
    gated=np.zeros((3,4),dtype=int); np.add.at(gated,(labels,np.where(accepted,winners,3)),1)
    metrics={'selected_epoch':selected,'completed_epochs':epoch,'validation':measured(vs,labels),'gated_validation_counts':gated.tolist(),'onnx_cpu_parity_frames':sum(len(x) for x in parity_inputs),'maximum_parity_difference':parity,'test_images_evaluated':0,'field_accuracy_established':False}
    write(output/'metrics.json',metrics); plot_history(output)
    files=['best.pt','best.onnx','protocol.json','development-manifest.json','metrics.json','history.jsonl','epoch-curves.png','calibration/gate-policy.json','calibration/training-references.npz']
    write(output/'candidate-lock.json',{'schema_version':1,'architecture':'MobileNetV2 Reject branch + trained interior age head','run':str(output),'collection_plan_sha256':sha(dataset/'collection-plan.json'),'original_candidate_sha256':plan['original_candidate_sha256'],'artifacts':[{'path':str(output/n),'sha256':sha(output/n)} for n in files]})
    print(json.dumps({k:v for k,v in metrics.items() if k!='validation'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','parent','output'): p.add_argument(name,type=Path)
    args=p.parse_args();train(args.dataset.resolve(),args.parent.resolve(),args.output.resolve())
