"""Verified ONNX source-label inference. This service grants no grading authority."""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import time
import warnings
from pathlib import Path

MULTIVIEW_POLICY = "three-timed-views-v1"


def active_registry(root: Path) -> Path:
    pointer = root / "deployment/active-release.txt"
    release = pointer.read_text().strip() if pointer.exists() else "automatic-recapture-20260912"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,80}", release) or release in {".", ".."}:
        raise ValueError("Invalid active model release")
    return root / "deployment/releases" / release / "registry.json"


def view_consensus(results, hashes):
    if len(results) != 3 or len(hashes) != 3:
        raise ValueError("Automatic analysis requires three views")
    accepted = {digest: result["sourcePrediction"] for result, digest in zip(results, hashes, strict=True)
                if not result["recaptureRequested"] and result["analysisOutcome"] == "CLASSIFIED" and result["sourcePrediction"]}
    labels = set(accepted.values())
    prediction = next(iter(labels)) if len(accepted) >= 2 and len(labels) == 1 else None
    reasons = [] if prediction else ["MULTIVIEW_DISAGREEMENT" if len(labels) > 1 else "MULTIVIEW_INSUFFICIENT_ACCEPTED_VIEWS"]
    if prediction is None:
        reasons += sorted({reason for view in results for reason in view["recaptureReasons"]})
    return prediction, reasons, len(accepted)


def combine_views(results, hashes):
    prediction, reasons, accepted = view_consensus(results, hashes)
    # Keep scores and quality measurements attached to their individual view, never invent a combined probability.
    result = {key: results[0][key] for key in ("modelId", "modelReleaseId", "registrySha256", "modelSha256",
              "isSimulated", "operationalOutcome", "operationalUseAuthorized", "authority", "limitations")}
    result.update(sourcePrediction=prediction, analysisOutcome="CLASSIFIED" if prediction else "RECAPTURE_REQUIRED",
                  recaptureRequested=prediction is None, recaptureReasons=reasons, reviewRequired=False,
                  inferenceMs=round(sum(view["inferenceMs"] for view in results), 3),
                  multiView={"policy": MULTIVIEW_POLICY, "capture": "timed_rotating_holder", "anglesVerified": False,
                             "acceptedDistinctViews": accepted,
                             "views": [{**view, "imageHash": digest} for view, digest in zip(results, hashes, strict=True)]})
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_jpeg(body: bytes):
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as image:
                if image.format != "JPEG" or min(image.size) < 32 or image.width * image.height > 16_000_000:
                    raise ValueError("Expected a JPEG between 32 pixels per side and 16 megapixels")
                image.verify()
            with Image.open(io.BytesIO(body)) as image:
                image.load()
                return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid or oversized JPEG") from exc


def preprocess(body, config):
    import numpy as np
    from PIL import Image
    image = decode_jpeg(body).resize((224, 224), Image.Resampling.BILINEAR)
    values = np.asarray(image, dtype=np.float32) / 255.0
    values = (values - np.asarray(config["normalization_mean"], dtype=np.float32)) / np.asarray(config["normalization_std"], dtype=np.float32)
    return np.ascontiguousarray(values.transpose(2, 0, 1)[None])


class ModelBusyError(RuntimeError):
    pass


