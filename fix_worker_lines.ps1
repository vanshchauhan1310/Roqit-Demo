$p = 'backend/app/workers/trip_assignment_worker.py'
$lines = [System.Collections.Generic.List[string]]@(Get-Content $p)
$new = [System.Collections.Generic.List[string]]::new()
foreach ($line in $lines) {
    $isAlready = $line -match 'already assigned'
    $isBackfilled = $line -match 'resources backfilled'
    $hasPrint = $line -match 'print\(f'
    if (($hasPrint -and $isAlready) -or ($hasPrint -and $isBackfilled)) {
        $idx = $line.IndexOf('print(f')
        $head = $line.Substring(0, $idx) -replace '\s*[\\n]+$', ''
        $new.Add($head)
        $new.Add($line.Substring($idx))
    } else {
        $new.Add($line)
    }
}
Set-Content -Path $p -Value $new -Encoding UTF8
'DONE'