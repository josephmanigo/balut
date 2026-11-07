"""Generate the defense guide from the locked 20-egg study. Requires matplotlib and reportlab."""
from collections import Counter
from html import escape
import json
from pathlib import Path
from statistics import median
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "tmp/pdfdeps").is_dir():
    sys.path.append(str(ROOT / "tmp/pdfdeps"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

SOURCE = ROOT / "apps/web/public/assets/study-20261107-v4"
OUT = ROOT / "output/egggrade-panel-guide"
PDF = ROOT / "output/pdf/EggGrade-Panel-Defense.pdf"
NAMES = ("Day 16", "Day 18", "Reject")
KEYS = ("DAY_16", "DAY_18", "REJECT")
NAVY, BLUE, AMBER, TEAL, RED, GRAY = "#163448", "#2069A0", "#B65D12", "#14756B", "#AE4541", "#60717C"
PAPER, BACK, LINE = "#FFFFFF", "#EDF3F4", "#D5E0E4"
V4 = "https://egggradeiot.vercel.app/assets/study-20261107-v4/"
BIO = "https://pmc.ncbi.nlm.nih.gov/articles/PMC12167807/"
CNN = "https://openaccess.thecvf.com/content_cvpr_2018/html/Sandler_MobileNetV2_Inverted_Residuals_CVPR_2018_paper.html"
ISO = "https://www.iso.org/standard/78176.html"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


HISTORY = [json.loads(line) for line in (SOURCE/"history.jsonl").read_text().splitlines()]
MET = read(SOURCE/"metrics.json")
PHY = read(SOURCE/"physical-results.json")
FIRST, REP = PHY["primary_first_attempt_per_egg"], PHY["repeated_attempts"]
EDGE = read(SOURCE/"edge-comparison.json")
SELECT = EDGE["candidate" if EDGE["changed"] else "baseline"]
AUDIT_PATH = ROOT/"data/local/emeet-20-rotation-20261107/audit.json"
if not AUDIT_PATH.exists():
    AUDIT_PATH = ROOT/"apps/web/public/assets/study-20261107-v5/dataset-audit.json"
AUDIT = read(AUDIT_PATH)
LOG = PHY["scan_log"]


def check_sources():
    assert [r["epoch"] for r in HISTORY] == list(range(1, 12))
    assert MET["selected_epoch"] == 1 and MET["epochs_completed"] == 11
    assert MET["test_images_opened"] == 0
    assert AUDIT["class_counts"] == {"DAY_16": 3000, "DAY_18": 3000, "REJECT": 3814}
    assert sum(AUDIT["partition_counts"]["train"].values()) == MET["training_images"] == 6633
    assert sum(AUDIT["partition_counts"]["validation"].values()) == MET["validation_images"] == 1770
    assert len(LOG) == 40 and PHY["unique_scored_camera_views"] == 120
    for metric, logs in ((FIRST, [r for r in LOG if r["attempt"] == 1]), (REP, LOG)):
        matrix = [[sum(r["truth"] == label and r["outcome"] == outcome for r in logs)
                   for outcome in metric["outcome_order"]] for label in KEYS]
        assert matrix == metric["confusion_matrix"]
        assert metric["correct"] == sum(matrix[i][i] for i in range(3))
    assert (FIRST["correct"], REP["correct"], REP["wrong_classified"], REP["unclassified"]) == (3, 28, 3, 9)


def style(axis, grid="y"):
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["bottom", "left"]].set_color(LINE)
    axis.grid(axis=grid, color=LINE, linewidth=.65)
    axis.set_axisbelow(True)
    axis.tick_params(color=LINE, labelcolor=NAVY, length=3)


FIGURES = {}


def save(fig, slug, title, caption, top=.83, bottom=.14):
    fig.set_facecolor("white")
    fig.text(.035,.965,title,ha="left",va="top",size=19,weight="bold",color=NAVY)
    fig.text(.035,.025,caption,va="bottom",size=9,color=GRAY,linespacing=1.4)
    fig.subplots_adjust(top=top,bottom=bottom)
    fig.savefig(OUT/(slug+".png"),dpi=190,facecolor="white")
    plt.close(fig)
    FIGURES[slug]=(title,caption)


def chart_epochs():
    fig,axes=plt.subplots(2,2,figsize=(10.2,7.0))
    fig.subplots_adjust(left=.10,right=.975,wspace=.25,hspace=.52)
    epochs=[r["epoch"] for r in HISTORY]
    for ax,(title,key) in zip(axes.flat,[("Cross-entropy loss","loss"),("Accuracy (%)","raw_accuracy"),
                                          ("Validation macro F1 (%)","macro_f1"),("Day 18 validation recall (%)","recall")]):
        style(ax)
        for split,col in ([("train",BLUE),("validation",AMBER)] if key in {"loss","raw_accuracy"} else [("validation",TEAL)]):
            vals=[r[split]["per_class"][1]["recall"] if key=="recall" else r[split][key] for r in HISTORY]
            vals=np.array(vals)*(1 if key=="loss" else 100)
            ax.plot(epochs,vals,"o-",ms=3,lw=2,label=split.title(),color=col)
            if split=="validation":ax.scatter(1,vals[0],marker="D",s=45,color=col,edgecolor="white",zorder=4)
        ax.axvline(3.5,color=GRAY,ls="--",lw=1)
        ax.set(xlim=(.65,11.35),xticks=[1,3,4,6,8,10,11],xlabel="Completed epoch")
        ax.set_title(title,loc="left",fontsize=12,weight="bold")
        if key in {"loss","raw_accuracy"}:ax.legend(fontsize=8,frameon=False)
        if key!="loss":ax.set_ylim(60 if key=="recall" else 85,101)
    save(fig,"01-training-history","Training history across 11 epochs",
         "Diamond = selected epoch 1. Dashed line = encoder fine-tuning began at epoch 4.\nDay 18 is the target age of interest. Its training count equals Day 16's.",top=.865,bottom=.16)


def chart_balance():
    fig,axes=plt.subplots(1,2,figsize=(11,5.2))
    fig.subplots_adjust(left=.085,right=.98,wspace=.29)
    x=np.arange(3); ax,bx=axes; bottom=np.zeros(3)
    for part,c in (("train",BLUE),("validation","#6BA89F"),("test","#D7A75F")):
        vals=np.array([AUDIT["partition_counts"][part][k] for k in KEYS])
        ax.bar(x,vals,bottom=bottom,width=.65,color=c,label=part.title())
        for i,val in enumerate(vals):ax.text(i,bottom[i]+val/2,f"{val:,}",ha="center",va="center",size=9,color="white" if part=="train" else NAVY)
        bottom+=vals
    for i,num in enumerate(bottom):ax.text(i,num+60,f"{num:,.0f}",ha="center",weight="bold")
    ax.set_title("Recorded images by partition",loc="left",weight="bold",size=12)
    ax.set_ylabel("Images");ax.set_ylim(0,4400);ax.legend(loc="upper left",frameon=False,ncols=3,fontsize=7)
    train=[AUDIT["partition_counts"]["train"][k] for k in KEYS];units=sum(train)/3
    for bars in [bx.bar(x-.18,train,.35,color=BLUE,label="Images seen per epoch"),
                 bx.bar(x+.18,[units]*3,.35,color="#CE812D",label="Sum of loss weights")]:
        bx.bar_label(bars,fmt="%.0f",size=8,padding=3)
    bx.set_ylim(0,3700);bx.legend(fontsize=8,frameon=False,loc="upper left")
    bx.set_title("Class contribution during fitting",loc="left",weight="bold",size=12)
    bx.set_ylabel("Images or loss-weight units")
    for a in axes:style(a);a.set_xticks(x,NAMES)
    save(fig,"02-class-balance","Dataset size and class weighting",
         "Each training image was sampled once per epoch. Loss weights give each class 2,211 weight units.\nThe 211 archived Reject test images were excluded from physical scoring.",top=.78,bottom=.21)


def matrix(ax, counts, outcomes, title, missing_row=False):
    data=np.array(counts,dtype=float)
    if missing_row:data[-1,:]=np.nan
    cmap=plt.colormaps["Blues"].copy();cmap.set_bad("#EDF0F1")
    ax.imshow(data,aspect="auto",cmap=cmap,vmin=0,vmax=max(1,np.nanmax(data)))
    for (y,x),v in np.ndenumerate(data):
        ax.text(x,y,"n/a" if np.isnan(v) else str(int(v)),ha="center",va="center",
                weight="bold",size=13,color="white" if v>np.nanmax(data)*.55 else NAVY)
    ax.set_xticks(range(len(outcomes)),outcomes,size=8);ax.set_yticks(range(3),NAMES,size=9)
    ax.set_xlabel("Predicted class / scanner outcome",size=9)
    ax.set_ylabel("Known class",size=9);ax.set_title(title,loc="left",size=12,weight="bold",pad=10)
    ax.tick_params(length=0,pad=5)
    for s in ax.spines.values():s.set_visible(False)


def chart_matrices():
    fig,axs=plt.subplots(1,2,figsize=(11.3,4.6));fig.subplots_adjust(left=.075,right=.98,wspace=.26)
    matrix(axs[0],MET["validation"]["raw_confusion_matrix"],NAMES,"CNN top prediction")
    matrix(axs[1],SELECT["metrics"]["selective_confusion_matrix"],[*NAMES,"Recapture"],"After scanner rules")
    save(fig,"03-validation-confusion","Validation confusion matrices",
         "Counts from 1,770 validation images. Both panels use the same images. Each heatmap has its own color scale.",top=.75,bottom=.22)
    fig,axs=plt.subplots(1,2,figsize=(11.3,4.6));fig.subplots_adjust(left=.075,right=.98,wspace=.24)
    outcomes=(*NAMES,"Recap.","Acq. fail")
    matrix(axs[0],FIRST["confusion_matrix"],outcomes,"First scan per egg  |  4 attempts",True)
    matrix(axs[1],REP["confusion_matrix"],outcomes,"All scans on those eggs  |  40 attempts",True)
    save(fig,"04-physical-confusion","Physical test confusion matrices",
         "Cell values are counts. Recap. = recapture. Acq. fail = acquisition failure. Gray cells have no physical Reject egg.\nThe 40 attempts include the first four. Each heatmap has its own color scale.",top=.75,bottom=.24)


def chart_metrics():
    fig,axes=plt.subplots(1,3,figsize=(11.6,4.8),sharey=True);fig.subplots_adjust(left=.065,right=.98,wspace=.12)
    panels=[("Raw validation",MET["validation"]["per_class"]),
            ("Validation after scanner rules",[dict(precision=m["gated_precision"],recall=m["gated_recall"],f1=m["gated_f1"]) for m in [SELECT["per_class"][k] for k in KEYS]]),
            ("Physical repeated scans",REP["per_class"])]
    for ax,(title,rows) in zip(axes,panels):
        style(ax);ax.set_ylim(0,116);ax.set_title(title,loc="left",size=11,weight="bold")
        for j,(key,c) in enumerate([("precision",BLUE),("recall","#D89A3D"),("f1",TEAL)]):
            val=[np.nan if r[key] is None else r[key]*100 for r in rows]
            ax.bar(np.arange(3)+(j-1)*.24,val,width=.22,color=c,label=key.upper() if key=="f1" else key.title())
        ax.set_xticks(range(3),NAMES,fontsize=9);ax.set_yticks([0,25,50,75,100])
    axes[0].set_ylabel("Score (%)");axes[2].text(2,12,"n/a",ha="center",color=GRAY)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc="upper left",bbox_to_anchor=(.04,.88),ncols=3,frameon=False,fontsize=9)
    save(fig,"05-class-metrics","Precision, recall and F1 by class",
         "Physical scores use ten scans on each of four eggs. A recapture counts as a missed prediction for its known class.\nReject has validation images but no physical test support.",top=.72,bottom=.19)


