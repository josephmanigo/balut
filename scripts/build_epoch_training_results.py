"""Render genuine epoch histories and locked historical confusion matrices."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_unfertilized_training_report import check_lock, read, sha, summary, np, plt
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run, evaluation, out = args.run.resolve(), args.evaluation.resolve(), args.output.resolve()
    check_lock(run, "selection-lock.json"); check_lock(evaluation, "evaluation-lock.json")
    history = [json.loads(line) for line in (run / "history.jsonl").read_text().splitlines()]
    trained, measured = read(run / "metrics.json"), read(evaluation / "metrics.json")
    selected = trained["selected_epoch"]
    assert [row["epoch"] for row in history] == list(range(1, trained["epochs_completed"] + 1))
    assert 1 <= selected <= len(history) and measured["class_order"] == ["DAY_16", "DAY_18", "REJECT"]
    config = read(run / "config.json")
    fine = config["training_method"] == "FINAL_ENCODER_BLOCKS_AND_HEAD_EPOCH_FINETUNING"
    raw = np.array(measured["overall"]["raw_confusion_matrix"])
    gated = np.array(measured["overall"]["selective_confusion_matrix"])
    values = summary(raw, gated)
    baseline = read(ROOT / "ml/runs/unfertilized-heldout-20261019-v1/metrics.json")["overall"]
    old_raw, old_gated = np.array(baseline["raw_confusion_matrix"]), np.array(baseline["selective_confusion_matrix"])
    checks = {"raw_age_correct_not_lower": int(raw[0, 0] + raw[1, 1]) >= int(old_raw[0, 0] + old_raw[1, 1]),
              "correct_each_class_not_lower": bool(all(gated[i, i] >= old_gated[i, i] for i in range(3))),
              "wrong_each_age_not_higher": bool(all(gated[i, :3].sum() - gated[i, i] <= old_gated[i, :3].sum() - old_gated[i, i] for i in range(2))),
              "coverage_not_lower": bool(gated[:, :3].sum() >= old_gated[:, :3].sum())}
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 12,
                         "xtick.labelsize": 9, "ytick.labelsize": 9, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 5, figsize=(22, 19))
    fig.subplots_adjust(left=.055, right=.985, top=.84, bottom=.455, wspace=.42, hspace=.78)
    fig.text(.055, .97, "EggGrade IoT | Actual epoch training results", fontsize=25, weight="bold", color="#173b35")
    method = "Final encoder blocks + classifier fine-tune" if fine else "Classifier-head training; retained image encoder frozen"
    fig.text(.055, .94, f"{method} | {len(history)} epochs | Selected: {selected} | Regression: {'PASSED' if all(checks.values()) else 'FAILED - candidate not promoted'}", fontsize=12, color="#52635e")
    fig.text(.055, .901,
             f"HISTORICAL TEST: RAW {values['raw_accuracy']:.2%}   |   ACCEPTED {values['accepted_accuracy']:.2%}   |   COVERAGE {values['coverage']:.2%}   |   CORRECT / ALL {values['correct_over_all']:.2%}",
             fontsize=12, weight="bold", color="#1c4d67")
    fig.add_artist(plt.Line2D([.055, .985], [.88, .88], transform=fig.transFigure, color="#ced8d4", linewidth=1))
    epochs = [row["epoch"] for row in history]
    for r, partition in enumerate(["train", "validation"]):
        for c, metric in enumerate(["loss", "accuracy", "precision", "recall", "f1"]):
            axis = axes[r, c]
            scale = 1 if metric == "loss" else 100
            ys = [row[partition][metric] * scale for row in history]
            axis.plot(epochs, ys, "o-", color="#2878b8", linewidth=1.6, markersize=3)
            axis.axvline(selected, color="#b9862d", linestyle="--", linewidth=1, label=f"Selected epoch {selected}")
            axis.set_title(f"{partition}/{metric}", loc="left", weight="bold", pad=12)
            axis.set_xlabel("Epoch")
            axis.set_ylabel("Cross-entropy" if metric == "loss" else "Percent")
            axis.set_xlim(.5, len(history) + .5)
            if metric == "loss": axis.set_ylim(bottom=0)
            else: axis.set_ylim(max(0, min(ys) - 2), min(105, max(ys) + 1))
            axis.grid(color="#e4e9e7", linewidth=.7); axis.set_axisbelow(True)
            if c == 0: axis.legend(frameon=False, fontsize=8)
    fig.text(.055, .365, "Historical regression confusion matrices | 649 previously inspected images", fontsize=19, weight="bold", color="#173b35")
    names = ["Day 16", "Day 18", "Reject"]
    for position, title, matrix in [([.08, .15, .35, .17], "Raw predictions", raw), ([.56, .15, .38, .17], "After recapture gates", gated)]:
        axis = fig.add_axes(position)
        axis.imshow(matrix, cmap="BuGn", vmin=0, vmax=int(raw.max()))
        axis.set_title(title, fontsize=15, weight="bold", pad=14)
        columns = names + (["Recapture"] if matrix.shape[1] == 4 else [])
        axis.set_xticks(range(len(columns)), columns, rotation=22, ha="right", fontsize=11)
        axis.set_yticks(range(3), names, fontsize=11)
        axis.set_xlabel("Predicted label", fontsize=12); axis.set_ylabel("Recorded label", fontsize=12)
        for i in range(3):
            for j in range(matrix.shape[1]):
                axis.text(j, i, str(matrix[i, j]), ha="center", va="center", fontsize=18, weight="bold",
                          color="white" if matrix[i, j] > raw.max() * .53 else "#173b35")
        for spine in axis.spines.values(): spine.set_visible(False)
    notes = ["DATA: 2,256 training / 814 validation / 649 historical test images. Repeated age-camera test views represent ten eggs.",
             "SOURCE: Reject is the requested output name for Unfertilized annotations. General defects and physical Reject performance are unvalidated.",
             "EVIDENCE: Curves use completed epoch records. Precision, recall and F1 are macro averages. No fabricated loss, mAP or epoch points."]
    for y, note in zip([.075, .054, .033], notes, strict=True): fig.text(.055, y, note, fontsize=10.5, color="#52635e")
    fig.canvas.draw()
    for axis in fig.axes:
        bounds = axis.get_tightbbox(fig.canvas.get_renderer())
        assert bounds.x0 >= 0 and bounds.y0 >= 0 and bounds.x1 <= fig.bbox.x1 and bounds.y1 <= fig.bbox.y1
    fig.savefig(out / "results.png", dpi=180, facecolor="white"); plt.close(fig)
    with Image.open(out / "results.png") as image:
        assert image.size == (3960, 3420); image.verify()
    with (out / "results.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["epoch", "learning_rate", *[f"{part}/{metric}" for part in ["train", "validation"] for metric in ["loss", "accuracy", "precision", "recall", "f1"]]])
        for row in history:
            writer.writerow([row["epoch"], row["learning_rate"], *[row[part][metric] for part in ["train", "validation"] for metric in ["loss", "accuracy", "precision", "recall", "f1"]]])
    for label, matrix in [("raw", raw), ("after-recapture", gated)]:
        with (out / f"confusion-matrix-{label}.csv").open("w", newline="") as stream:
            writer = csv.writer(stream); writer.writerow(["Recorded / predicted", *names, *(["Recapture"] if matrix.shape[1] == 4 else [])])
            writer.writerows([[name, *map(int, values)] for name, values in zip(names, matrix, strict=True)])
    comparison = {"run": str(run.relative_to(ROOT)), "epochs_completed": len(history), "selected_epoch": selected,
                  "historical_baseline": baseline, "candidate": measured["overall"], "regression_checks": checks,
                  "regression_admission_passed": all(checks.values()), "not_independent_field_accuracy": True,
                  "png_sha256": sha(out / "results.png"), "source_history_sha256": sha(run / "history.jsonl")}
    write_json = lambda path, value: path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    write_json(out / "comparison.json", comparison)
    for name in ["history.jsonl", "metrics.json", "config.json", "selection-lock.json", "gate-policy.json"]:
        shutil.copyfile(run / name, out / ("training-" + name))
    for name in ["metrics.json", "evaluation-plan.json", "evaluation-lock.json", "outcomes.jsonl"]:
        shutil.copyfile(evaluation / name, out / ("regression-" + name))
    (out / "README.txt").write_text(f"EggGrade IoT - Actual epoch results\n\n{method}.\nCompleted {len(history)} epochs; selected epoch {selected}.\n"
        "Training and validation graphs use actual completed records; no detection loss or mAP is invented.\n"
        "The historical test was previously inspected and is not a fresh independent test. Never claim 99% field accuracy.\n"
        "Reject is the requested name for Unfertilized source examples; no general defect or food-safety condition is established.\n"
        "No raw egg photos, account data, credentials or full model weights are included in this results packet.\n"
        "Read comparison.json for the regression admission checks; this packet alone does not prove live deployment.\n", encoding="utf-8")
    files = {path.name: sha(path) for path in out.iterdir() if path.is_file() and path.name != "bundle-manifest.json"}
    write_json(out / "bundle-manifest.json", files)
    with zipfile.ZipFile(out.with_suffix(".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
        for path in out.iterdir():
            if path.is_file(): archive.write(path, path.name)
    with zipfile.ZipFile(out.with_suffix(".zip")) as archive:
        assert archive.testzip() is None
        assert all(__import__("hashlib").sha256(archive.read(name)).hexdigest() == digest for name, digest in files.items())
    print(json.dumps(comparison), flush=True)


if __name__ == "__main__": main()
