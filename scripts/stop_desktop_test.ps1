$ErrorActionPreference = "Stop"

$result = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8790/session/stop-desktop" `
    -Method Post

$result | ConvertTo-Json
