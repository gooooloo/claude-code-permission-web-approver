# Installer for Claude Code WebUI hooks (Windows PowerShell)
#
# Installs 3 Python hook scripts (PermissionRequest, SessionStart, SessionEnd).
# No external dependencies — uses native PowerShell JSON manipulation.
#
# Scopes:
#   -Scope Project  Install hooks into <cwd>\.claude\settings.json (project-level only)
#   -Scope Global   Install hooks into ~\.claude\settings.json + copy hook files to ~\.claude\hooks\
#   -Scope All      Do both Project and Global
#
# Usage: .\install.ps1 [-Scope Project|Global|All]

param(
    [ValidateSet("Project", "Global", "All")]
    [string]$Scope
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Get-Location
$HooksDir = Join-Path $HOME ".claude\hooks"

function Show-Usage {
    Write-Host "Usage: .\install.ps1 [-Scope Project|Global|All]"
    Write-Host ""
    Write-Host "  Project  Install hooks into <cwd>\.claude\settings.json"
    Write-Host "  Global   Install hooks into ~\.claude\settings.json + copy hook files"
    Write-Host "  All      Install both Project and Global"
    exit 1
}

function Prompt-Scope {
    Write-Host "Select install scope:"
    Write-Host "  1) Project  - Install hooks into <cwd>\.claude\settings.json"
    Write-Host "  2) Global   - Install hooks into ~\.claude\settings.json + copy hook files"
    Write-Host "  3) All      - Install both Project and Global"
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

# Hook configuration using %USERPROFILE% so settings.json is portable
$HooksConfig = @{
    PermissionRequest = @(
        @{
            matcher = ".*"
            hooks = @(
                @{
                    type = "command"
                    command = 'python "%USERPROFILE%\.claude\hooks\permission-request.py"'
                    timeout = 86400
                }
            )
        }
    )
    SessionStart = @(
        @{
            matcher = ".*"
            hooks = @(
                @{
                    type = "command"
                    command = 'python "%USERPROFILE%\.claude\hooks\session-start.py"'
                    timeout = 5
                }
            )
        }
    )
    SessionEnd = @(
        @{
            matcher = ".*"
            hooks = @(
                @{
                    type = "command"
                    command = 'python "%USERPROFILE%\.claude\hooks\session-end.py"'
                    timeout = 5
                }
            )
        }
    )
}

function Install-HookFiles {
    if (-not (Test-Path $HooksDir)) {
        New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null
    }

    # Remove old .sh files if they exist
    $oldScripts = @(
        "permission-request.sh", "post-tool-use.sh", "stop.sh",
        "user-prompt-submit.sh", "session-start.sh", "session-end.sh"
    )
    foreach ($old in $oldScripts) {
        $oldPath = Join-Path $HooksDir $old
        if (Test-Path $oldPath) {
            Remove-Item $oldPath -Force
        }
    }

    # Copy hook scripts (copy instead of symlink — Windows symlinks require admin/developer mode)
    $scripts = @("permission-request.py", "session-start.py", "session-end.py", "platform_utils.py")
    foreach ($script in $scripts) {
        $src = Join-Path $ScriptDir $script
        $dst = Join-Path $HooksDir $script
        if (Test-Path $src) {
            Copy-Item $src $dst -Force
        } else {
            Write-Warning "Source file not found: $src"
        }
    }
    Write-Host "Copied hook files to: $HooksDir"
}

function Install-Settings {
    param([string]$SettingsFile)

    $settingsDir = Split-Path -Parent $SettingsFile

    if (-not (Test-Path $settingsDir)) {
        New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null
    }

    if (Test-Path $SettingsFile) {
        $existing = Get-Content $SettingsFile -Raw | ConvertFrom-Json
        # Remove existing hooks property if present, then add new one
        if ($existing.PSObject.Properties["hooks"]) {
            $existing.PSObject.Properties.Remove("hooks")
        }
        $existing | Add-Member -NotePropertyName "hooks" -NotePropertyValue $HooksConfig
        $existing | ConvertTo-Json -Depth 10 | Set-Content $SettingsFile -Encoding UTF8
        Write-Host "Updated: $SettingsFile"
    } else {
        @{ hooks = $HooksConfig } | ConvertTo-Json -Depth 10 | Set-Content $SettingsFile -Encoding UTF8
        Write-Host "Created: $SettingsFile"
    }
}

if ($DoGlobal) {
    Install-HookFiles
    Install-Settings (Join-Path $HOME ".claude\settings.json")
    Write-Host "WebUI hooks installed globally (all projects)"
}

if ($DoProject) {
    Install-Settings (Join-Path $ProjectDir ".claude\settings.json")
    Write-Host "WebUI hooks installed for: $ProjectDir"
}

Write-Host "Start the server: python $ScriptDir\server.py"
Write-Host "Then open: http://localhost:19836"
