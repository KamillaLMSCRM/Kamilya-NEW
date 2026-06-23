# Kamilya LMS - Upload and Generate Course Script
$baseUrl = "https://kamilya-lms-api.onrender.com/api/v1"

# Read brand book
$brandBookContent = "Brand Book Acme Corp - Marketing agency full cycle. Digital, offline, strategy, creative, media buying. Mission: Help brands become what their customers want to see. Vision: Be the agency people come to for growth, not just advertising. Values: Honesty, Quality > Speed, Freedom with Responsibility, Creativity without Ego, Business Results. Tone of voice: Confident without arrogance, specific without fluff, humor when appropriate, jargon-free where possible, direct without rudness. Visual identity: Coral #FF5E5B, Charcoal #2C2C2C, Cream #F8F4E3. Fonts: Inter body, Montserrat headlines. Social media: Instagram, LinkedIn, Facebook, TikTok, Telegram. Content rubrics: Case of the day, Creative notes, What if..., Behind the scenes, Trends. Brand in communications: Presentations by template, Short email subjects, Meetings with agenda. Merch: T-shirts, Hoodies, Thermoses, Notebooks. Brand is a promise - we make marketing that works, not marketing for marketing sake."

Write-Host "=== Step 1: Create Tenant ===" -ForegroundColor Cyan

