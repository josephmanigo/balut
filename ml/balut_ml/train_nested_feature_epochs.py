"""Train small CPU heads in real epochs; choose epochs without outer-fold eggs."""
import copy
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from threadpoolctl import threadpool_limits

from .train_grouped_camera import ROOT, DATA, sha, write, metrics, fit_weights

BASE = ROOT / "ml/runs/grouped-camera-20261019"
REPS = ROOT / "ml/runs/representation-search-20261019"
RUN = ROOT / "ml/runs/nested-feature-epochs-20261019"
HIDDEN = (64, 128)
MAX_EPOCHS, PATIENCE = 60, 8


class FeatureHead(nn.Module):
    def __init__(self, fit_features, hidden):
        super().__init__()
        self.register_buffer("mean", torch.from_numpy(fit_features.mean(0)))
        self.register_buffer("scale", torch.from_numpy(fit_features.std(0).clip(.01)))
        self.layers = nn.Sequential(nn.Linear(fit_features.shape[1], hidden), nn.SiLU(), nn.Dropout(.2), nn.Linear(hidden, 3))

    def forward(self, x):
        return self.layers((x - self.mean) / self.scale)


def infer(model, x):
    model.eval()
    with torch.inference_mode():
        return model(torch.from_numpy(x)).numpy()


def train(x, truth, rows, fit, hidden, seed, epochs, folder, held=None, physical=None):
    torch.manual_seed(seed)
    model = FeatureHead(x[fit], hidden)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.01)
    weights = torch.from_numpy((fit_weights([rows[i] for i in fit], 20) * 2256 / len(fit)).astype(np.float32))
    samples = torch.from_numpy(x[fit]); targets = torch.from_numpy(truth[fit]).long()
    generator = torch.Generator().manual_seed(seed)
    best, selected, stale, best_state = None, None, 0, None
    folder.mkdir()
    for epoch in range(1, epochs + 1):
        model.train()
        order = torch.randperm(len(fit), generator=generator)
        objective = 0.
        for start in range(0, len(fit), 256):
            batch = order[start:start + 256]
            optimizer.zero_grad(set_to_none=True)
            scores = model(samples[batch])
            loss = (nn.functional.cross_entropy(scores, targets[batch], reduction="none", label_smoothing=.03) * weights[batch]).mean()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            objective += float(loss.detach()) * len(batch)
        record = {"epoch": epoch, "train": metrics(infer(model, x[fit]), truth[fit]), "optimization_loss": objective / len(fit)}
        if held is not None:
            scores = infer(model, x[held]); pred = scores.argmax(1); camera = physical[held]; actual = truth[held]
            age = [float(np.mean(pred[camera & (actual == label)] == label)) for label in range(2)]
            measured = metrics(scores, actual)
            key = (min(age), float(np.mean(age)), metrics(scores[~camera], actual[~camera])["f1"], -measured["loss"])
            record.update(validation=measured, camera_age_recall=age)
            if best is None or key > best:
                best, selected, stale = key, record, 0
                best_state = copy.deepcopy(model.state_dict())
            else:
                stale += 1
        with (folder / "history.jsonl").open("a") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        if held is not None and stale >= PATIENCE:
            break
    if held is not None:
        model.load_state_dict(best_state)
    else:
        selected = record
    torch.save({"state_dict": model.state_dict(), "hidden": hidden, "input_dim": x.shape[1]}, folder / "head.pt")
    write(folder / "summary.json", {"epochs_completed": epoch, "selected_epoch": selected["epoch"], "selected": selected})
    return model, selected["epoch"]