class ModelService:
    def __init__(self):
        self.models = {}
        self.release_id = None
        self.registry_sha256 = None
        self.analysis_model_id = None
        self.gate = threading.BoundedSemaphore(1)

    def load(self, path: Path, expected_sha256: str | None):
        import numpy as np
        import onnxruntime as ort
        digest = sha256_file(path)
        if expected_sha256 and digest != expected_sha256:
            raise ValueError("Model registry checksum mismatch")
        registry = json.loads(path.read_text(encoding="utf-8"))
        if registry.get("schema_version") != 1 or registry.get("scope") != "SOURCE_LABEL_SHADOW_ONLY":
            raise ValueError("Unsupported model registry scope")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,80}", registry["release_id"]):
            raise ValueError("Invalid model release identity")
        loaded = {}
        root = path.parent.resolve()

        def verified(artifact):
            candidate = (root / artifact["path"]).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                raise ValueError("Model artifact path is invalid")
            if sha256_file(candidate) != artifact["sha256"]:
                raise ValueError("Model artifact checksum mismatch")
            return candidate

        if not 1 <= len(registry["models"]) <= 8:
            raise ValueError("Registry must contain one to eight models")
        for entry in registry["models"]:
            model_id = entry["id"]
            if model_id in loaded or not re.fullmatch(r"[a-z0-9-]{3,60}", model_id):
                raise ValueError("Invalid or duplicate model ID")
            model_path, config_path = verified(entry["model"]), verified(entry["config"])
            config = json.loads(config_path.read_text(encoding="utf-8"))
            classes = config["class_order"]
            if config["status"] not in {"EXPLORATORY_PUBLIC_SOURCE_CLASSIFIER", "EXPLORATORY_FROZEN_FEATURE_CLASSIFIER"} or config["operational_use_authorized"] is not False:
                raise ValueError("Model contract does not permit source-label-only serving")
            if config["input_size"] != 224 or config["normalization_mean"] != [0.485, 0.456, 0.406] or config["normalization_std"] != [0.229, 0.224, 0.225]:
                raise ValueError("Unsupported input transform")
            if len(classes) not in {2, 3} or len(set(classes)) != len(classes):
                raise ValueError("Invalid class mapping")
            selective = config.get("selective_inference", False)
            if not isinstance(selective, bool) or bool(entry.get("gate_policy")) != selective or bool(entry.get("training_references")) != selective:
                raise ValueError("Incomplete selective inference contract")
            policy, references, reference_labels = None, None, None
            if selective:
                from .selective_gate import CLASSES, validate_policy
                if classes != CLASSES:
                    raise ValueError("Selective model class mapping mismatch")
                policy_path, reference_path = verified(entry["gate_policy"]), verified(entry["training_references"])
                if (sha256_file(policy_path) != config["gate_policy_sha256"]
                        or sha256_file(reference_path) != config["references_sha256"]):
                    raise ValueError("Recapture artifacts differ from the trained model contract")
                policy = json.loads(policy_path.read_text())
                with np.load(reference_path, allow_pickle=False) as bank:
                    references, reference_labels = bank["features"], bank["labels"]
                validate_policy(policy, references, reference_labels)
            options = ort.SessionOptions()
            options.intra_op_num_threads = 4
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
            inputs, outputs = session.get_inputs(), session.get_outputs()
            if len(inputs) != 1 or inputs[0].type != "tensor(float)" or inputs[0].shape[1:] != [3, 224, 224] or len(outputs) != (2 if selective else 1):
                raise ValueError("Unsupported ONNX input/output contract")
            if selective and ([o.name for o in outputs] != ["decision_scores", "embedding"] or outputs[1].shape[1:] != [references.shape[1]]):
                raise ValueError("Unsupported selective ONNX output contract")
            fixture = verified(entry["known_answer"])
            fixture_outputs = session.run(None, {inputs[0].name: preprocess(fixture.read_bytes(), config)})
            actual = fixture_outputs[0]
            expected = np.asarray(entry["expected_scores"], dtype=np.float32)
            if actual.shape != (1, len(classes)) or expected.shape != (len(classes),) or not np.isfinite(actual).all() or not np.isfinite(expected).all():
                raise ValueError("Invalid known-answer output")
            if not np.allclose(actual[0], expected, atol=1e-4, rtol=1e-4) or int(actual[0].argmax()) != int(expected.argmax()):
                raise ValueError("Model known-answer verification failed")
            if selective:
                from .selective_gate import decide
                embedding = fixture_outputs[1]
                known_result = decide(actual[0], embedding[0], decode_jpeg(fixture.read_bytes()), policy, references, reference_labels)
                if known_result["analysisOutcome"] != "CLASSIFIED" or known_result["sourcePrediction"] != entry["expected_prediction"]:
                    raise ValueError("Automatic recapture known-answer verification failed")
            loaded[model_id] = {"session": session, "config": config, "entry": entry, "input_name": inputs[0].name,
                                "policy": policy, "references": references, "reference_labels": reference_labels}
        analysis_id = registry.get("default_analysis_model")
        if analysis_id is not None:
            if analysis_id not in loaded:
                raise ValueError("Default egg analysis model is missing")
            config = loaded[analysis_id]["config"]
            if config.get("task") != "THREE_CLASS_EGG_APPEARANCE" or config["class_order"] != ["DAY_16", "DAY_18", "REJECT"]:
                raise ValueError("Default egg analysis model must support Day 16, Day 18, and Reject")
        examples = registry.get("software_test_examples", [])
        if examples:
            if analysis_id is None:
                raise ValueError("Software test examples require an analysis model")
            model = loaded[analysis_id]
            covered = set()
            for example in examples:
                body = verified(example["file"]).read_bytes()
                outputs = model["session"].run(None, {model["input_name"]: preprocess(body, model["config"])})
                scores = outputs[0]
                expected = np.asarray(example["expected_scores"], dtype=np.float32)
                if (scores.shape != (1, 3) or expected.shape != (3,) or not np.isfinite(expected).all()
                        or not np.isfinite(scores).all()
                        or not np.allclose(scores[0], expected, atol=1e-4, rtol=1e-4)):
                    raise ValueError("Software test example model output mismatch")
                if model["policy"] is not None:
                    embedding = outputs[1]
                    if embedding.shape != (1, model["references"].shape[1]):
                        raise ValueError("Software test example embedding mismatch")
                    result = decide(scores[0], embedding[0], decode_jpeg(body), model["policy"], model["references"], model["reference_labels"])
                    if (result["sourcePrediction"] != example["expected_prediction"]
                            or result["analysisOutcome"] != example["expected_analysis_outcome"]
                            or result["recaptureReasons"] != example["expected_recapture_reasons"]):
                        raise ValueError("Software test example recapture decision mismatch")
                    covered.add(result["sourcePrediction"])
                else:
                    prediction = model["config"]["class_order"][int(scores[0].argmax())]
                    if prediction != example["expected_prediction"]:
                        raise ValueError("Software test example prediction mismatch")
                    covered.add(prediction)
            required = {"DAY_16", "DAY_18", "REJECT", None} if model["policy"] is not None else {"DAY_16", "DAY_18", "REJECT"}
            if covered != required:
                raise ValueError("Software test examples must cover every class and recapture")
        self.models, self.release_id, self.registry_sha256 = loaded, registry["release_id"], digest
        self.analysis_model_id = analysis_id

    def describe(self):
        analysis = self.models.get(self.analysis_model_id, {}).get("config", {})
        return {"releaseId": self.release_id, "registrySha256": self.registry_sha256,
                "experimental": analysis.get("experimental", False), "displayName": analysis.get("display_name"),
                "scope": "SOURCE_LABEL_SHADOW_ONLY", "operationalUseAuthorized": False,
                "analysisModelId": self.analysis_model_id,
                "models": [{"id": key, "modelSha256": value["entry"]["model"]["sha256"],
                            "classOrder": value["config"]["class_order"], "input": value["entry"]["input_description"]}
                           for key, value in self.models.items()]}

    def predict(self, model_id, body):
        import numpy as np
        if model_id not in self.models:
            raise KeyError(model_id)
        if not self.gate.acquire(blocking=False):
            raise ModelBusyError("Inference is busy; retry later")
        try:
            started = time.perf_counter()
            model = self.models[model_id]
            values = preprocess(body, model["config"])
            outputs = model["session"].run(None, {model["input_name"]: values})
            output = outputs[0]
            classes = model["config"]["class_order"]
            if output.shape != (1, len(classes)) or not np.isfinite(output).all():
                raise RuntimeError("Invalid model output")
            scores = output[0]
            result = {"modelId": model_id, "modelReleaseId": self.release_id, "registrySha256": self.registry_sha256,
                    "modelSha256": model["entry"]["model"]["sha256"], "sourcePrediction": classes[int(scores.argmax())],
                    "sourceClassDecisionScores": dict(zip(classes, scores.tolist())), "isSimulated": False,
                    "operationalOutcome": "REVIEW_RECAPTURE", "operationalUseAuthorized": False, "reviewRequired": True,
                    "authority": "SHADOW_ONLY", "inferenceMs": round((time.perf_counter()-started)*1000, 3),
                    "limitations": "Uncalibrated source-label scores. No verified age, viability, food safety, or out-of-distribution acceptance."}
            if model["policy"] is not None:
                from .selective_gate import decide
                if outputs[1].shape != (1, model["references"].shape[1]):
                    raise RuntimeError("Invalid embedding output")
                result.update(decide(scores, outputs[1][0], decode_jpeg(body), model["policy"], model["references"], model["reference_labels"]))
                result.update(operationalOutcome="NOT_AUTHORIZED", recapturePolicySha256=model["entry"]["gate_policy"]["sha256"],
                              limitations="Image appearance only. Recapture gates do not guarantee correct labels. Physical sorting and food-safety decisions are not authorized.")
            result["inferenceMs"] = round((time.perf_counter()-started)*1000, 3)
            return result
        finally:
            self.gate.release()

    def close(self):
        self.models.clear()
        self.analysis_model_id = None

    def predict_views(self, model_id, bodies):
        if len(bodies) != 3:
            raise ValueError("Automatic analysis requires three views")
        if self.models[model_id]["policy"] is None:
            raise ValueError("Multi-view analysis requires selective quality gates")
        return combine_views([self.predict(model_id, body) for body in bodies],
                             [hashlib.sha256(body).hexdigest() for body in bodies])