def chart_repeats():
    ids=sorted({r["egg_id"] for r in LOG});outcomes=["DAY_16","DAY_18","REJECT","UNCLASSIFIED","ACQUISITION_FAILURE"]
    arr=np.array([[outcomes.index(r["outcome"]) for r in sorted((r for r in LOG if r["egg_id"]==egg),key=lambda r:r["attempt"])] for egg in ids])
    palette=[BLUE,TEAL,"#996583","#D4A047",RED]
    fig,ax=plt.subplots(figsize=(10.9,4.2));fig.subplots_adjust(left=.11,right=.98)
    ax.imshow(arr,cmap=ListedColormap(palette),vmin=-.5,vmax=4.5,aspect="auto")
    for (y,x),v in np.ndenumerate(arr):
        ax.text(x,y,["16","18","RJ","R","F"][v],ha="center",va="center",color=NAVY if v==3 else "white",weight="bold",size=12)
    ax.set(xticks=range(10),xticklabels=range(1,11),yticks=range(4),yticklabels=ids,xlabel="Fresh scan number");ax.set_ylabel("Physical egg")
    ax.axvline(.5,color="white",lw=3);ax.tick_params(length=0,pad=5)
    for s in ax.spines.values():s.set_visible(False)
    save(fig,"06-repeatability","Ten fresh scans of each reserved egg",
         "Read one row to follow the same egg. 16 and 18 are returned ages; R = recapture.\nThe first column supplies the primary accuracy result.",top=.78,bottom=.24)