def main():
    if RUN.exists():
        raise FileExistsError("Preserve completed or interrupted nested CPU epoch run")
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    for folder in (BASE, REPS):
        lock = json.loads((folder / "selection-lock.json").read_text())
        assert all(sha(folder / name) == digest for name, digest in lock["artifacts"].items())
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["partition"] in ("train", "validation")]
    with np.load(REPS / "selected-features.npz", allow_pickle=False) as bank:
        x, truth = bank["features"], bank["truth"]
    with np.load(BASE / "development.npz", allow_pickle=False) as bank:
        folds = bank["folds"]
        np.testing.assert_array_equal(truth, bank["truth"])
        np.testing.assert_array_equal(bank["source_sha256"], [r["source_sha256"] for r in rows])
    groups = np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows])
    physical = np.array([bool(r.get("physical_egg_id")) for r in rows])
    protected = {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), DATA / "manifest.jsonl", BASE / "selection-lock.json",
                 REPS / "selection-lock.json", ROOT / "deployment/active-release.txt")}
    RUN.mkdir()
    write(RUN / "experiment-plan.json", {"method": "NESTED_GROUPED_CPU_FEATURE_HEAD_EPOCHS", "frozen_representation": "fused-interior",
          "hidden_units": HIDDEN, "architecture": "Fit-only input centering/scaling, Linear, SiLU, dropout0.2, Linear3",
          "max_epochs": MAX_EPOCHS, "patience": PATIENCE, "learning_rate": .001, "weight_decay": .01, "label_smoothing": .03,
          "optimizer": "AdamW", "batch_size": 256, "physical_egg_weight": 20, "fixed_total_weight": 2256,
          "inner_selection": "Inner held fold=(outer+1) mod5. Train on remaining three folds. Select weaker camera-age recall, mean recall, source macro F1, lower loss.",
          "outer_evaluation": "Refit on all four outer training folds for the selected inner epoch count; outer fold never selects stopping epoch or input statistics",
          "target": "Raw overall and both camera-age recalls >=96%", "cpu_only": True, "test_images_opened": 0,
          "development_caveat": "Architectures are compared on development outer folds. This is not a fresh independent test or field accuracy.",
          "reject_scope": "Public source Unfertilized renamed Reject; vendor R1/R2/R3 excluded", "protected_files": protected})
    candidates = []; started = time.perf_counter()
    for hidden in HIDDEN:
        folder = RUN / f"hidden-{hidden}"; folder.mkdir()
        oof = np.full((len(rows), 3), np.nan, dtype=np.float32); summaries = []
        for outer in range(5):
            inner = (outer + 1) % 5
            inner_fit = np.flatnonzero((folds != outer) & (folds != inner)); inner_held = np.flatnonzero(folds == inner)
            fit, held = np.flatnonzero(folds != outer), np.flatnonzero(folds == outer)
            assert not set(groups[inner_fit]) & set(groups[inner_held])
            assert not set(groups[held]) & (set(groups[inner_fit]) | set(groups[inner_held]))
            assert not set(groups[fit]) & set(groups[held])
            _, epoch = train(x, truth, rows, inner_fit, hidden, 42 + outer, MAX_EPOCHS, folder / f"fold-{outer + 1}-inner", inner_held, physical)
            model, _ = train(x, truth, rows, fit, hidden, 42 + outer, epoch, folder / f"fold-{outer + 1}-outer")
            oof[held] = infer(model, x[held])
            summaries.append({"outer_fold": outer + 1, "selected_inner_epoch": epoch})
            print(json.dumps({"hidden": hidden, "outer_fold_completed": outer + 1, "selected_inner_epoch": epoch,
                              "elapsed_seconds": time.perf_counter() - started}), flush=True)
        assert np.isfinite(oof).all(); pred = oof.argmax(1)
        age = [float(np.mean(pred[physical & (truth == label)] == label)) for label in range(2)]
        measured = metrics(oof, truth); source = metrics(oof[~physical], truth[~physical])
        target = measured["accuracy"] >= .96 and min(age) >= .96
        record = {"hidden": hidden, "raw": measured, "camera_age_recall": age, "source_raw": source,
                  "development_target_passed": target, "fold_selected_epochs": summaries}
        np.savez_compressed(folder / "oof.npz", scores=oof, truth=truth, folds=folds)
        write(folder / "metrics.json", record); candidates.append(record)
        print(json.dumps(record), flush=True)
    selected = max(candidates, key=lambda r: (r["development_target_passed"], min(r["camera_age_recall"]), np.mean(r["camera_age_recall"]), r["source_raw"]["f1"]))
    write(RUN / "metrics.json", {"selected": selected, "candidates": candidates, "test_images_opened": 0, "promoted": False})
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    write(RUN / "selection-lock.json", {"artifacts": {str(p.relative_to(RUN)): sha(p) for p in RUN.rglob("*") if p.is_file()}, "test_images_opened": 0})
    print(json.dumps({"complete": True, "selected": selected}), flush=True)


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main()
