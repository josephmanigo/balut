# Automatic classification and recapture software samples

Open http://127.0.0.1:8765 in Chrome or Edge on the prepared laptop. On Analyze egg, upload each JPEG and use the same Analyze egg button. No class or model selector is needed.

- `day_16.jpg`: Day 16.
- `day_18.jpg`: Day 18.
- `reject.jpg`: Reject — suspected.
- `too-dark.jpg`: Another image needed; unclassified.
- `unclear-egg.jpg`: Another image needed; unclassified.

After an unclear result, select a new JPEG. There is no human review queue in this workflow. The sample images are known-answer software fixtures: four are selected validation crops from the public sources, and the dark frame is synthetic. They do not demonstrate independent accuracy. Source hashes and adaptations are in `manifest.json`; dataset notices are in the release's licenses folder. The trained model's historical accepted accuracy was 95/97 at 97/172 coverage, with two wrong accepted predictions.
