import pytest

from scripts.capture_rotating_emeet import sectors
from scripts.prepare_emeet_rotation_study import make_plan


def test_source_targets_and_heldout_eggs():
    eggs = make_plan()["eggs"]
    for age, total, tests in [(16,10,2),(18,10,2)]:
        group=[v for v in eggs.values() if v["label"]==f"DAY_{age}"]
        assert len(group)==total
        assert sum(v["sampled_frames"] for v in group)==3000
        assert all(v["sampled_frames"]==300 for v in group)
        assert sum(v["partition"]=="test" for v in group)==tests


def test_motor_wrap_is_valid_but_no_turn_or_missing_timestamps_is_not():
    trace=[(i*100_000_000,(2**32-128+i*64)%2**32) for i in range(60)]
    times=[t+1 for t,_ in trace[:-1]]
    assert {b for b,_ in sectors(times,trace)}==set(range(12))
    with pytest.raises(ValueError,match="complete turn"):
        sectors(times[:10],trace)
    with pytest.raises(ValueError,match="outside"):
        sectors([times[0]-2,*times],trace)
