"""Render the actual grouped comparison, historical metrics, and deployment decision."""
import csv
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from build_unfertilized_training_report import (
    read,sha,check_lock,np,plt,PdfReader,colors,A4,ParagraphStyle,
    SimpleDocTemplate,Paragraph,Table,TableStyle,Image,Spacer,PageBreak,
)
LINEAR=ROOT/"ml/runs/grouped-camera-20261019"
KERNEL=ROOT/"ml/runs/grouped-kernel-20261019"
TEST=ROOT/"ml/runs/grouped-camera-historical-20261019"
BASE=ROOT/"ml/runs/unfertilized-heldout-20261019-v1"
OUT=ROOT/"output/model-results/EggGrade-IoT-Grouped-Camera-Results-20261019"
PDF=ROOT/"output/pdf/EggGrade-IoT-Grouped-Camera-Results-20261019.pdf"
LABELS=["Day 16","Day 18","Reject"]
INK,MUTED="#173b35","#52635e"


def classification(matrix):
    matrix=np.asarray(matrix);rows=[]
    for i,label in enumerate(LABELS):
        tp=int(matrix[i,i]);support=int(matrix[i].sum());fp=int(matrix[:,i].sum())-tp;fn=support-tp
        p=tp/(tp+fp) if tp+fp else 0;r=tp/support
        rows.append({"class":label,"support":support,"TP":tp,"FP":fp,"FN":fn,"precision":p,"recall":r,"f1":2*tp/(2*tp+fp+fn)})
    return {"accuracy":float(np.trace(matrix)/matrix.sum()),"per_class":rows,
            **{"macro_"+key:float(np.mean([r[key] for r in rows])) for key in ["precision","recall","f1"]}}


def pct(x):return f"{100*x:.2f}%"


