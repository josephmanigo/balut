"""Original numbered egg cohorts and their fixed, shared dataset roles."""
import re


def partition_for(egg_id):
    match = re.fullmatch(r"(16|18)-([1-9]|1[0-5])", egg_id)
    if not match:
        raise ValueError("Expected a distinct egg ID from 16-1..16-15 or 18-1..18-15")
    age, index = map(int, match.groups())
    # Keep the originally reserved fifth egg in the completed pilot test.
    return age, "test" if index in (5, 12, 13, 14, 15) else "train" if index in (1, 2, 3, 6, 7) else "validation"
