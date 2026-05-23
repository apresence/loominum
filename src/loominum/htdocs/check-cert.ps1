# Check if Loominum certificate is installed
Write-Host "Checking for Loominum certificate..." -ForegroundColor Cyan
Write-Host ""

# Check LocalMachine\Root store
$certs = Get-ChildItem -Path Cert:\LocalMachine\Root | Where-Object { 
    $_.Subject -like "*tau*" -or $_.Issuer -like "*tau*" 
}

if ($certs) {
    Write-Host "✓ Found certificate(s):" -ForegroundColor Green
    foreach ($cert in $certs) {
        Write-Host ""
        Write-Host "  Subject: $($cert.Subject)" -ForegroundColor White
        Write-Host "  Issuer:  $($cert.Issuer)" -ForegroundColor White
        Write-Host "  Valid:   $($cert.NotBefore) to $($cert.NotAfter)" -ForegroundColor White
        Write-Host "  Thumbprint: $($cert.Thumbprint)" -ForegroundColor Gray
        
        # Show DNS names
        $sans = $cert.Extensions | Where-Object { $_.Oid.FriendlyName -eq "Subject Alternative Name" }
        if ($sans) {
            Write-Host "  SANs:    $($sans.Format($false))" -ForegroundColor White
        }
    }
    Write-Host ""
    Write-Host "Recommendation: Restart Edge completely (kill all Edge processes)" -ForegroundColor Yellow
} else {
    Write-Host "✗ No certificate found in Trusted Root store" -ForegroundColor Red
    Write-Host ""
    Write-Host "Reinstall with:" -ForegroundColor Yellow
    Write-Host "  curl.exe -k https://tau:7993/install-cert.ps1 | powershell -ExecutionPolicy Bypass -Command -" -ForegroundColor White
}

Write-Host ""
Write-Host "Checking Edge processes..." -ForegroundColor Cyan
$edgeProcesses = Get-Process -Name msedge -ErrorAction SilentlyContinue
if ($edgeProcesses) {
    Write-Host "⚠  Edge is running ($($edgeProcesses.Count) processes)" -ForegroundColor Yellow
    Write-Host "   Close all Edge windows and kill processes:" -ForegroundColor Yellow
    Write-Host "   taskkill /F /IM msedge.exe" -ForegroundColor White
} else {
    Write-Host "✓ Edge is not running" -ForegroundColor Green
}
