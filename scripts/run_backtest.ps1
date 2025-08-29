# scripts/run_backtest.ps1
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Load-DotEnv($path) {
  $map = @{}
  if (Test-Path $path) {
    foreach ($line in Get-Content $path) {
      if ($line -match "^\s*#" -or $line.Trim() -eq "") { continue }
      if ($line -match "^\s*([^=]+)\s*=\s*(.*)\s*$") {
        $k = $Matches[1].Trim()
        $v = $Matches[2].Trim()
        if ($v -match "^\s*#") { $v = "" }
        $map[$k] = $v
      }
    }
  }
  return $map
}

function GetOrDefault($m, $k, $d) { if ($m.ContainsKey($k) -and $m[$k]) { $m[$k] } else { $d } }

$envp = Join-Path $root ".env"
$cfg = Load-DotEnv $envp

# dates
$from = GetOrDefault $cfg "HIST_FROM" ""
$to   = GetOrDefault $cfg "HIST_TO" ""
if (-not $from -or -not $to) {
  throw "HIST_FROM / HIST_TO missing in .env (dd-mm-yyyy)"
}
function DateFile($d) { (Get-Date $d -Format "ddMMyyyy") }

$fromTag = DateFile $from
$toTag   = DateFile $to

# symbols + per-symbol params
$SYMBOLS   = (GetOrDefault $cfg "SYMBOLS" "NIFTY,BANKNIFTY").Split(",") | ForEach-Object { $_.Trim().ToUpper() }
$RSI       = [double](GetOrDefault $cfg "RSI_OVERSOLD" "50")
$CONFIRM   = [int](GetOrDefault $cfg "CONFIRM_BARS" "5")
$CAPITAL   = [double](GetOrDefault $cfg "CAPITAL" "30000")
$RISK_PCT  = [double](GetOrDefault $cfg "RISK_PCT" "0.02")
$DELTA_DEF = [double](GetOrDefault $cfg "DELTA_FACTOR" "1.0")

# defaults (you can override in .env)
$LOT_NIFTY     = [int](GetOrDefault $cfg "LOT_SIZE_NIFTY" "75")
$LOT_BANKNIFTY = [int](GetOrDefault $cfg "LOT_SIZE_BANKNIFTY" "35")
$SL_NIFTY  = [double](GetOrDefault $cfg "SL_PTS_NIFTY" "35")
$SL_BANK   = [double](GetOrDefault $cfg "SL_PTS_BANKNIFTY" "70")
$TP_NIFTY  = [double](GetOrDefault $cfg "TP1_PTS_NIFTY" "20")
$TP_BANK   = [double](GetOrDefault $cfg "TP1_PTS_BANKNIFTY" "40")
$DELTA_NIFTY = [double](GetOrDefault $cfg "DELTA_NIFTY" $DELTA_DEF)
$DELTA_BANK  = [double](GetOrDefault $cfg "DELTA_BANKNIFTY" $DELTA_DEF)

# ensure data exists (use 1m)
$paths = @{}
foreach ($s in $SYMBOLS) {
  $path = "data\${s}_1m_${fromTag}_${toTag}.csv"
  if (-not (Test-Path $path)) {
    Write-Host "Missing $path; will try to fetch..." -ForegroundColor Yellow
    & scripts\fetch_hist.ps1
    if (-not (Test-Path $path)) { throw "Still missing $path after fetch." }
  }
  $paths[$s] = $path
}

New-Item -ItemType Directory -Force -Path "out" | Out-Null

foreach ($s in $SYMBOLS) {
  if ($s -eq "NIFTY") {
    $lot = $LOT_NIFTY; $sl = $SL_NIFTY; $tp = $TP_NIFTY; $delta = $DELTA_NIFTY
  } else {
    $lot = $LOT_BANKNIFTY; $sl = $SL_BANK; $tp = $TP_BANK; $delta = $DELTA_BANK
  }
  $data = $paths[$s]
  $out  = "out\trades_seq_${s}_1m_${from}_${to}.csv"

  Write-Host "=== Backtest $s ($from -> $to) ===" -ForegroundColor Cyan
  python scripts/seq_backtest.py `
    --data "$data" `
    --symbol $s `
    --rsi-oversold $RSI `
    --confirm-bars $CONFIRM `
    --sl-pts $sl `
    --tp1-pts $tp `
    --lot-size $lot `
    --capital $CAPITAL `
    --risk-pct $RISK_PCT `
    --delta-factor $delta `
    --out-trades "$out"
}
Write-Host "All done. See /out for results."