def chart_latency():
    ids=sorted({r["egg_id"] for r in LOG})
    fig,ax=plt.subplots(figsize=(10.6,4.5));fig.subplots_adjust(left=.13,right=.97)
    for i,egg in enumerate(ids):
        rows=[r for r in LOG if r["egg_id"]==egg]
        for j,r in enumerate(rows):
            ax.scatter(r["seconds"],i+(j-4.5)*.043,color=BLUE if egg.startswith("D16") else TEAL,s=45,edgecolor="white",lw=.5)
    m=median(r["seconds"] for r in LOG);ax.axvline(m,color=AMBER,ls="--",label=f"Overall median {m:.2f} s")
    style(ax,"x");ax.set_yticks(range(4),ids);ax.invert_yaxis();ax.set_xlabel("Seconds from acquisition start to decision");ax.legend(frameon=False,fontsize=9,loc="lower right",bbox_to_anchor=(1,1))
    save(fig,"07-response-time","Scan time on the EMEET test rig",
         "Each point is one measured scan, including camera acquisition and local CPU inference.\nAll 40 attempts returned a grade or a recapture decision.",top=.79,bottom=.23)


QA = {
    1:("How did you train the model?",
       "We collected 300 real EMEET images from each of 20 age-confirmed duck eggs. Each egg turned in two placements with 150 frames per placement. We reused the source-labeled Reject collection and trained a three-class classifier on 6,633 images. We resized inputs to 224 x 224 pixels, normalized them, and initialized MobileNetV2 from ImageNet weights. AdamW optimized weighted cross-entropy with batch size 32 and seed 42. Mild geometric and brightness changes applied only during training. Each egg or source family received equal weight within its class, and each class received equal total weight."),
    2:("Why did you choose this split?",
       "For each age, six eggs trained the weights, two selected the checkpoint and scanner thresholds, and two were reserved for a physical test. That gave a 60/20/20 split by egg and kept every angle of one egg in one partition. We used the available ten eggs per age to preserve two separate eggs for each evaluation step. Reject retained its historical source-family split. The four reserved age eggs stayed outside fitting and calibration."),
    3:("Where can we see precision, recall and F1?",
       "The metric table reports all three by class. The raw validation model got 1,748 of 1,770 images correct (98.76%); its macro F1 was 98.78%. The locked scanner returned 1,414 correct grades, zero wrong grades and 356 recaptures on those same images (79.89% correct across all views). In the 40 fresh physical scans, Day 16 F1 was 81.08% and Day 18 F1 was 76.47%. Physical Reject metrics are unavailable because there were zero confirmed Reject test eggs."),
    4:("How did you compute the scores?",
       "Accuracy = correct / all attempts. Precision = TP / (TP + FP). Recall = TP / (TP + FN). F1 = 2TP / (2TP + FP + FN). For Day 18 across all 40 physical attempts, TP = 13, FP = 1 and FN = 7. Precision = 13/14 = 92.86%, recall = 13/20 = 65.00% and F1 = 26/34 = 76.47%. The seven misses were two Day 16 grades and five recaptures. Macro F1 averages the supported class F1 values; weighted F1 weights classes by support."),
    5:("Did repeated scans of the same egg agree?",
       "We reopened the EMEET for ten fresh scans per reserved egg. Each scan used three new camera views after warmup. D18-09 returned Day 18 on all ten attempts. D18-10 returned Day 18 three times, Day 16 twice and recapture five times. D16-09 was correct eight times and D16-10 seven times. Only one of four eggs returned the same class every time. Numerical scores varied on all four eggs, so none met the stricter identical-output criterion."),
    6:("Why did Day 16 and Day 18 get confused?",
       "The ground-truth difference is 48 hours in the operator's reported incubation record. The scanner sees light transmitted through the shell. In this study some eggs of both ages showed a dark center and bright rim. On D18-10, Day 16 was the top prediction in 21 of 30 fresh views. A second issue was the scanner's quality rule: on D16-09 all 30 top predictions were correct, yet two scans requested recapture because too few views passed its sharpness check. The measurements establish both types of error. They cannot identify the anatomical cause of an individual error."),
    7:("Which epoch did you stop at, and why?",
       "We completed 11 epochs and restored the checkpoint from epoch 1, which had the highest validation macro F1 (0.98777). Epochs 1-3 trained the new classifier head. At epoch 4 we unfroze the last five encoder blocks and reset the patience counter. Epochs 4-11 did not improve the best validation macro F1 by more than 0.001, so eight stale fine-tuning epochs triggered stopping. The cap was 50. The deployed-for-test checkpoint therefore used the trained head with the ImageNet encoder."),
    8:("Was there data leakage?",
       "The audit found no known cross-partition physical-egg, recorded source-family or exact-image overlap. All 6,000 age frames had distinct decoded pixel hashes. We locked the candidate and decision rules before recording the reserved eggs, then scored 120 fresh physical views. However, egg and batch identities in the archived Reject source are incomplete, some eggs may have appeared in earlier project experiments, and age images and public Reject images came from different camera domains. Random frame-level splitting would have overstated independence. No group or hash check eliminates all possible bias."),
    9:("Which CNN did you use?",
       "We used MobileNetV2 with a three-class output: Day 16, Day 18 and Reject. Its lightweight convolution blocks use depthwise convolutions, inverted residual connections and linear bottlenecks. The EMEET supplied images, the ESP32 controlled the rotating holder, the RTX 3080 trained the model, and the host CPU ran the exported ONNX model during physical testing. The physical trials used this locked research candidate; the Vercel scanner still serves the earlier release."),
    10:("What is your field-testing accuracy?",
        "Our controlled physical result was 3/4 correct (75%) on the first scan of each reserved egg. D18-10's first scan requested recapture. Across ten scans of each egg, 28/40 were correct (70%), three were wrong and nine requested recapture. All 40 camera acquisitions succeeded. Of the 31 scans that returned a grade, 28 were correct (90.32%). Median time was 6.05 seconds per scan. Broad production-field accuracy remains unestablished: only four age eggs were tested, and physical Reject support was zero.")
}
BIO_NOTE = ("A published duck staging study placed the same HH39 developmental stage at about day 16 in Pekin ducks "
            "and day 18.5 in Mulard ducks (Trela et al., Table 5). This illustrates why elapsed age and visible development "
            "can differ. Our EMEET trial did not establish a breed-specific marker, confirm anatomy through candling, or measure viability.")
