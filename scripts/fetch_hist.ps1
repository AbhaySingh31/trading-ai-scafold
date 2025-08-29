param()

$ErrorActionPreference = "Stop"

# --- repo root (parent of the scripts folder) ---
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root      = Split-Path -Parent $scriptDir
Set-Location $root

# Ensure Python can import from ./src when using -m
$env:PYTHONPATH = "$root\src;$env:PYTHONPATH"

function Load-DotEnv($path) {
  $map = @{}
  if (Test-Path $path) {
    # Force UTF-8; trim whitespace; strip inline "  # comment"
    foreach ($line in Get-Content -Path $path -Encoding UTF8) {
      if ($line -match "^\s*#" -or $line.Trim() -eq "") { continue }
      if ($line -match "^\s*([^=]+)\s*=\s*(.*)\s*$") {
        $key = $Matches[1].Trim()
        $val = $Matches[2]
        if ($val -match "^(.*?)(\s+#.*)?$") { $val = $Matches[1] }
        $val = $val.Trim().Trim("`"","'")
        $map[$key] = $val
      }
    }
  }
  return $map
}

$cfg = Load-DotEnv (Join-Path $root ".env")
Write-Host "[env] Loaded $($cfg.Count) keys from $((Join-Path $root '.env'))"
foreach ($k in @('ANGEL_API_KEY','ANGEL_CLIENT_CODE','ANGEL_MPIN','ANGEL_TOTP_SECRET')) {
  $v = $cfg[$k]
  if ($v) {
    $mask = if ($v.Length -ge 6) { ($v.Substring(0,2) + "..." + $v.Substring($v.Length-2,2)) } else { "***" }
    Write-Host ("[env] {0} = {1}" -f $k,$mask)
  } else {
    Write-Host ("[env] {0} = (missing)" -f $k)
  }
}

# required creds
$API_KEY = $cfg.ANGEL_API_KEY
$CLIENT  = $cfg.ANGEL_CLIENT_CODE
$MPIN    = $cfg.ANGEL_MPIN
$TOTP    = $cfg.ANGEL_TOTP_SECRET
if (-not $API_KEY -or -not $CLIENT -or -not $MPIN -or -not $TOTP) {
  throw "Missing ANGEL_API_KEY / ANGEL_CLIENT_CODE / ANGEL_MPIN / ANGEL_TOTP_SECRET in .env"
}

# window + symbols
$FROM = $cfg.HIST_FROM
$TO   = $cfg.HIST_TO
$SYMS = @()
if ($cfg.SYMBOLS) { $SYMS = $cfg.SYMBOLS -split "," } else { $SYMS = @("NIFTY","BANKNIFTY") }

# tokens (put these in .env)
$TOKENS = @{
  "NIFTY"     = $cfg.NIFTY_TOKEN
  "BANKNIFTY" = $cfg.BANKNIFTY_TOKEN
}

# intervals
$FAST = $cfg.INTERVAL_FAST
$SLOW = $cfg.INTERVAL_SLOW

# output dirs
New-Item -ItemType Directory -Force -Path (Join-Path $root "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root "out")  | Out-Null

foreach ($sym in $SYMS) {
  $SYMU = $sym.Trim().ToUpper()
  $tok = $TOKENS[$SYMU]
  if (-not $tok) { throw "Missing token for $SYMU. Add ${SYMU}_TOKEN to .env" }

  Write-Host "=== $SYMU ($FROM -> $TO) ==="

  $fastOut = "data\$SYMU`_$FAST`_$($FROM -replace '-','')`_$($TO -replace '-','').csv"
  $slowOut = "data\$SYMU`_$SLOW`_$($FROM -replace '-','')`_$($TO -replace '-','').csv"

  # login + fetch fast
  python -m src.trading_ai.cli.angel_hist `
    --use-env `
    --symbol $SYMU `
    --token $tok `
    --interval $FAST `
    --from $FROM `
    --to $TO `
    --out $fastOut

  # login + fetch slow
  python -m src.trading_ai.cli.angel_hist `
    --use-env `
    --symbol $SYMU `
    --token $tok `
    --interval $SLOW `
    --from $FROM `
    --to $TO `
    --out $slowOut

  # Run MTF backtest runner (call the file directly to avoid -m path quirks)
  python "src\trading_ai\cli\mtf_backtest.py" `
    --symbol $SYMU `
    --fast-csv $fastOut `
    --slow-csv $slowOut `
    --use-presets `
    --out-signals ("out\signals_{0}_{1}_to_{2}.csv" -f $SYMU,$FROM,$TO) `
    --out-trades  ("out\trades_{0}_{1}_to_{2}.csv"  -f $SYMU,$FROM,$TO)
}

Write-Host "All done. See /out for results."
