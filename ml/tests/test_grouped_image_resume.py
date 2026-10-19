import json
from balut_ml.train_grouped_images import write


def test_training_progress_replacement_keeps_valid_json(tmp_path):
    target=tmp_path/"progress.json"
    write(target,{"fold":1,"epoch":7})
    write(target,{"fold":2,"epoch":1})
    assert json.loads(target.read_text())=={"fold":2,"epoch":1}
    assert not target.with_name("progress.json.pending").exists()