OBJECTIVES = [
    ("01   Integrate camera, microcontroller and CNN","Demonstrated on the test rig.",
     "The EMEET supplied images. The ESP32 drove holder rotation and reported motor steps. MobileNetV2 ran on the host CPU for the 40 physical scan decisions.",
     "Describe these roles explicitly. On-device CNN inference would require a separate microcontroller deployment and benchmark."),
    ("02   Collect labeled images and validate the classifier","Dataset and validation complete. Stability remains limited.",
     "The audited corpus contains 3,000 Day 16 images, 3,000 Day 18 images and 3,814 archived Reject images. Validation metrics and four physical egg results are available. The retained Reject annotations do not independently establish dead embryo or spoilage.",
     "Define the stakeholder's acceptable accuracy and stability thresholds before the next independent trial. Collect confirmed physical Reject examples to measure that class."),
    ("03   Grade eggs using a decision rule and rotating holder","Rotation and software decisions demonstrated; bin sorting unverified.",
     "Each egg was recorded over 12 estimated holder sectors in two placements. Margin, image-quality and similarity checks assess individual views. At least two accepted views must agree to return a grade. Operators still placed, repositioned and removed the eggs.",
     "For a physical sorting trial, log the commanded grade, actual destination, recaptures, manual interventions and routing time per egg. Compute correct deliveries divided by all attempted sorts."),
    ("04   Evaluate ISO/IEC 25010 qualities and real operation","Controlled measurements complete; stakeholder and production evaluation pending.",
     "The rig recorded 28/40 correct repeat scans, median response time 6.05 s and 40/40 completed acquisitions. Some dataset collection attempts had holder-status timeouts and needed a retry. A blank vendor, farmer and technical-evaluator instrument is available.",
     "Record the ISO/IEC 25010 edition used. Administer the instrument to all three groups, summarize responses and missing values separately, and repeat timed accuracy and dependability tests in an actual production setting.")
]

