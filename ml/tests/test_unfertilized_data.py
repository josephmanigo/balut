import pytest

from balut_ml.unfertilized_data import combine


def inputs():
    ages, public = [], []
    for part in ("train", "validation", "test"):
        for label in ("DAY_16", "DAY_18"):
            key = part + label
            ages.append(dict(source_label=label, partition=part, source_sha256=key, pixel_sha256=key,
                             duplicate_group=key, physical_egg_id=None))
        for n in range(50):
            egg = {"train": "R1", "validation": "R2", "test": "R3"}[part]
            ages.append(dict(source_label="REJECT", partition=part, physical_egg_id="physical-reject-20261019:"+egg))
        public.append(dict(source_label="Unfertilized", partition=part, source_sha256=part, pixel_sha256=part,
                           duplicate_group=part, crop_provenance={"source_label": "Unfertilized"}))
    return ages, public


def test_only_explicit_unfertilized_annotations_replace_removed_reject_data():
    ages, public = inputs()
    public.append(dict(source_label="Reject"))
    result = combine(ages, public)
    assert len(result) == 9
    assert {r["source_label"] for r in result} == {"DAY_16", "DAY_18", "UNFERTILIZED"}
    assert not any(r.get("physical_egg_id") for r in result)
    assert all(r["original_source_label"] == "Unfertilized" for r in result if r["source_label"] == "UNFERTILIZED")


def test_conflicting_annotation_provenance_is_rejected():
    ages, public = inputs()
    public[0]["crop_provenance"]["source_label"] = "Reject"
    with pytest.raises(ValueError, match="provenance"):
        combine(ages, public)


def test_a_public_image_family_cannot_cross_partitions():
    ages, public = inputs()
    public[1]["duplicate_group"] = public[0]["duplicate_group"]
    with pytest.raises(ValueError, match="family"):
        combine(ages, public)
