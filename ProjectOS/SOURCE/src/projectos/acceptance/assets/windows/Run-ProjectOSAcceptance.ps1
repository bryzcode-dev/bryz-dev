$ErrorActionPreference = "Stop"
python -m projectos.acceptance_host @args
exit $LASTEXITCODE
