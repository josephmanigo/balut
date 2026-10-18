# Experimental camera model in the app

The user explicitly requested the newly retrained model in the app for live camera testing. The active cloud release is selected by `deployment/active-release.txt`, which now names `camera-trial-20261018`. The Vercel app, Render entrypoint, model assembler, and source packagers use the same selection. Existing desktop profiles continue to select their explicitly configured release.

This is the three-class adaptation in `ml/runs/retained-camera-20261018`, trained from the retained dataset plus ten camera training eggs. The 30 camera rows retain their original train/validation/completed-test roles. It is distinct from the earlier binary pilot. Camera validation was 8/10 raw correct, with seven correct accepted results and three recapture requests. Historical raw validation decreased from 361/368 to 358/368. Activation is for operator-requested experimentation; it does not establish 99% accuracy.

The release uses the unchanged retained ONNX encoder with the learned three-class linear weights inserted into its existing classifier. It keeps the saved adaptation's uncertainty policy and references. Operational authorization remains false. No camera test images were opened for release preparation, and no model or threshold was retrained for this activation.

Release verification compared all 20 camera development frames against the saved head and retained encoder. Embeddings matched, the maximum score difference was `0.00000667572021484375`, and all ten validation decisions matched. Startup fixtures cover Day 16, Day 18, Reject, and an uncertain dark image. A clean reconstruction from the deployment chunks matched the sealed model hash. The original retained release still passes its known-answer checks.

- Release: `camera-trial-20261018`
- Registry SHA-256: `909b08a19e0af651eb7076264b109e709c6919221bc9298a24f00a6379af090e`
- Model SHA-256: `8189d47fc25d357c5efb2e4abf4d714fe644c5356ec8c775e4addc679c635253`
- Release verification: `deployment/releases/camera-trial-20261018/verification.json`
- Cloud verification records: `output/camera-trial-20261018/cloud-status.jsonl`

The live page identifies the active model as “Camera model · experimental.” A saved result from an earlier release is labeled as an earlier model result until a fresh placement produces a result. History displays the release ID. Refresh the app, leave the holder empty until Ready, then place one egg and keep hands clear. The app still analyzes a single fresh frame automatically.

The original retained release and training run are preserved locally. Reverting the activation commit restores the prior active selection and deployment model chunks. Restoring only the selection without restoring matching chunks is insufficient for a clean cloud build. The autonomous holder still rotates; no firmware or motor control changes were made.
