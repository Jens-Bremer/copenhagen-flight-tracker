#Requires -Version 5.1
#
# Wrapper for run_scheduler.py used by the Task Scheduler entry registered by
# scripts/scheduler_autostart.ps1. Captures both stdout and stderr to a dated
# log file under logs/ so a silent-failing detached task is still diagnosable.
#
# Direct console usage is also fine; the wrapper just appends to logs/scheduler.out.log.

$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $RepoRoot 'logs'
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir 'scheduler.out.log'

$PythonPath = Join-Path $RepoRoot '.venv' 'Scripts' 'python.exe'
if (-not (Test-Path $PythonPath)) {
    $PythonPath = 'python'
}
$ScriptPath = Join-Path $RepoRoot 'scripts' 'run_scheduler.py'

$timestamp = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
"[$timestamp] launching $PythonPath $ScriptPath" | Out-File -FilePath $LogFile -Append -Encoding utf8

# Merge stderr into stdout, then redirect everything to the log file.
& $PythonPath $ScriptPath *>> $LogFile
