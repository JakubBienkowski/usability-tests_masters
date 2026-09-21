param(
    [string]$StudyId = "",
    [string]$ParticipantId = "",
    [string]$Label = "Desktop usability test"
)

$ErrorActionPreference = "Stop"
$body = @{
    study_id = if ($StudyId) { $StudyId } else { $null }
    participant_id = if ($ParticipantId) { $ParticipantId } else { $null }
    label = $Label
} | ConvertTo-Json

$result = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8790/session/start-desktop" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body

$result | ConvertTo-Json