def main():
    for path,name in [(LINEAR,"selection-lock.json"),(KERNEL,"selection-lock.json"),(TEST,"evaluation-lock.json"),(BASE,"evaluation-lock.json")]:check_lock(path,name)
    new=read(TEST/"metrics.json");old=read(BASE/"metrics.json");selected=read(KERNEL/"metrics.json")["selected"]
    linear=[json.loads(line) for line in (LINEAR/"search.jsonl").read_text().splitlines()]
    kernel=[json.loads(line) for line in (KERNEL/"search.jsonl").read_text().splitlines()]
    assert len(linear)==18 and len(kernel)==6 and not new["regression_passed"]
    control=next(r for r in linear if r["spec"]=={"view":"fused","C":100.,"camera_weight":20})
    old_metrics=classification(old["overall"]["raw_confusion_matrix"])
    new_metrics=classification(new["overall"]["raw_confusion_matrix"])
    cv_metrics=classification(selected["raw"]["confusion_matrix"])
    OUT.mkdir(parents=True,exist_ok=True)
    report={"method":"Retained frozen DINOv2 ViT-S/14 + EfficientNet-B0; three one-vs-rest RBF SVMs",
        "candidate_count":24,"spec":selected["spec"],"development_images":3070,"physical_development_eggs":20,
        "historical_images":649,"physical_historical_eggs":10,"active_raw":old_metrics,"candidate_raw":new_metrics,"candidate_cv_raw":cv_metrics,
        "control_cv_camera_age_recall":control["camera_age_recall"],"candidate_cv_camera_age_recall":selected["camera_age_recall"],
        "active_selective":old["overall"],"candidate_selective":new["overall"],"promotion_checks":new["promotion_checks"],"promoted":False,
        "historical_is_not_fresh_independent_test":True,"field_accuracy_established":False,"source_photos_or_weights_in_packet":False}
    (OUT/"comparison.json").write_text(json.dumps(report,indent=2)+"\n")
    with (OUT/"classification-metrics.csv").open("w",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(["scope","class","support","TP","FP","FN","precision","recall","F1"])
        for scope,measured in [("active_historical_raw",old_metrics),("candidate_grouped_cv_raw",cv_metrics),("candidate_historical_raw",new_metrics)]:
            for row in measured["per_class"]:writer.writerow([scope,*[row[k] for k in ["class","support","TP","FP","FN","precision","recall","f1"]]])
    with (OUT/"same-egg-single-view-results.csv").open("w",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(["egg_id","views","old_raw_correct_fraction","new_raw_correct_fraction","old_modal_agreement","new_modal_agreement","full_scan_repeatability_test"])
        for egg in sorted(new["physical_eggs"]):
            a,b=old["physical_eggs"][egg],new["physical_eggs"][egg];truth=0 if ":16-" in egg else 1
            first,second=np.array(a["raw_confusion_matrix"])[truth],np.array(b["raw_confusion_matrix"])[truth]
            assert first.sum()==second.sum()==54
            writer.writerow([egg,54,first[truth]/54,second[truth]/54,first.max()/54,second.max()/54,False])
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11})
    fig=plt.figure(figsize=(16,13),facecolor="white")
    fig.text(.045,.961,"EggGrade IoT | Grouped camera training results",fontsize=23,weight="bold",color=INK)
    fig.text(.045,.931,"24 development candidates | 5 known-egg/family-disjoint folds | New candidate NOT promoted",fontsize=12,color=MUTED)
    ax=fig.add_axes([.045,.71,.91,.18]);ax.axis("off")
    data=[]
    for name,count,measured in [("Active / historical",649,old_metrics),("Candidate / grouped CV",3070,cv_metrics),("Candidate / historical",649,new_metrics)]:
        data.append([name,str(count),pct(measured["accuracy"]),pct(measured["macro_precision"]),pct(measured["macro_recall"]),pct(measured["macro_f1"])])
    tab=ax.table(cellText=data,colLabels=["Raw predictions","Images","Accuracy","Macro precision","Macro recall","Macro F1"],colWidths=[.30,.08,.14,.17,.15,.16],cellLoc="center",bbox=[0,0,1,1]);tab.auto_set_font_size(False);tab.set_fontsize(12)
    for (r,c),cell in tab.get_celld().items():
        cell.set_edgecolor("#dce5e1");cell.set_facecolor(INK if r==0 else "#edf5f1" if r%2 else "white")
        if r==0:cell.get_text().set_color("white");cell.get_text().set_weight("bold")
    fig.text(.045,.667,"Candidate historical raw scores by class",fontsize=17,weight="bold",color=INK)
    ax=fig.add_axes([.045,.48,.91,.15]);ax.axis("off")
    tab=ax.table(cellText=[[r["class"],r["support"],r["TP"],r["FP"],r["FN"],pct(r["precision"]),pct(r["recall"]),pct(r["f1"])] for r in new_metrics["per_class"]],colLabels=["Class","Support","TP","FP","FN","Precision","Recall","F1"],cellLoc="center",bbox=[0,0,1,1]);tab.auto_set_font_size(False);tab.set_fontsize(12)
    for (r,c),cell in tab.get_celld().items():
        cell.set_edgecolor("#dce5e1");cell.set_facecolor(INK if r==0 else "#edf5f1" if r%2 else "white")
        if r==0:cell.get_text().set_color("white");cell.get_text().set_weight("bold")
    for rect,title,key in [([.07,.16,.36,.24],"Raw historical predictions","raw_confusion_matrix"),([.55,.16,.39,.24],"After recapture gates","selective_confusion_matrix")]:
        ax=fig.add_axes(rect);matrix=np.array(new["overall"][key]);ax.imshow(matrix,cmap="BuGn",vmin=0,vmax=266)
        ax.set_title(title,fontsize=16,weight="bold",pad=12)
        ax.set_xticks(range(matrix.shape[1]),LABELS+(["Recapture"] if matrix.shape[1]==4 else []),rotation=18,ha="right")
        ax.set_yticks(range(3),LABELS);ax.set_xlabel("Predicted label");ax.set_ylabel("Recorded label")
        for i in range(3):
            for j in range(matrix.shape[1]):ax.text(j,i,str(matrix[i,j]),ha="center",va="center",fontsize=18,weight="bold",color="white" if matrix[i,j]>140 else INK)
    fig.text(.045,.09,"Raw accuracy improves 84.75% to 88.14%; correct / all after gates falls 65.18% to 48.54%. Current app model retained.",fontsize=11.5,color=INK)
    fig.text(.045,.066,"Candidate: 315 correct classifications, 0 wrong, 334 recaptures. 100% accepted accuracy covers only 48.54% of inputs.",fontsize=11.5,color=INK)
    fig.text(.045,.039,"Historical images were previously inspected. Reject is the Unfertilized source category; no general defect or field accuracy claim.",fontsize=10.5,color=MUTED)
    fig.canvas.draw()
    for axis in fig.axes:
        b=axis.get_tightbbox(fig.canvas.get_renderer());assert b.x0>=0 and b.y0>=0 and b.x1<=fig.bbox.x1 and b.y1<=fig.bbox.y1
    fig.savefig(OUT/"results.png",dpi=180);plt.close(fig)
    fig,axes=plt.subplots(2,1,figsize=(9,7))
    all_candidates=linear+kernel
    for label,color in [(0,"#2878b8"),(1,"#bd733a")]:axes[0].plot(range(1,25),[100*r["camera_age_recall"][label] for r in all_candidates],"o-",label=LABELS[label],markersize=3,color=color)
    chosen_id=18+selected["number"];axes[0].axvline(chosen_id,color="#8c7348",linestyle="--",label=f"Selected {chosen_id}")
    axes[0].axvline(18.5,color="#aebdb6",linestyle=":");axes[0].set_ylim(80,100)
    axes[0].set_title("Actual grouped-CV camera recall | 18 linear + 6 kernel settings",loc="left",weight="bold")
    axes[0].set_xlabel("Candidate ID (not epochs)");axes[0].set_ylabel("Recall (%)");axes[0].legend(ncol=3,fontsize=8);axes[0].grid(alpha=.2)
    with np.load(KERNEL/"selected-oof.npz",allow_pickle=False) as bank:prediction=bank["scores"].argmax(1);truth=bank["truth"]
    with np.load(LINEAR/"development.npz",allow_pickle=False) as bank:folds=bank["folds"]
    rows=[json.loads(line) for line in (ROOT/"data/local/retained-camera-epochs-reject-20261019/manifest.jsonl").read_text().splitlines() if json.loads(line)["partition"]!="test"]
    physical=np.array([bool(r.get("physical_egg_id")) for r in rows])
    for label,color in [(0,"#2878b8"),(1,"#bd733a")]:
        ys=[100*np.mean(prediction[physical&(truth==label)&(folds==i)]==label) for i in range(5)]
        axes[1].bar(np.arange(1,6)+(label-.5)*.3,ys,width=.3,color=color,label=LABELS[label])
    axes[1].set_ylim(0,105);axes[1].set_xticks(range(1,6));axes[1].set_xlabel("Held-out development fold");axes[1].set_ylabel("Recall (%)")
    axes[1].set_title("Selected classifier | two held-out eggs per age in every fold",loc="left",weight="bold");axes[1].legend();axes[1].grid(axis="y",alpha=.2)
    fig.tight_layout(pad=2);fig.savefig(OUT/"cross-validation-comparison.png",dpi=180);plt.close(fig)

    styles={"title":ParagraphStyle("title",fontName="Helvetica-Bold",fontSize=23,leading=28,textColor=colors.HexColor(INK),spaceAfter=12),
            "body":ParagraphStyle("body",fontName="Helvetica",fontSize=10.2,leading=14,textColor=colors.HexColor(INK),spaceAfter=9),
            "q":ParagraphStyle("q",fontName="Helvetica-Bold",fontSize=12,leading=16,textColor=colors.HexColor("#217a68"),spaceBefore=8,spaceAfter=7),
            "small":ParagraphStyle("small",fontName="Helvetica",fontSize=8.7,leading=11.5,textColor=colors.HexColor(MUTED),spaceAfter=7)}
    story=[]
    def p(text,style="body"):story.append(Paragraph(text,styles[style]))
    def table(data,widths):
        t=Table([[Paragraph(str(x),styles["small"]) for x in row] for row in data],colWidths=widths,hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#dfede6")),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#c8d8cf")),("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]));story.append(t);story.append(Spacer(1,8))
    p("Grouped camera model results","title")
    p("EggGrade IoT | 19 October 2026 | Improved raw classifier; current app model retained.","small")
    p("The new classifier makes <b>22 more correct raw predictions</b> on the same historical 649 images: 572 correct versus 550. Its conservative recapture gates reduce useful classifications, so the candidate fails deployment checks. It is not active in the web or mobile backend.")
    p("How this candidate was trained","q")
    p("We retained the frozen DINOv2 ViT-S/14 and EfficientNet-B0 encoders. All 3,070 development images were recomputed using the actual ONNX CPU pipeline. Twenty development age eggs were available, versus ten eggs used to fit the previous model. The remaining ten historical age eggs stayed excluded from fitting.")
    p("Five grouped folds kept every view of each known physical egg and every recorded public image family together. Each fold held out two eggs per age. We compared eighteen regularized linear heads and six one-vs-rest RBF SVM settings. Selection used mean physical-egg recall, the weaker age recall, worst camera-fold recall, and source macro F1. The selected kernel uses <b>C=100, gamma=1</b>; each physical egg's weight is shared over its views, with balanced positive/negative effective weight.")
    p("The selected head was refitted on all development data. Margin and novelty thresholds came from out-of-fold development predictions. Gate calibration counts are optimistic development results. The SVM optimization is <b>not a new CNN epoch run</b>; the old eleven-epoch image experiment remains separately archived.")
    table([["Camera raw recall / same folds","Linear control","Selected kernel"],["Day 16",pct(control["camera_age_recall"][0]),pct(selected["camera_age_recall"][0])],["Day 18",pct(control["camera_age_recall"][1]),pct(selected["camera_age_recall"][1])],["Mean",pct(np.mean(control["camera_age_recall"])),pct(np.mean(selected["camera_age_recall"]))]],[265,120,120])
    p("Software verification","q")
    p("Portable kernel scores agree with the fitted classifiers; ONNX CPU scores and embeddings exactly match the cached CPU pipeline on a fixed 64-image development sample. Startup fixtures cover all three class labels and a synthetic dark-image recapture. Original models, original images, live history and motor capture behavior are preserved.")
    p("Reject is only the requested name for original public Unfertilized annotations. R1/R2/R3 are excluded. Public egg/farm identities and biological label authority are incomplete. No confirmed physical Unfertilized egg or new independent field batch was tested.","small")
    story.append(PageBreak());p("Historical comparison and formulas","title")
    table([["Raw evaluation","Accuracy","Macro precision","Macro recall","Macro F1"],*[[name,pct(m["accuracy"]),pct(m["macro_precision"]),pct(m["macro_recall"]),pct(m["macro_f1"])] for name,m in [("Active historical",old_metrics),("Candidate grouped CV",cv_metrics),("Candidate historical",new_metrics)]]],[145,80,95,95,90])
    table([["Candidate historical","Support","Precision","Recall","F1"],*[[r["class"],r["support"],pct(r["precision"]),pct(r["recall"]),pct(r["f1"])] for r in new_metrics["per_class"]]],[145,80,95,95,90])
    p("Rows are recorded labels; columns are predicted labels. Last column is Recapture.","small")
    table([["After gates","Day 16","Day 18","Reject","Recapture"],*[[LABELS[i],*row] for i,row in enumerate(new["overall"]["selective_confusion_matrix"])]],[145,90,90,90,90])
    table([["Serving measure","Active model","Candidate"],["Correct / classified","423 / 444 (95.27%)","315 / 315 (100.00%)"],["Coverage","444 / 649 (68.41%)","315 / 649 (48.54%)"],["Correct / all inputs","423 / 649 (65.18%)","315 / 649 (48.54%)"],["Wrong classifications",21,0],["Recaptures",205,334]],[205,150,150])
    p("Why the app model stays unchanged","q")
    p("The candidate improves raw age predictions and reduces accepted errors, but classified Day 16 images fall from 165 correct to 69, and Day 18 from 201 to 189. Overall useful correct outputs fall from 423 to 315. A 100% accepted subset with less than half the input coverage does not establish better end-to-end grading.")
    p("Precision=TP/(TP+FP); recall=TP/(TP+FN); F1=2TP/(2TP+FP+FN). Macro F1 averages the three class F1 scores. Raw accuracy=(266+232+74)/649=88.14%. These are recorded-label image metrics, not prospective field accuracy.","small")
    story.append(PageBreak());p("Actual cross-validation graphs","title")
    p("These points compare actual candidate settings and held-out folds. They are not fabricated epoch or loss curves.","small")
    story.append(Image(str(OUT/"cross-validation-comparison.png"),width=505,height=505*7/9))
    p("Repeatability and leakage limits","q")
    p("The CSV packet compares raw label agreement and correctness across the 54 saved views of each historical egg. Different-angle image predictions are not repeated independent live three-view scans. A consistent wrong majority is still wrong. No 0.5 score tolerance has been established.")
    p("Known egg IDs, source hashes, pixel hashes and recorded source families remain isolated as required by their partitions/folds. However, unknown public egg/batch relationships cannot be excluded. Historical images were inspected in previous experiments and used as a regression comparison after locking this candidate, not a new blind field study. No model fitting or threshold adjustment followed this historical evaluation.")
    p("Next evidence required: new independently labelled eggs/batches and a locked full-scan repeatability study. Reusing more views of the same thirty eggs cannot establish population field accuracy or a 99% guarantee.","small")
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont("Helvetica",8);canvas.setFillColor(colors.HexColor(MUTED));canvas.drawString(45,26,"EggGrade IoT | Grouped development and historical regression | 19 October 2026");canvas.drawRightString(A4[0]-45,26,str(doc.page));canvas.restoreState()
    PDF.parent.mkdir(exist_ok=True);SimpleDocTemplate(str(PDF),pagesize=A4,leftMargin=45,rightMargin=45,topMargin=43,bottomMargin=48).build(story,onFirstPage=footer,onLaterPages=footer)
    reader=PdfReader(PDF);assert len(reader.pages)==3,len(reader.pages)
    assert all(len(page.extract_text())>700 for page in reader.pages)
    for source,name in [(LINEAR/"search.jsonl","linear-search.jsonl"),(KERNEL/"search.jsonl","kernel-search.jsonl"),(KERNEL/"experiment-plan.json","kernel-plan.json"),(KERNEL/"selection-lock.json","selection-lock.json"),(TEST/"evaluation-plan.json","historical-plan.json"),(TEST/"evaluation-lock.json","historical-lock.json"),(TEST/"outcomes.jsonl","historical-outcomes.jsonl")]:shutil.copyfile(source,OUT/name)
    (OUT/"README.txt").write_text("Actual grouped development comparison and locked historical regression. Candidate NOT promoted: coverage and correct-over-all decrease. No field accuracy, no full-scan repeatability or 99% claim. Reject names source Unfertilized only. No raw photographs, credentials or model weights included. See comparison.json and PDF.\n")
    files={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!="bundle-manifest.json"};files[PDF.name]=sha(PDF)
    (OUT/"bundle-manifest.json").write_text(json.dumps(files,indent=2)+"\n")
    with zipfile.ZipFile(OUT.with_suffix(".zip"),"w",zipfile.ZIP_DEFLATED) as archive:
        for path in OUT.iterdir():
            if path.is_file():archive.write(path,path.name)
        archive.write(PDF,PDF.name)
    with zipfile.ZipFile(OUT.with_suffix(".zip")) as archive:assert archive.testzip() is None
    print(json.dumps({"raw_before":old_metrics,"raw_after":new_metrics,"promotion_checks":new["promotion_checks"],"pdf":str(PDF),"pages":3}),flush=True)


if __name__=="__main__":main()
