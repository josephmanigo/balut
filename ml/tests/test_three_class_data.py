import pytest

from balut_ml.train_three_class import combine_rows


def sources():
    result = {"age": [], "pat": []}
    for partition in ["train", "validation", "test"]:
        for source, labels in [("age", ["Fertile-Day-16", "Fertile-Day-18"]), ("pat", ["Reject", "Fertilized", "Unfertilized"])]:
            for label in labels:
                key = source + partition + label
                result[source].append({"source_label": label, "partition": partition, "pixel_sha256": key,
                                       "source_sha256": key, "duplicate_group": partition})
    return result


def test_joint_labels_keep_partitions_and_exclude_unmapped_pat_classes():
    original = sources()
    rows = combine_rows(original)
    assert len(rows) == 9
    assert {row["source_label"] for row in rows} == {"DAY_16", "DAY_18", "REJECT"}
    for row in rows:
        source = original[row["source_dataset"]][row["original_row_index"]]
        assert row["partition"] == source["partition"]
        assert row["original_source_label"] == source["source_label"]
        if row["source_label"] == "REJECT":
            assert row["original_source_label"] == "Reject"


def test_cross_source_label_or_partition_conflict_blocks_training():
    original = sources()
    original["pat"][0]["pixel_sha256"] = original["age"][0]["pixel_sha256"]
    with pytest.raises(ValueError, match="conflicting labels or cross-partition"):
        combine_rows(original)


def test_missing_class_in_holdout_blocks_training():
    original = sources()
    original["age"] = [row for row in original["age"] if not (row["source_label"] == "Fertile-Day-18" and row["partition"] == "test")]
    with pytest.raises(ValueError, match="Each partition"):
        combine_rows(original)