$tenantPayload = @{
    name = "Acme Corp"
    slug = "acme-corp"
    status = "active"
    plan = "starter"
    settings = @{}`.Trim() -replace "`r`n", "`n" # JSONB with server default

# Use Invoke-WebRequest with proper JSON body
try {
    $tenantResponse = Invoke-WebRequest -Uri "$baseUrl/tenants" -Method POST -ContentType "application/json" -Body @{ name = "Acme Corp"; slug = "acme-corp" }.ToJson() -UseBasicParsing
    $tenant = $tenantResponse.Content | ConvertFrom-Json
    Write-Host "Tenant created: $($tenant.name) ($($tenant.slug))" -ForegroundColor Green
    $tenantId = $tenant.id
} catch {
    Write-Host "Failed to create tenant: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "=== Step 2: Create Admin User ===" -ForegroundColor Cyan

try {
    $userResponse = Invoke-WebRequest -Uri "$baseUrl/auth/register" -Method POST -ContentType "application/json" -Body @{
        email = "admin@acme-corp.kz"
        password = "Admin12345"
        first_name = "Acme"
        last_name = "Admin"
        tenant_id = $tenantId
    }.ToJson() -UseBasicParsing
    $user = $userResponse.Content | ConvertFrom-Json
    $jwt = $user.access_token
    Write-Host "User created, JWT received ($($userResponse.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "Failed to create user: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "=== Step 3: Login to Refresh Token ===" -ForegroundColor Cyan

try {
    $loginResponse = Invoke-WebRequest -Uri "$baseUrl/auth/login" -Method POST -ContentType "application/json" -Body @{
        email = "admin@acme-corp.kz"
        password = "Admin12345"
    }.ToJson() -UseBasicParsing
    $login = $loginResponse.Content | ConvertFrom-Json
    $jwt = $login.access_token
    Write-Host "Login successful, new JWT received" -ForegroundColor Green
} catch {
    Write-Host "Failed to login: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Trying with first registration token..." -ForegroundColor Yellow
    # Use the JWT from step 2 if login fails (may already be valid)
}

# Test token works
try {
    $testResponse = Invoke-WebRequest -Uri "$baseUrl/documents" -Headers @{Authorization="Bearer $jwt"} -UseBasicParsing
    Write-Host "Auth verified: $($testResponse.StatusCode) OK" -ForegroundColor Green
} catch {
    Write-Host "Auth test failed: $($_.Exception.Response.StatusCode)" -ForegroundColor Red
}

Write-Host "=== Step 4: Upload Brand Book Document ===" -ForegroundColor Cyan

# Create multipart form data for upload
$tempFile = [System.IO.Path]::GetTempFileName() + ".txt"
[System.IO.File]::WriteAllText($tempFile, $brandBookContent, [System.Text.Encoding]::UTF8)

try {
    $uploadResponse = Invoke-RestMethod -Uri "$baseUrl/documents/upload" -Method POST -ContentType "multipart/form-data" -InFile $tempFile -UseBasicParsing
    Write-Host "Document uploaded: $($uploadResponse.title) ($($uploadResponse.id))" -ForegroundColor Green
    $docId = $uploadResponse.id
} catch {
    Write-Host "Failed to upload document: $($_.Exception.Message)" -ForegroundColor Red
}

if (Test-Path $tempFile) { Remove-Item $tempFile -ErrorAction SilentlyContinue }

Write-Host "=== Step 5: Create a Course Entity First ===" -ForegroundColor Cyan

# Create a course (needed for generation to attach to)
try {
    $courseResponse = Invoke-RestMethod -Uri "$baseUrl/courses" -Method POST -Headers @{Authorization="Bearer $jwt"} -ContentType "application/json" -Body @{
        name = "Acme Corp Brand Book Training"
        description = "Complete training on the Acme Corp Brand Book - understanding brand identity, values, tone of voice and visual guidelines. Based on official internal brand documentation."
        language = "ru"
        status = "draft"
    }.ToJson() -UseBasicParsing
    $course = $courseResponse
    $courseId = $course.id
    Write-Host "Course created: $($course.name) ($($courseId))" -ForegroundColor Green
} catch {
    Write-Host "Failed to create course: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "Will try generation without course_id..." -ForegroundColor Yellow
}

Write-Host "=== Step 6: Trigger AI Course Generation ===" -ForegroundColor Cyan

$aiPayload = @{
    documents = @("Uploaded Brand Book Document")
    target_audience = "New employees of Acme Corp marketing agency"
    num_modules = 3
    language = "ru"
    tone = "professional"
}

if ($courseId) {
    $aiPayload["course_id"] = $courseId
    Write-Host "Generation will be attached to course $courseId" -ForegroundColor Yellow
}

try {
    $aiResponse = Invoke-RestMethod -Uri "$baseUrl/ai/generate-course" -Method POST -ContentType "application/json" -Headers @{Authorization="Bearer $jwt"} -Body $aiPayload.ToJson() -UseBasicParsing
    $jobId = $aiResponse.id
    $status = $aiResponse.status
    $stage = $aiResponse.stage
    Write-Host "AI Job created: $jobId (status: $status, stage: $stage)" -ForegroundColor Green
} catch {
    Write-Host "Failed to trigger generation: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "=== Step 7: Poll Job Status ===" -ForegroundColor Cyan
Write-Host "Checking AI generation progress..." -ForegroundColor Yellow

for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 3
    try {
        $job = Invoke-RestMethod -Uri "$baseUrl/ai/jobs/$jobId" -Headers @{Authorization="Bearer $jwt"} -UseBasicParsing
        Write-Host "  [$i] Status: $($job.status) | Progress: $($job.progress)% | Stage: $($job.stage) | Message: $($job.message)" -NoNewline
        if ($job.status -in @("completed","failed","cancelled")) {
            Write-Host " [DONE]" -ForegroundColor $(if ($job.status -eq "completed") {"Green"} else {"Red"})
            break
        }
    } catch {
        Write-Host "  [$i] Check failed: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== Step 8: Final Job Status ===" -ForegroundColor Cyan
try {
    $finalJob = Invoke-RestMethod -Uri "$baseUrl/ai/jobs/$jobId" -Headers @{Authorization="Bearer $jwt"} -UseBasicParsing
    Write-Host "Final Status: $($finalJob.status)"
    Write-Host "Progress: $($finalJob.progress)%"
    Write-Host "Stage: $($finalJob.stage)"
    Write-Host "Message: $($finalJob.message)"
} catch {
    Write-Host "Final status check failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
