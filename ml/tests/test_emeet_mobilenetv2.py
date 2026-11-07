import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
import torch

from balut_ml.train_emeet_mobilenetv2 import MobileNetEgg, measured, training_weights
from scripts.prepare_emeet_study import retain_reject
from scripts.capture_emeet_egg import sha, write


def test_metrics_match_count_based_computation():
    result = measured([[5, 0, 0], [0, 5, 0], [0, 5, 0], [0, 0, 5]], [0, 1, 2, 2])
    assert result["raw_confusion_matrix"] == [[1, 0, 0], [0, 1, 0], [0, 1, 1]]
    assert result["raw_accuracy"] == .75
    day18 = result["per_class"][1]
    assert (day18["TP"], day18["FP"], day18["FN"]) == (1, 1, 0)
    assert day18["precision"] == .5 and day18["recall"] == 1
    assert day18["f1"] == pytest.approx(2 / 3)
    assert result["macro_f1"] == pytest.approx((1 + 2 / 3 + 2 / 3) / 3)


def test_weights_balance_physical_groups_and_classes():
    rows = [{"source_label": "DAY_16", "physical_egg_id": "egg-a"}] * 3
    rows += [{"source_label": "DAY_16", "physical_egg_id": "egg-b"}]
    rows += [{"source_label": "DAY_18", "physical_egg_id": "egg-c"}] * 2
    rows += [{"source_label": "REJECT", "duplicate_group": "public-family"}] * 4
    weights = training_weights(rows)
    assert weights[:3].sum() == pytest.approx(weights[3])
    assert weights[:4].sum() == pytest.approx(weights[4:6].sum())
    assert weights[6:].sum() == pytest.approx(weights[:4].sum())


def test_mobilenet_is_trainable_and_returns_serving_contract():
    torch.set_num_threads(2)
    model = MobileNetEgg(pretrained=False).eval()
    logits, embedding = model(torch.randn(2, 3, 224, 224))
    assert logits.shape == (2, 3) and embedding.shape == (2, 1280)
    np.testing.assert_allclose(embedding.detach().norm(dim=1), 1, atol=1e-5)
    torch.nn.functional.cross_entropy(logits, torch.tensor([0, 1])).backward()
    assert model.classifier[1].weight.grad is not None
    assert model.features[-1][0].weight.grad is not None


def test_embedded_roi_removes_side_background_and_gamma_brightens_shadows():
    torch.set_num_threads(2)
    rgb = MobileNetEgg(representation="egg-roi").eval()
    gamma = MobileNetEgg(representation="egg-roi-gamma").eval()
    values = (torch.full((1, 3, 224, 224), .04) - rgb.input_mean) / rgb.input_std
    changed = values.clone(); changed[:, :, :, :48] = 9.; changed[:, :, :, 176:] = -9.
    torch.testing.assert_close(rgb.image_representation(values), rgb.image_representation(changed), rtol=0, atol=0)
    plain = rgb.image_representation(values) * rgb.input_std + rgb.input_mean
    bright = gamma.image_representation(values) * gamma.input_std + gamma.input_mean
    assert float(plain[0, 0, 112, 112]) == pytest.approx(.04)
    assert float(bright[0, 0, 112, 112]) == pytest.approx(.2)
    assert float(bright[0, 0, 0, 0]) == pytest.approx(0)
    logits, embedding = gamma(values)
    assert logits.shape == (1, 3) and torch.isfinite(logits).all()
    torch.testing.assert_close(embedding.norm(dim=1), torch.ones(1))


def test_reject_retention_excludes_old_ages_and_preserves_source_labels(tmp_path):
    source, target = tmp_path / "source", tmp_path / "new-study"
    source.mkdir()
    rows = []
    for index, label in enumerate(["Reject", "Unfertilized", "Fertilized", "DAY_16", "DAY_18"]):
        image = source / f"{index}.png"
        Image.new("RGB", (40, 40), (30 + index, 40, 50)).save(image)
        rows.append({"image_path": str(image), "source_sha256": sha(image), "source_label": label,
                     "duplicate_group": f"group-{index}", "partition": "train"})
    (source / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    write(source / "audit.json", {"manifest_sha256": sha(source / "manifest.jsonl")})
    audit = retain_reject(target, source)
    assert audit["images"] == 2 and audit["old_age_images_included"] == 0
    retained = [json.loads(line) for line in (target / "reject/manifest.jsonl").read_text().splitlines()]
    assert {r["source_annotation"] for r in retained} == {"Reject", "Unfertilized"}
    assert {r["source_label"] for r in retained} == {"REJECT"}
    assert all(sha(Path(r["image_path"])) == r["source_sha256"] for r in retained)
