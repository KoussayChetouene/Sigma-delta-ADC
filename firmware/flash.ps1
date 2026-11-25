# Flash build\sdm_f746.elf over the on-board ST-LINK (board connected by USB on CN14).
# Alternative with no tools: copy build\sdm_f746.bin onto the "DIS_F746NG" USB drive.
$ErrorActionPreference = "Stop"
$ide = Get-ChildItem "C:\ST" -Directory -Filter "STM32CubeIDE_*" |
       Sort-Object Name -Descending | Select-Object -First 1
$plugins = Join-Path $ide.FullName "STM32CubeIDE\plugins"
$prog = Get-ChildItem $plugins -Directory -Filter "*cubeprogrammer.win32*" | Select-Object -First 1
$cli  = Join-Path $prog.FullName "tools\bin\STM32_Programmer_CLI.exe"
$elf  = Join-Path $PSScriptRoot "build\sdm_f746.elf"
if (-not (Test-Path $elf)) { throw "Build first: .\build.ps1" }
& $cli -c port=SWD -w $elf -v -rst
