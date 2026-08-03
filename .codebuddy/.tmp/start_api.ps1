Set-Location 'D:\project\memorydemo\api'
$uvicorn = 'C:\Users\L0836\.conda\envs\memory\Scripts\uvicorn.exe'
if (-not (Test-Path $uvicorn)) {
    Write-Host "uvicorn.exe not found at $uvicorn" -ForegroundColor Red
    Read-Host
    exit 1
}
Write-Host "Starting uvicorn from $uvicorn ..." -ForegroundColor Green
& $uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1
Write-Host ''
Write-Host '--- uvicorn exited ---' -ForegroundColor Yellow
Read-Host
