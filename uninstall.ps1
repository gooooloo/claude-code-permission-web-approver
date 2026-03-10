# Uninstaller for Claude Code WebUI hooks (Windows PowerShell)
#
# Reverses what install.ps1 does: removes hook configuration from settings.json
# and (for global scope) removes hook files from ~\.claude\hooks\.
# Also cleans up old .sh files from the previous architecture.
#
# Scopes:
#   -Scope Project  Remove hooks from <cwd>\.claude\settings.json
#   -Scope Global   Remove hooks from ~\.claude\settings.json + remove hook files
#   -Scope All      Do both Project and Global
#
# Usage: .\uninstall.ps1 [-Scope Project|Global|All]

param(
    [ValidateSet("Project", "Global", "All")]
    [string]$Scope
)

$ErrorActionPreference = "Stop"

$ProjectDir = Get-Location
$HooksDir = Join-Path $HOME ".claude\hooks"

function Show-Usage {
    Write-Host "Usage: .\uninstall.ps1 [-Scope Project|Global|All]"
    Write-Host ""
    Write-Host "  Project  Remove hooks from <cwd>\.claude\settings.json"
    Write-Host "  Global   Remove hooks from ~\.claude\settings.json + hook files"
    Write-Host "  All      Remove both Project and Global"
    exit 1
}

function Prompt-Scope {
    Write-Host "Select uninstall scope:"
    Write-Host "  1) Project  - Remove hooks from <cwd>\.claude\settings.json"
    Write-Host "  2) Global   - Remove hooks from ~\.claude\settings.json + hook files"
    Write-Host "  3) All      - Remove both Project and Global"
    Write-Host ""
    $choice = Read-Host "Enter choice [1-3]"
    switch ($choice) {
        "1" { return "Project" }
        "2" { return "Global" }
        "3" { return "All" }
        default { Write-Host "Invalid choice"; exit 1 }
    }
}

if (-not $Scope) {
    $Scope = Prompt-Scope
}

$DoProject = $Scope -eq "Project" -or $Scope -eq "All"
$DoGlobal = $Scope -eq "Global" -or $Scope -eq "All"

function Remove-HookFiles {
    $removed = 0

    # Remove .py hook files
    $pyScripts = @("hook-permission-request.py", "hook-session-start.py", "hook-session-end.py", "platform_utils.py")
    foreach ($script in $pyScripts) {
        $path = Join-Path $HooksDir $script
        if (Test-Path $path) {
            Remove-Item $path -Force
            $removed++
        }
    }

    # Also clean up old files from previous architectures
    $oldScripts = @(
        "permission-request.py", "session-start.py", "session-end.py",
        "permission-request.sh", "post-tool-use.sh", "stop.sh",
        "user-prompt-submit.sh", "session-start.sh", "session-end.sh"
    )
    foreach ($script in $oldScripts) {
        $path = Join-Path $HooksDir $script
        if (Test-Path $path) {
            Remove-Item $path -Force
            $removed++
        }
    }

    Write-Host "Removed $removed hook files from: $HooksDir"

    # Remove hooks directory if empty
    if ((Test-Path $HooksDir) -and ((Get-ChildItem $HooksDir -Force | Measure-Object).Count -eq 0)) {
        Remove-Item $HooksDir -Force
        Write-Host "Removed empty directory: $HooksDir"
    }
}

function Remove-HooksFromSettings {
    param([string]$SettingsFile)

    if (-not (Test-Path $SettingsFile)) {
        Write-Host "No settings file found: $SettingsFile (skipping)"
        return
    }

    $settings = Get-Content $SettingsFile -Raw | ConvertFrom-Json

    if (-not $settings.PSObject.Properties["hooks"]) {
        Write-Host "No hooks found in: $SettingsFile (skipping)"
        return
    }

    $settings.PSObject.Properties.Remove("hooks")

    # Check if settings is now empty (no remaining properties)
    $remainingProps = @($settings.PSObject.Properties)
    if ($remainingProps.Count -eq 0) {
        Remove-Item $SettingsFile -Force
        Write-Host "Removed empty: $SettingsFile"

        # Remove .claude\ directory if empty
        $settingsDir = Split-Path -Parent $SettingsFile
        if ((Test-Path $settingsDir) -and ((Get-ChildItem $settingsDir -Force | Measure-Object).Count -eq 0)) {
            Remove-Item $settingsDir -Force
            Write-Host "Removed empty directory: $settingsDir"
        }
    } else {
        $settings | ConvertTo-Json -Depth 10 | Set-Content $SettingsFile -Encoding UTF8
        Write-Host "Removed hooks from: $SettingsFile"
    }
}

if ($DoGlobal) {
    Remove-HookFiles
    Remove-HooksFromSettings (Join-Path $HOME ".claude\settings.json")
    Write-Host "WebUI hooks uninstalled globally"
}

if ($DoProject) {
    Remove-HooksFromSettings (Join-Path $ProjectDir ".claude\settings.json")
    Write-Host "WebUI hooks uninstalled for: $ProjectDir"
}
