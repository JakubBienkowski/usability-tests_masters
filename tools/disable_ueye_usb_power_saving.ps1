$ErrorActionPreference = "Continue"

$LogPath = Join-Path $PSScriptRoot "disable_ueye_usb_power_saving.log"
$DeviceInstanceId = "USB\VID_1409&PID_C007\5&1e9a0576&0&6"
$DeviceRegPath = "HKLM:\SYSTEM\CurrentControlSet\Enum\$DeviceInstanceId\Device Parameters"
$UsbSettingsGuid = "2a737441-1930-4402-8d77-b2bebba308a3"
$UsbSelectiveSuspendGuid = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp $Message" | Tee-Object -FilePath $LogPath -Append
}

if (Test-Path $LogPath) {
    Remove-Item $LogPath -Force
}

Write-Log "Starting uEye USB power saving disable"
Write-Log "Device instance: $DeviceInstanceId"
Write-Log "Device registry path: $DeviceRegPath"

Write-Log "Power scheme before changes:"
powercfg /getactivescheme | Tee-Object -FilePath $LogPath -Append

Write-Log "Disabling USB selective suspend for AC power"
powercfg /SETACVALUEINDEX SCHEME_CURRENT $UsbSettingsGuid $UsbSelectiveSuspendGuid 0 | Tee-Object -FilePath $LogPath -Append
Write-Log "AC selective suspend exit code: $LASTEXITCODE"

Write-Log "Disabling USB selective suspend for DC/battery power"
powercfg /SETDCVALUEINDEX SCHEME_CURRENT $UsbSettingsGuid $UsbSelectiveSuspendGuid 0 | Tee-Object -FilePath $LogPath -Append
Write-Log "DC selective suspend exit code: $LASTEXITCODE"

Write-Log "Applying active power scheme"
powercfg /SETACTIVE SCHEME_CURRENT | Tee-Object -FilePath $LogPath -Append
Write-Log "Set active exit code: $LASTEXITCODE"

Write-Log "Device registry values before changes:"
if (Test-Path $DeviceRegPath) {
    Get-ItemProperty -Path $DeviceRegPath | Format-List | Out-String | Tee-Object -FilePath $LogPath -Append
} else {
    Write-Log "Device registry path does not exist"
}

if (Test-Path $DeviceRegPath) {
    $values = @{
        "EnhancedPowerManagementEnabled" = 0
        "SelectiveSuspendEnabled" = 0
        "AllowIdleIrpInD3" = 0
        "DeviceSelectiveSuspended" = 0
    }

    foreach ($entry in $values.GetEnumerator()) {
        Write-Log "Setting $($entry.Key)=$($entry.Value)"
        New-ItemProperty -Path $DeviceRegPath -Name $entry.Key -PropertyType DWord -Value $entry.Value -Force | Out-Null
    }
}

Write-Log "Device registry values after changes:"
if (Test-Path $DeviceRegPath) {
    Get-ItemProperty -Path $DeviceRegPath | Format-List | Out-String | Tee-Object -FilePath $LogPath -Append
}

Write-Log "Restarting uEye USB device"
pnputil /restart-device "$DeviceInstanceId" | Tee-Object -FilePath $LogPath -Append
Write-Log "Restart device exit code: $LASTEXITCODE"

Start-Sleep -Seconds 5

Write-Log "Connected USB devices after restart:"
pnputil /enum-devices /connected /class USB | Tee-Object -FilePath $LogPath -Append

Write-Log "Done"
