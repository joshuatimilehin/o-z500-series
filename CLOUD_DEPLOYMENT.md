# Cloud Deployment (GCP)

This project can run fully in cloud so your local PC can stay offline.

## What this setup deploys

- `polybot-arb-scan` (Cloud Run Job): single arb scan and append to `data/arb_events.jsonl`
- `polybot-window-stack` (Cloud Run Job): builds BTC-window truth + fair value + execution signals
- `polybot-phase3` (Cloud Run Job): full Phase 3 training/backtest pipeline

All outputs are synced to Google Cloud Storage (GCS).

## 1) Prerequisites

- Install Google Cloud SDK (`gcloud`)
- Authenticate: `gcloud auth login`
- Have a GCP project + billing enabled
- Create a GCS bucket (or reuse existing)

## 2) Deploy jobs

Run from repo root:

```powershell
.\deploy_cloud_run_jobs.ps1 -ProjectId "YOUR_PROJECT_ID" -BucketName "YOUR_BUCKET_NAME" -Region "us-central1"
```

Optional:

```powershell
.\deploy_cloud_run_jobs.ps1 `
  -ProjectId "YOUR_PROJECT_ID" `
  -BucketName "YOUR_BUCKET_NAME" `
  -Region "us-central1" `
  -CryptoPanicApiKey "YOUR_KEY"
```

## 3) Execute jobs manually

```powershell
gcloud run jobs execute polybot-arb-scan --region us-central1 --wait
gcloud run jobs execute polybot-window-stack --region us-central1 --wait
gcloud run jobs execute polybot-phase3 --region us-central1 --wait
```

## 4) Optional: schedule jobs (Cloud Scheduler)

Create a scheduler service account:

```powershell
gcloud iam service-accounts create polybot-scheduler --display-name "Polybot Scheduler"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member "serviceAccount:polybot-scheduler@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role "roles/run.developer"
```

Arb scan every 2 minutes:

```powershell
gcloud scheduler jobs create http polybot-arb-every-2min `
  --location us-central1 `
  --schedule "*/2 * * * *" `
  --uri "https://run.googleapis.com/v2/projects/YOUR_PROJECT_ID/locations/us-central1/jobs/polybot-arb-scan:run" `
  --http-method POST `
  --oauth-service-account-email "polybot-scheduler@YOUR_PROJECT_ID.iam.gserviceaccount.com" `
  --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"
```

Window stack every 15 minutes:

```powershell
gcloud scheduler jobs create http polybot-window-every-15min `
  --location us-central1 `
  --schedule "*/15 * * * *" `
  --uri "https://run.googleapis.com/v2/projects/YOUR_PROJECT_ID/locations/us-central1/jobs/polybot-window-stack:run" `
  --http-method POST `
  --oauth-service-account-email "polybot-scheduler@YOUR_PROJECT_ID.iam.gserviceaccount.com" `
  --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"
```

## 5) Data persistence and logs

- Local container paths are ephemeral.
- Persistent files are uploaded to `gs://<bucket>/polybot/...` by `cloud_runner.py`.
- Each run writes `results/cloud_runner_last_manifest.json`.
- View logs in Cloud Run Jobs console.

## 6) Useful local test

Before deploying:

```powershell
python cloud_runner.py arb-scan-once --gcs-bucket "" --output data/arb_events.jsonl
```

This runs without GCS sync.