def metric_rows():
    rows=[]
    for i,name in enumerate(NAMES):
        r=MET["validation"]["per_class"][i]
        rows.append(["Raw validation",name,r["support"],r["precision"],r["recall"],r["f1"]])
    for name,key in zip(NAMES,KEYS):
        r=SELECT["per_class"][key]
        rows.append(["Scanner validation",name,r["views"],r["gated_precision"],r["gated_recall"],r["gated_f1"]])
    for name,r in zip(NAMES,REP["per_class"]):
        rows.append(["Physical repeats",name,r["support"],r["precision"],r["recall"],r["f1"]])
    return [[*r[:3],*[("n/a" if x is None else f"{x:.2%}") for x in r[3:]]] for r in rows]


class Book:
    def __init__(self):
        PDF.parent.mkdir(exist_ok=True,parents=True)
        self.c=Canvas(str(PDF),pagesize=A4,pageCompression=1)
        self.c.setTitle("EggGrade | Panel defense and study figures")
        self.c.setAuthor("EggGrade study")
        self.w,self.h=A4;self.x=39;self.width=self.w-2*self.x
        self.number=0

    def page(self,title,topic):
        if self.number:
            self.end()
        self.number+=1
        c=self.c;c.setFillColor(colors.HexColor(TEAL));c.setFont("Helvetica-Bold",9)
        c.drawString(self.x,self.h-38,"EGGGRADE   /   EMEET STUDY")
        c.drawRightString(self.w-self.x,self.h-38,topic.upper())
        c.setStrokeColor(colors.HexColor(LINE));c.line(self.x,self.h-48,self.w-self.x,self.h-48)
        self.y=self.h-72
        self.block(title,size=23,bold=True,leading=26,gap=13)

    def block(self,text,size=10.8,bold=False,leading=None,gap=8,color=NAVY):
        p=Paragraph(escape(text),ParagraphStyle("body",fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,leading=leading or size*1.38,textColor=colors.HexColor(color)))
        _,height=p.wrap(self.width,1000)
        self.y-=height;p.drawOn(self.c,self.x,self.y);self.y-=gap

    def qa(self,n):
        q,a=QA[n]
        self.block(f"{n:02d}    {q}",size=12.3,bold=True,gap=3)
        self.block(a)

    def figure(self,slug):
        from PIL import Image
        p=OUT/(slug+".png")
        with Image.open(p) as im:
            w,h=im.size
        height=self.width*h/w;self.y-=height
        self.c.drawImage(str(p),self.x,self.y,width=self.width,height=height);self.y-=9

    def grid(self,head,rows,widths):
        c=self.c
        for i,row in enumerate([head,*rows]):
            y=self.y-19
            c.setFillColor(colors.HexColor(NAVY if i==0 else (BACK if i%2 else PAPER)))
            c.rect(self.x,y,self.width,19,fill=1,stroke=0)
            x=self.x
            c.setFillColor(colors.HexColor(PAPER if i==0 else NAVY));c.setFont("Helvetica-Bold" if i==0 else "Helvetica",9)
            for s,w in zip(row,widths,strict=True):
                c.drawString(x+5,y+5.5,str(s));x+=self.width*w
            self.y=y
        self.y-=12

    def end(self):
        if self.y<44:
            raise ValueError(f"PDF page {self.number} overflows by {44-self.y:.1f} pt")
        c=self.c;c.setStrokeColor(colors.HexColor(LINE));c.line(self.x,33,self.w-self.x,33)
        c.setFont("Helvetica",8);c.setFillColor(colors.HexColor(GRAY))
        c.drawString(self.x,20,"EggGrade  |  20-egg controlled study  |  7 November 2026")
        c.drawRightString(self.w-self.x,20,f"{self.number}");c.showPage()

    def link(self,label,url):
        c=self.c;c.setFont("Helvetica",9.5);c.setFillColor(colors.HexColor(TEAL))
        self.y-=12;c.drawString(self.x,self.y,label)
        c.linkURL(url,(self.x,self.y-2,self.x+c.stringWidth(label,"Helvetica",9.5),self.y+10),relative=0,thickness=0)
        self.y-=3


