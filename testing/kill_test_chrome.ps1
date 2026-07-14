# SAFE cleanup: terminate ONLY the headless Chrome instances this test harness spawned, matched by
# their unique --user-data-dir under blue-origin-landings\testing. NEVER touches the user's real
# Chrome (different profile / no such flag). Use this instead of `taskkill /F /IM chrome.exe`.
$pattern = 'blue-origin-landings\\testing\\_'   # our test profiles all live here (\_prof*, \_chromeprofile*, \_dbgprof*)
$procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match $pattern) -and ($_.CommandLine -match '--headless') }
if (-not $procs) { Write-Output "no test-harness chrome found (nothing killed)"; exit 0 }
foreach ($p in $procs) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Output "killed test chrome PID $($p.ProcessId)" }
    catch { Write-Output "could not kill PID $($p.ProcessId): $_" }
}
