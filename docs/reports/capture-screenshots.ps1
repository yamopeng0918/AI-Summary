$ErrorActionPreference = 'Stop'
$reportRoot = $PSScriptRoot
$browserPath = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
$tasks = @(@{ Name='cover'; Width=1200; Height=980; Url='http://127.0.0.1:8765/AI-Summary/' }, @{ Name='overview'; Width=1440; Height=1080; Url='http://127.0.0.1:8765/AI-Summary/#summary-filters' })
$records = Get-ChildItem "$reportRoot/../../data/summaries/*.json" | ForEach-Object { Get-Content -Raw -Encoding utf8 $_.FullName | ConvertFrom-Json }
foreach ($entry in @(@{Name='web'; Suffix='8ed66e81'}, @{Name='youtube'; Suffix='9f06f9b7'}, @{Name='social'; Suffix='5f8aee85'})) {
    $record = $records | Where-Object { $_.id.EndsWith($entry.Suffix) }
    if (@($record).Count -ne 1 -or $record.status -ne 'published') { throw 'Expected one published record' }
    $tasks += @{ Name=$entry.Name; Width=760; Height=1150; Url=('http://127.0.0.1:8765/AI-Summary/summaries/' + [Uri]::EscapeDataString($record.id) + '/') }
}
foreach ($task in $tasks) {
    $target = "$reportRoot/.build/assets/$($task.Name).png"
    $arguments = @('--headless', '--disable-gpu', '--no-first-run', '--hide-scrollbars', "--user-data-dir=$reportRoot/.build/profile-$($task.Name)", "--screenshot=$target", "--window-size=$($task.Width),$($task.Height)", '--virtual-time-budget=5000', $task.Url)
    Start-Process -FilePath $browserPath -ArgumentList $arguments -WindowStyle Hidden -Wait
    if (-not (Test-Path -LiteralPath $target)) { throw "Missing screenshot $target" }
    Write-Output "Captured $($task.Name)"
}
