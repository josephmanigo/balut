"""Record one operator-confirmed egg placement using the physical EMEET and spinner."""
import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from PIL import Image, ImageOps, ImageDraw
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.capture_emeet_egg import finish, sha, verify_candidate, write
from scripts.prepare_emeet_rotation_study import STUDY
from scripts.spinner_control import open_spinner

def sectors(times, trace, steps=2048):
    """Estimate relative holder angle at JPEG write time, using bracketing motor polls."""
    stamps, positions = zip(*trace)
    for before, after, x, y in zip(stamps, stamps[1:], positions, positions[1:]):
        if not 0 < after-before <= 1_500_000_000 or not 0 <= (y-x) % 2**32 < steps:
            raise ValueError("Motor telemetry gap or reset; repeat this placement")
    continuous = [0]
    for x,y in zip(positions,positions[1:]):
        continuous.append(continuous[-1]+(y-x) % 2**32)
    estimated = []
    for t in times:
        i = bisect_right(stamps,t)-1
        if not 0 <= i < len(stamps)-1:
            raise ValueError("Camera frame outside measured rotation")
        estimated.append(continuous[i]+(continuous[i+1]-continuous[i])*(t-stamps[i])/(stamps[i+1]-stamps[i]))
    offset = estimated[0]
    values = [(p-offset)/steps for p in estimated]
    bins = [int((v%1)*12) for v in values]
    if values[-1] < 1 or set(bins) != set(range(12)):
        raise ValueError("A complete turn covering all twelve sectors was not recorded")
    return [(b, round((v%1)*360,1)) for b,v in zip(bins,values)]

def capture_pose(dataset, egg, pose):
    planpath=dataset/'collection-plan.json'
    plan=json.loads(planpath.read_text()); a=plan['eggs'][egg]
    if a['partition']=='test':
        verify_candidate(dataset)
    elif (dataset/'candidate-lock.json').exists():
        raise ValueError("Development closed after model lock")
    poses=plan['rotation_poses']; pos=poses.index(pose)
    folder=dataset/'captures'/egg/'two-placements'
    folder.mkdir(exist_ok=True,parents=True)
    path=folder/'record.json'
    if path.exists():
        record=json.loads(path.read_text())
        if record['plan_sha256']!=sha(planpath) or record['egg_id']!=egg:
            raise ValueError("Placement identity changed")
    else:
        record={'egg_id':egg,'source_label':a['label'],'partition':a['partition'],'plan_sha256':sha(planpath),
                'camera':plan['camera'],'started_at':datetime.now(timezone.utc).isoformat(),'status':'partial',
                'model_used_for_label':False,'rotation':{}}
    total=a['sampled_frames']; sizes=[total//2,total-total//2]
    already=len(record['rotation'].get(pose,[]))
    if any(len(record['rotation'].get(name,[]))!=sizes[i] for i,name in enumerate(poses[:pos])) or already>=sizes[pos] or record['status']=='complete':
        raise ValueError("Recorded placements must be kept; capture the next placement of this egg")
    write(path,record)
    offset=sum(sizes[:pos])+already; n=sizes[pos]-already
    stage=folder/'sessions'/(pose+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    stage.mkdir(parents=True)
    camera=plan['camera']; fps=plan['sample_fps']
    cmd=['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-f','dshow','-rtbufsize','128M','-use_wallclock_as_timestamps','1',
         '-video_size','1920x1080','-framerate','30','-vcodec','mjpeg','-i','video='+camera,'-an',
         '-vf',f"fps={fps},select=gte(n\\,{2*fps})",'-fps_mode','vfr','-frames:v',str(n),'-q:v','2',
         '-start_number',str(1+offset),str(stage/'frame-%03d.jpg')]
    trace=[]
    spinner=open_spinner()
    def poll():
        state,steps=spinner.command('STATUS')
        if state!='RUNNING':
            raise ValueError("Holder is not rotating")
        trace.append([spinner.status_timestamp_ns,steps])
    try:
        poll()
        with (stage/'camera.log').open('wb') as log, subprocess.Popen(cmd,stderr=log,stdout=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as process:
            try:
                until=time.monotonic()+n/fps+35
                while process.poll() is None:
                    poll()
                    if time.monotonic()>until:
                        raise TimeoutError("EMEET camera timed out")
                    time.sleep(.12)
                poll()
                if process.returncode:
                    raise RuntimeError((stage/'camera.log').read_text(errors='replace')[-1500:])
            finally:
                if process.poll() is None:
                    process.kill();process.wait()
    finally:
        spinner.close();write(stage/'motor-trace.json',trace)
    photos=sorted(stage.glob('frame-*.jpg'))
    if len(photos)!=n:
        raise ValueError("Incomplete camera recording")
    angles=sectors([p.stat().st_mtime_ns for p in photos],trace,plan['steps_per_turn'])
    samples=[]; thumbs={}
    known={v['pixel_sha256'] for group in record['rotation'].values() for v in group}
    import hashlib
    for p,(b,angle) in zip(photos,angles,strict=True):
        with Image.open(p) as im:
            if list(im.size)!=plan['capture_size']:raise ValueError("Unexpected image size")
            pix=hashlib.sha256(im.convert('RGB').tobytes()).hexdigest()
            if pix in known:raise ValueError("Duplicate camera image; retry placement")
            known.add(pix)
            if b not in thumbs:thumbs[b]=ImageOps.contain(im,(240,135)).copy()
        samples.append({'image':p.name,'sector':b,'estimated_holder_degrees':angle,'pixel_sha256':pix})
    sheet=Image.new('RGB',(960,3*158));draw=ImageDraw.Draw(sheet)
    for b,img in thumbs.items():
        x,y=(b%4)*240,(b//4)*158;sheet.paste(img,(x,y));draw.text((x+4,y+136),f"{pose}: sector {b+1}",fill='white')
    sheet.save(stage/'review.jpg')
    for p in photos:
        dest=folder/p.name
        if dest.exists() and sha(dest)!=sha(p):raise ValueError("Uncommitted frames exist; inspect interrupted session before retry")
        p.replace(dest)
    record['rotation'].setdefault(pose,[]).extend(samples)
    record.setdefault('telemetry',{}).setdefault(pose,[]).append({'operator_confirmed_egg_rotation':True,'trace':str((stage/'motor-trace.json').relative_to(folder)),
                          'trace_sha256':sha(stage/'motor-trace.json'),'angle_basis':'Host frame write time interpolated between motor polls; no position encoder'})
    write(path,record)
    if all(len(record['rotation'].get(name,[]))==sizes[i] for i,name in enumerate(poses)): record=finish(dataset,folder)
    return {'egg':egg,'pose':pose,'frames':n,'egg_frames':sum(map(len,record['rotation'].values())),'sectors':12,'egg_status':record['status'],'review':str(stage/'review.jpg')}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('egg');p.add_argument('pose',choices=['side-A','side-B'])
    args=p.parse_args();print(json.dumps(capture_pose(STUDY,args.egg,args.pose)))
