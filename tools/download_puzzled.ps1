param(
    [string]$OutputDirectory = ".datasets/puzzled"
)

$ErrorActionPreference = "Stop"
$baseUrl = "https://groups.inf.ed.ac.uk/vision/DATASETS/PUZZLED"
$ids = @(
    "163904405748",
    "163904657409",
    "163949565032",
    "163965258378",
    "163974758282",
    "16400282145",
    "164002054426",
    "164006412052",
    "164007913498",
    "164008493608"
)

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

foreach ($id in $ids) {
    foreach ($extension in @("csv", "webm")) {
        $destination = Join-Path $OutputDirectory "$id.$extension"
        if (Test-Path $destination) {
            Write-Host "Already present: $destination"
            continue
        }
        $partial = "$destination.partial"
        Write-Host "Downloading $id.$extension"
        $folder = if ($extension -eq "webm") { "VIDEOS" } else { "LABELS" }
        $url = "$baseUrl/$folder/$id.$extension"
        & curl.exe --fail --location --retry 12 --retry-delay 5 --continue-at - `
            --output $partial $url
        if ($LASTEXITCODE -ne 0) {
            throw "curl failed for $url with exit code $LASTEXITCODE"
        }
        Move-Item -LiteralPath $partial -Destination $destination
    }
}

Write-Host "PUZZLED download complete."
