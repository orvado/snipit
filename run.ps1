# Launch SnipIt from the project folder.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
python -m snipit