def make_pdf():
    b=Book();b.page("What happened on real eggs?","Physical test")
    b.block("3 of 4 eggs correct on the first scan",size=19,bold=True,color=TEAL)
    b.qa(10);b.figure("04-physical-confusion")
    b.block("How to read the matrices",size=13,bold=True)
    b.block("Read across each row. In the 20 scans of confirmed Day 18 eggs, the scanner correctly returned Day 18 thirteen times, returned Day 16 twice and requested five recaptures. A recapture is a decision to take another view. Reject is a biological class label.")
    b.link("Open the verified run records and physical results",V4+"index.html")
    b.page("How the dataset was divided","Data & leakage")
    b.qa(2);b.figure("02-class-balance");b.qa(8)
    b.grid(["Partition","Day 16 images","Day 18 images","Reject images"],[[p.title(),*AUDIT["partition_counts"][p].values()] for p in ("train","validation","test")],[.23,.255,.255,.26])
    b.block("Each age class has 10 physical eggs. The 211 archived Reject test images appear in the manifest only. Physical test scoring used fresh camera views.",size=9.7)
    b.page("How MobileNetV2 was trained","Training & stopping")
    b.qa(9);b.qa(1);b.figure("01-training-history");b.qa(7)
    b.page("Precision, recall and F1","Classification metrics")
    b.qa(3);b.figure("05-class-metrics")
    b.grid(["Measurement","Class","Support","Precision","Recall","F1"],metric_rows(),[.25,.14,.12,.17,.15,.17])
    b.block("The physical table uses scans as the unit. For the primary first-scan measure, Day 16 recall was 2/2 and Day 18 recall was 1/2. Reject has zero physical support.",size=9.8)
    b.page("The two-day distinction","Computation & confusion")
    b.qa(4);b.figure("03-validation-confusion");b.qa(6);b.block(BIO_NOTE,size=10.1)
    b.link("Trela et al. | Developmental stages of Pekin and Mulard ducks",BIO)
    b.page("How consistent was each egg?","Repeatability & time")
    b.qa(5);b.figure("06-repeatability");b.figure("07-response-time")
    b.block("The strict test required identical labels, identical classify/recapture decisions and identical score vectors. The median scan time includes camera acquisition and host inference.",size=9.6)
    b.page("Evidence for the four objectives","Objective alignment")
    for title,status,evidence,missing in OBJECTIVES:
        b.block(title,size=12.5,bold=True,gap=3)
        b.block(status,size=10.3,bold=True,color=TEAL,gap=4)
        b.block(evidence,size=10.1,gap=4);b.block(missing,size=10.1,gap=11)
    b.link("Blank stakeholder instrument | Observed tasks and rating sheet",V4+"evaluation-instrument.html")
    b.link("ISO | ISO/IEC 25010 product quality model",ISO)
    b.link("Sandler et al. | MobileNetV2 architecture",CNN)
    b.link("EggGrade | Epoch log, confusion counts and physical scan records",V4+"index.html")
    b.end();b.c.save()


