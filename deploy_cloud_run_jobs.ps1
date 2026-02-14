param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Repository = "polybot",
    [string]$ImageName = "polybot",
    [Parameter(Mandatory = $true)]
    [string]$BucketName,
    [string]$RunServiceAccount = "",
    [string]$CryptoPanicApiKey = ""
)

$ErrorActionPreference = "Stop"

function Resolve-GcloudCommand {
    $direct = Get-Command gcloud -ErrorAction SilentlyContinue
    if ($direct) {
        return $direct.Source
    }

    $candidates = @(
        "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "${env:ProgramFiles(x86)}\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "$env:LocalAppData\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    )

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    throw "Google Cloud CLI (gcloud) not found. Install it first: winget install Google.CloudSDK, then reopen PowerShell."
}

if ([string]::IsNullOrWhiteSpace($ProjectId) -or $ProjectId -eq "YOUR_PROJECT_ID") {
    throw "ProjectId is not set. Replace placeholder with your real GCP project id."
}

if ([string]::IsNullOrWhiteSpace($BucketName) -or $BucketName -eq "YOUR_BUCKET_NAME") {
    throw "BucketName is not set. Replace placeholder with your real GCS bucket name."
}

if ([string]::IsNullOrWhiteSpace($RunServiceAccount)) {
    $RunServiceAccount = "polybot-runner@$ProjectId.iam.gserviceaccount.com"
}

$gcloud = Resolve-GcloudCommand

$imageUri = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName:latest"
$runnerSaName = $RunServiceAccount.Split("@")[0]

Write-Host "Project: $ProjectId"
Write-Host "Region:  $Region"
Write-Host "Bucket:  $BucketName"
Write-Host "Image:   $imageUri"

Write-Host "`n[1/7] Setting gcloud project..."
& $gcloud config set project $ProjectId | Out-Null

Write-Host "[2/7] Enabling required APIs..."
& $gcloud services enable `
    run.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com `
    storage.googleapis.com `
    iam.googleapis.com `
    cloudscheduler.googleapis.com | Out-Null

Write-Host "[3/7] Ensuring Artifact Registry repository exists..."
$repoExists = $true
try {
    & $gcloud artifacts repositories describe $Repository --location $Region | Out-Null
} catch {
    $repoExists = $false
}
if (-not $repoExists) {
    & $gcloud artifacts repositories create $Repository `
        --repository-format docker `
        --location $Region `
        --description "Polybot container images" | Out-Null
}

Write-Host "[4/7] Ensuring runner service account exists..."
$saExists = $true
try {
    & $gcloud iam service-accounts describe $RunServiceAccount | Out-Null
} catch {
    $saExists = $false
}
if (-not $saExists) {
    & $gcloud iam service-accounts create $runnerSaName `
        --display-name "Polybot Cloud Run Runner" | Out-Null
}

Write-Host "Granting storage permissions to runner service account..."
& $gcloud projects add-iam-policy-binding $ProjectId `
    --member "serviceAccount:$RunServiceAccount" `
    --role "roles/storage.objectAdmin" | Out-Null

Write-Host "[5/7] Building container with Cloud Build..."
& $gcloud builds submit --tag $imageUri .

$commonEnv = "GCS_BUCKET=$BucketName,GCS_PREFIX=polybot"
if (-not [string]::IsNullOrWhiteSpace($CryptoPanicApiKey)) {
    $commonEnv = "$commonEnv,CRYPTOPANIC_API_KEY=$CryptoPanicApiKey"
}

Write-Host "[6/7] Recreating Cloud Run jobs..."
$jobNames = @("polybot-arb-scan", "polybot-window-stack", "polybot-phase3")
foreach ($jobName in $jobNames) {
    & $gcloud run jobs delete $jobName --region $Region --quiet 2>$null
}

& $gcloud run jobs create polybot-arb-scan `
    --image $imageUri `
    --region $Region `
    --service-account $RunServiceAccount `
    --set-env-vars $commonEnv `
    --cpu 1 `
    --memory 1Gi `
    --max-retries 1 `
    --task-timeout 900 `
    --command python `
    --args "cloud_runner.py,arb-scan-once,--min-gross-edge,0.005,--min-liquidity,1000,--output,data/arb_events.jsonl" | Out-Null

& $gcloud run jobs create polybot-window-stack `
    --image $imageUri `
    --region $Region `
    --service-account $RunServiceAccount `
    --set-env-vars $commonEnv `
    --cpu 2 `
    --memory 2Gi `
    --max-retries 1 `
    --task-timeout 1800 `
    --command python `
    --args "cloud_runner.py,window-stack,--max-markets,4000,--max-candidates,250,--min-liquidity,1000,--fallback-mode,auto,--fallback-min-rows,120" | Out-Null

& $gcloud run jobs create polybot-phase3 `
    --image $imageUri `
    --region $Region `
    --service-account $RunServiceAccount `
    --set-env-vars $commonEnv `
    --cpu 4 `
    --memory 8Gi `
    --max-retries 1 `
    --task-timeout 3600 `
    --command python `
    --args "cloud_runner.py,phase3" | Out-Null

Write-Host "[7/7] Done."
Write-Host "`nRun jobs manually:"
Write-Host "  gcloud run jobs execute polybot-arb-scan --region $Region --wait"
Write-Host "  gcloud run jobs execute polybot-window-stack --region $Region --wait"
Write-Host "  gcloud run jobs execute polybot-phase3 --region $Region --wait"

Write-Host "`nOptional scheduling examples:"
Write-Host "  - Arb scanner every 2 minutes"
Write-Host "  - Window stack every 15 minutes"
Write-Host "See CLOUD_DEPLOYMENT.md for Scheduler commands."
