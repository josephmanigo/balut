# Test without the candler

**The interface has been updated:** use `data/automatic-test-samples` and the single **Analyze egg** button. The instructions below document the previous separate-model release and do not describe the current operator page.

Use these saved candling JPEGs as camera inputs. They exercise the real trained models, upload workflow, and saved prediction records. They are copies of existing validation fixtures used by startup verification, so matching them is a software check, not a new measurement of accuracy.

## Try the dashboard

1. Copy the local operator password in PowerShell:

   ```powershell
   & 'C:\Users\My Pc\Downloads\balut\scripts\Copy-Balut-Login.ps1'
   ```

2. Open Chrome or Edge on this Windows laptop and paste `http://127.0.0.1:8765` into its address bar. Codex's embedded browser may block this local address. Sign in as `operator`, paste the password, and clear the clipboard afterward.
3. Open **Model releases**. Choose the matching comparison model below, select its JPEG, and click **Analyze image**.
4. Confirm the source-label match, **Review / recapture**, and a saved prediction record ID. Record IDs will differ between new submissions.

| Sample file | Comparison model in the dashboard | Expected model output |
|---|---|---|
| `01-age16-18.jpg` | Day 16 / Day 18 comparison | `Fertile-Day-16` |
| `02-pat-status.jpg` | Fertilized / Reject / Unfertilized | `Fertilized` |
| `03-duck-status.jpg` | Duck candling status | `infertile` |

These expected outputs describe what the sealed model predicts, not independently confirmed egg age or condition. The source, validation partition, and SHA-256 of each image are preserved in `manifest.json`.

The sample folder is `C:\Users\My Pc\Downloads\balut\data\software-test-samples`. In the file-selection dialog, paste that folder path into the address bar.

If the page does not open, start the service in a PowerShell window and leave it running:

```powershell
& 'C:\Users\My Pc\Downloads\balut\scripts\Start-Balut.ps1' -Supervise
```

Do not start another instance while the service already occupies port 8765. After a service restart, refresh the page. The current result display is temporary UI state; saved records persist and can be retrieved by the API. The automated check below verifies this recovery directly.

## Check software behavior

- Analyze the same selected image a second time without changing the model or file. The saved prediction ID should remain the same: this is a retry of the same request. Selecting a file again or changing the model starts a new request.
- Before selecting an image, the Analyze button should be disabled. Changing the model or image should clear the prior result.
- A non-JPEG file renamed to `.jpg` should be rejected when analyzed. An empty or corrupted JPEG must not produce a successful saved prediction. These checks validate file handling, not optical quality.
- Disconnect the internet while keeping the laptop service running and repeat a sample. The local model workflow should work without internet.
- Use saved candling photos for further experiments. Ordinary exterior egg photos and generated images do not provide evidence of candling accuracy.

Manual uploads are saved in the operating database. The automated check below uses separate test storage.

## Run the automated software check

From the full development workspace on this laptop:

```powershell
Set-Location 'C:\Users\My Pc\Downloads\balut'
& '.\.venv-serving\Scripts\python.exe' 'scripts\verify_live_serving.py'
```

This starts an isolated test service on port 8766 and uses its own database. It exercises all three real models, authentication, retries, concurrent requests, process restarts, backup, and restoration. It stops its test process afterward. Successful completion prints `"passed": true`; inspect `artifacts/production-live-verification.json` for the full result. A failed assertion or traceback is a failed check and needs investigation. Leave port 8766 free before starting it.

The automated verification script is in the development workspace; the Windows distribution ZIP contains the runtime and prior verification evidence, rather than this development test runner.

## What this establishes

You can verify that the installed models run, the dashboard submits images, results are recorded, invalid files fail, and stored data survives tested recovery scenarios. Testing these known fixtures does not establish accuracy on new eggs, camera/lighting consistency, incubation-age truth, physical motion, or real candler reliability. For a new accuracy evaluation, use labelled candling images from eggs and capture sessions that were excluded from training and model selection.