def htmltable(head,rows):
    def cells(row,tag):
        return "".join(f"<{tag}>{escape(str(x))}</{tag}>" for x in row)
    return ("<div class='scroll'><table><thead><tr>"+cells(head,"th")+"</tr></thead><tbody>"+
            "".join("<tr>"+cells(row,"td")+"</tr>" for row in rows)+"</tbody></table></div>")


def make_html():
    def figure(slug):
        t,caption=FIGURES[slug]
        return f'<figure><a href="{slug}.png"><img src="{slug}.png" alt="{escape(t)}"></a><figcaption>{escape(caption)} <a href="{slug}.png" download>Download PNG</a></figcaption></figure>'
    figs={1:"01-training-history",2:"02-class-balance",3:"05-class-metrics",5:"06-repeatability",6:"03-validation-confusion",10:"04-physical-confusion"}
    sections=[]
    for i,(q,a) in QA.items():
        content=f'<section id="q{i}"><h2>{i}. {q}</h2><p>{escape(a)}</p>'
        if i in figs:content+=figure(figs[i])
        if i==3:content+=htmltable(["Measurement","Class","Support","Precision","Recall","F1"],metric_rows())
        if i==4:
            content+="<p>Coverage = 31/40 = 77.5%. Accuracy among classified scans = 28/31 = 90.32%. Report it alongside accuracy over all 40 attempts.</p>"
        if i==6:content+=f'<p>{escape(BIO_NOTE)} <a href="{BIO}">Duck staging study</a>.</p>'
        if i==9:content+=f'<p><a href="{CNN}">MobileNetV2 architecture paper</a></p>'
        if i==10:content+=figure("07-response-time")
        sections.append(content+"</section>")
    objectives="".join(f'<article><h3>{escape(t)}</h3><strong>{escape(s)}</strong><p>{escape(e)}</p><p>{escape(m)}</p></article>' for t,s,e,m in OBJECTIVES)
    html=f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EggGrade | Panel answers and figures</title><style>
