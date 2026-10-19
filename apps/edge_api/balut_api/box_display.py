"""Send only the current accepted egg label to the identified USB display."""


def box_display_code(box):
    if not box.connected or box.error:
        return "OFFLINE"
    if box.state in {"needs_reference", "calibrating"}:
        return "CALIBRATE"
    if box.config.get("stationaryRequested") or box.state in {"settling", "analyzing", "capturing_views"}:
        return "CAPTURING"
    if box.state in {"waiting", "checking_empty"}:
        return "WAITING"
    result = box.result or {}
    if (box.state != "remove_egg" or not box.config.get("enabled") or not box.config.get("latched")
            or box.config.get("awaitingEmpty") or box.config.get("pending")
            or result.get("recaptureRequested") is not False or result.get("analysisOutcome") != "CLASSIFIED"):
        return "UNCLASSIFIED"
    return {"DAY_16": "DAY_16", "DAY_18": "DAY_18", "REJECT": "REJECT", "UNFERTILIZED": "REJECT"}.get(
        result.get("sourcePrediction"), "UNCLASSIFIED")
