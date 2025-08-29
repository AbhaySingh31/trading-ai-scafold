# scripts/fetch_hist.ps1
param(
  [string]$EnvPath = ".env"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Load-DotEnv($path) {
  $map = @{}
  if (Test-Path $path) {
    foreach ($line in Get-Content $path) {
      $s = $line.Trim()
      if ($s -match "^\s*#" -or $s -eq "") { continue }
      if ($s -match "^\s*([^=]+)\s*=\s*(.*)\s*$") {
        $k = $Matches[1].Trim()
        $v = $Matches[2].Trim()
        # strip inline comments at end
        if ($v -match "^(.*?)(\s+#.*)$") { $v = $Matches[1].Trim() }
        $map[$k] = $v
      }
    }
  }
  return $map
}

$cfg = Load-DotEnv $EnvPath
function GetOrDefault($k,$d){ if ($cfg.ContainsKey($k)) { $cfg[$k] } else { $d } }

# Credentials & window
$API   = GetOrDefault "ANGEL_API_KEY" ""
$CODE  = GetOrDefault "ANGEL_CLIENT_CODE" ""
$MPIN  = GetOrDefault "ANGEL_MPIN" ""
$TOTP  = GetOrDefault "ANGEL_TOTP_SECRET" ""
$FROM  = GetOrDefault "HIST_FROM" ""
$TO    = GetOrDefault "HIST_TO" ""

if (-not $API -or -not $CODE -or -not $MPIN -or -not $TOTP -or -not $FROM -or -not $TO) {
  throw "Missing one of ANGEL_API_KEY/ANGEL_CLIENT_CODE/ANGEL_MPIN/ANGEL_TOTP_SECRET/HIST_FROM/HIST_TO in .env"
}

# What to test
$SYMS  = (GetOrDefault "SYMBOLS" "NIFTY,BANKNIFTY").Split(",") | % { $_.Trim() } | Where-Object { $_ -ne "" }
$FAST  = GetOrDefault "INTERVAL_FAST" "1m"
$SLOW  = GetOrDefault "INTERVAL_SLOW" "5m"

# Strategy knobs
$VOL_F = [double](GetOrDefault "VOLUME_MULTIPLE_FAST" "0.0")
$VOL_S = [double](GetOrDefault "VOLUME_MULTIPLE_SLOW" "0.0")
$COOL  = [int](GetOrDefault "COOLDOWN_BARS" "10")
$RSI   = [double](GetOrDefault "RSI_OVERSOLD" "30")

# Risk
$USE_PRESETS = (GetOrDefault "USE_PRESETS" "true").ToLower() -eq "true"
$TICK  = [double](GetOrDefault "TICK_SIZE" "0.05")
$RISK  = [double](GetOrDefault "RISK_PCT" "0.005")
$PTVAL = [double](GetOrDefault "POINT_VALUE" "1")
$CAP   = [double](GetOrDefault "CAPITAL" "1000000")

New-Item -ItemType Directory -Force -Path (Join-Path $root "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root "out") | Out-Null

foreach ($sym in $SYMS) {
  Write-Host "=== $sym ($FROM -> $TO) ===" -ForegroundColor Cyan

  $fastCsv = "data/${sym}_${FAST}_$($FROM -replace '-','')_$($TO -replace '-','').csv"
  $slowCsv = "data/${sym}_${SLOW}_$($FROM -replace '-','')_$($TO -replace '-','').csv"

  # Fetch FAST
  python -m src.trading_ai.cli.angel_hist `
    --use-env --env-path $EnvPath `
    --symbol $sym --interval $FAST --from $FROM --to $TO --out $fastCsv

  # Fetch SLOW
  python -m src.trading_ai.cli.angel_hist `
    --use-env --env-path $EnvPath `
    --symbol $sym --interval $SLOW --from $FROM --to $TO --out $slowCsv

  # Backtest (1m filtered by 5m)
  $sigOut = "out/signals_${sym}_${FROM}_to_${TO}.csv"
  $trdOut = "out/trades_${sym}_${FROM}_to_${TO}.csv"

  $presetFlag = if ($USE_PRESETS) { "--use-presets" } else { "" }

  python -m src.trading_ai.cli.mtf_backtest `
    --symbol $sym `
    --data-fast $fastCsv --timeframe-fast $FAST `
    --data-slow $slowCsv --timeframe-slow $SLOW `
    --rsi-oversold $RSI `
    --volume-multiple-fast $VOL_F `
    --volume-multiple-slow $VOL_S `
    --cooldown $COOL `
    --simulate $presetFlag `
    --tick-size $TICK `
    --risk-pct $RISK `
    --point-value $PTVAL `
    --capital $CAP `
    --out-signals $sigOut `
    --out-trades $trdOut
}
Write-Host "All done. See /out for results." -ForegroundColor Green
