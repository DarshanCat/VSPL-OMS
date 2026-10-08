# VSPL OMS -- One-Click Google Cloud Run Production Deployment Script
# Usage: .\deploy.ps1 [-Tag <optional-tag>] [-SkipBuild]

param(
    [string]$Tag = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$PROJECT_ID = "vspl-oms-510015"
$REGION = "asia-south1"
$SERVICE_NAME = "vspl-oms"
$AR_REPO = "vspl-oms"
$SERVICE_ACCOUNT = "vspl-oms-runner@$PROJECT_ID.iam.gserviceaccount.com"
$CLOUDSQL_INSTANCE = "$PROJECT_ID:$REGION:vspl-oms-db"
$PRODUCTION_DOMAIN = "https://oms.vijayspheroidals.in"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " VSPL OMS -- GOOGLE CLOUD RUN PRODUCTION DEPLOYMENT" -ForegroundColor Cyan
Write-Host " Project : $PROJECT_ID ($REGION)" -ForegroundColor Cyan
Write-Host " Service : $SERVICE_NAME" -ForegroundColor Cyan
Write-Host " Domain  : $PRODUCTION_DOMAIN" -ForegroundColor Cyan
Write-Host "=================================================================`n" -ForegroundColor Cyan

# 1. Generate Image Tag
if (-not $Tag) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $Tag = "prod-$timestamp"
}
$IMAGE_URI = "$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPO/${SERVICE_NAME}:$Tag"

# 2. Local Frontend Build Verification
if (-not $SkipBuild) {
    Write-Host "[1/4] Verifying frontend build locally..." -ForegroundColor Yellow
    Push-Location "frontend"
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed! Aborting deployment."
        }
    } finally {
        Pop-Location
    }
    Write-Host "  [OK] Frontend build passed.`n" -ForegroundColor Green
} else {
    Write-Host "[1/4] Skipping local frontend build (--SkipBuild specified).`n" -ForegroundColor Gray
}

# 3. Cloud Build Container Image
Write-Host "[2/4] Building and pushing container image via Google Cloud Build..." -ForegroundColor Yellow
Write-Host "  Tag: $IMAGE_URI" -ForegroundColor Gray
gcloud builds submit --tag $IMAGE_URI --project=$PROJECT_ID
if ($LASTEXITCODE -ne 0) {
    throw "Cloud Build failed! Aborting deployment."
}
Write-Host "  [OK] Container image built and pushed to Artifact Registry.`n" -ForegroundColor Green

# 4. Deploy Revision to Cloud Run
Write-Host "[3/4] Deploying new revision to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $SERVICE_NAME `
    --image $IMAGE_URI `
    --region $REGION `
    --platform managed `
    --project $PROJECT_ID `
    --service-account $SERVICE_ACCOUNT `
    --add-cloudsql-instances $CLOUDSQL_INSTANCE `
    --set-env-vars "CORS_ORIGINS=*,BOOTSTRAP_ADMIN_EMAIL=aravind.gurudev@vijayspheroidals.com,BOOTSTRAP_ADMIN_NAME=Aravind Gurudev" `
    --set-secrets "DATABASE_URL=VSPL_DATABASE_URL:latest,SECRET_KEY=VSPL_SECRET_KEY:latest,BOOTSTRAP_ADMIN_PASSWORD=VSPL_ADMIN_PASSWORD:latest" `
    --port 8080 `
    --cpu 1 `
    --memory 1Gi `
    --min-instances 0 `
    --max-instances 3 `
    --allow-unauthenticated

if ($LASTEXITCODE -ne 0) {
    throw "Cloud Run deployment failed!"
}
Write-Host "  [OK] Cloud Run deployment completed.`n" -ForegroundColor Green

# 5. Post-Deployment Verification
Write-Host "[4/4] Verifying production health endpoints..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

try {
    $health = Invoke-RestMethod -Uri "$PRODUCTION_DOMAIN/health" -Method Get -TimeoutSec 15
    Write-Host "  [OK] Custom Domain Health: $PRODUCTION_DOMAIN/health -> status: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] Could not reach $PRODUCTION_DOMAIN/health yet (DNS/cert might be warming up). Trying canonical Cloud Run URL..." -ForegroundColor Yellow
    $canonUrl = (gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format="value(status.url)")
    $healthCanon = Invoke-RestMethod -Uri "$canonUrl/health" -Method Get -TimeoutSec 15
    Write-Host "  [OK] Canonical Cloud Run Health: $canonUrl/health -> status: $($healthCanon.status)" -ForegroundColor Green
}

Write-Host "`n=================================================================" -ForegroundColor Cyan
Write-Host " DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
Write-Host " Live Production App: $PRODUCTION_DOMAIN" -ForegroundColor Green
Write-Host "=================================================================" -ForegroundColor Cyan
