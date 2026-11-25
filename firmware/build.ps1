# Build the firmware with the toolchain bundled in STM32CubeIDE (no extra install).
#   .\build.ps1          -> build\sdm_f746.elf and build\sdm_f746.bin
#   .\build.ps1 clean
$ErrorActionPreference = "Stop"
$ide = Get-ChildItem "C:\ST" -Directory -Filter "STM32CubeIDE_*" |
       Sort-Object Name -Descending | Select-Object -First 1
if (-not $ide) { throw "STM32CubeIDE not found under C:\ST" }
$plugins = Join-Path $ide.FullName "STM32CubeIDE\plugins"
$gcc  = Get-ChildItem $plugins -Directory -Filter "*gnu-tools-for-stm32*win32*" | Select-Object -First 1
$make = Get-ChildItem $plugins -Directory -Filter "*externaltools.make.win32*" | Select-Object -First 1
$env:PATH = "$($gcc.FullName)\tools\bin;$($make.FullName)\tools\bin;$env:PATH"
Push-Location $PSScriptRoot
try {
    # run through cmd so compiler messages on stderr are not turned into PowerShell errors
    & cmd /c "make $($args -join ' ') 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "make failed (exit $LASTEXITCODE)" }
}
finally { Pop-Location }