*{{box-sizing:border-box}}body{{background:#f5f8f7;color:#173447;font:17px/1.55 system-ui,sans-serif;margin:0}}
main{{max-width:950px;margin:auto;background:white;padding:clamp(18px,5vw,58px)}}h1{{font-size:clamp(30px,5vw,50px);line-height:1.1}}
h2,h3{{line-height:1.25}}a{{color:#075f66}}section{{border-top:1px solid #cbdcde;margin-top:2.2em;padding-top:.8em}}
figure{{margin:1.2em 0}}img{{width:100%;height:auto}}figcaption,small{{color:#4b636b}}nav a{{margin-right:1em}}.scroll{{overflow-x:auto}}
table{{border-collapse:collapse}}td,th{{padding:.4em .7em;text-align:left;border:1px solid #d5e0e4}}th{{background:#eaf3f1}}
article{{padding:0 1em;border-left:3px solid #14756b;margin:1.7em 0}}.lead{{font-size:1.22em}}
</style><main><h1>EggGrade panel guide</h1><p class="lead"><strong>Three of four reserved eggs were correct on the first scan.</strong> Across all 40 fresh scans, 28 were correct, three returned the wrong age and nine requested another view.</p>
<nav><a href="EggGrade-Panel-Defense.pdf">Printable panel packet</a> <a href="EggGrade-Charts.zip">Download all seven charts</a> <a href="{V4}index.html">Full run evidence</a> <a href="#objectives">Study objectives</a></nav>
{''.join(sections)}<section id="objectives"><h2>Alignment with the study objectives</h2>{objectives}<p><a href="{V4}evaluation-instrument.html">Blank stakeholder questionnaire</a> · <a href="{ISO}">ISO product quality model</a></p></section></main></html>"""
    (OUT/"index.html").write_text(html,encoding="utf-8")


def main():
    check_sources()
    OUT.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.labelcolor":NAVY,"text.color":NAVY,"axes.titlecolor":NAVY})
    chart_epochs();chart_balance();chart_matrices();chart_metrics();chart_repeats();chart_latency()
    make_pdf()
    import shutil
    shutil.copyfile(PDF,OUT/PDF.name)
    shutil.copyfile(AUDIT_PATH,OUT/"dataset-audit.json")
    with ZipFile(OUT/"EggGrade-Charts.zip","w",compression=ZIP_DEFLATED) as z:
        for slug in FIGURES:z.write(OUT/(slug+".png"),slug+".png")
    make_html()
    print(OUT)

if __name__=="__main__":
    main()
