param(
  [string]$Symbols,
  [int]$Interval
)

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
        # strip surrounding quotes if present
        if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
          $v = $v.Substring(1, $v.Length-2)
        }
        $map[$k] = $v.Trim()
      }
    }
  }
  return $map
}

$envFile = Join-Path $root ".env"
$cfg = Load-DotEnv $envFile
function GetOrDefault($k, $d) { if ($cfg.ContainsKey($k)) { $cfg[$k] } else { $d } }

$API_KEY = GetOrDefault "ANGEL_API_KEY" ""
$CLIENT  = GetOrDefault "ANGEL_CLIENT_CODE" ""
$MPIN    = GetOrDefault "ANGEL_MPIN" ""
$TOTP    = GetOrDefault "ANGEL_TOTP_SECRET" ""
if (-not $API_KEY -or -not $CLIENT -or -not $MPIN -or -not $TOTP) {
  Write-Error "Missing one of ANGEL_API_KEY / ANGEL_CLIENT_CODE / ANGEL_MPIN / ANGEL_TOTP_SECRET in .env"
}

$TICK    = [double](GetOrDefault "TICK_SIZE" "0.05")
$RISK    = [double](GetOrDefault "RISK_PCT" "0.005")
$OPT_SL  = [double](GetOrDefault "OPT_SL_PCT" "0.25")
$OPT_TP1 = [double](GetOrDefault "OPT_TP1_PCT" "0.5")
$OPT_TP2 = [double](GetOrDefault "OPT_TP2_PCT" "1.0")
$SYMS    = if ($Symbols) { $Symbols } else { GetOrDefault "SYMBOLS" "NIFTY,BANKNIFTY" }
$INTV    = if ($PSBoundParameters.ContainsKey("Interval")) { $Interval } else { [int](GetOrDefault "INTERVAL" "30") }

$newTokens = Join-Path $root "out\tokens.json"
New-Item -ItemType Directory -Force -Path (Join-Path $root "out") | Out-Null

Write-Host "[1/2] Logging in..." -ForegroundColor Cyan
# NOTE: pass MPIN via --mpin; TOTP secret will be sanitized in Python
python -m src.trading_ai.cli.angel_login `
  --api-key $API_KEY `
  --client-code $CLIENT `
  --mpin $MPIN `
  --totp-secret $TOTP `
  > $newTokens

if ($LASTEXITCODE -ne 0) { throw "Login failed (see output above)" }

$tok  = Get-Content $newTokens | ConvertFrom-Json
$jwt  = $tok.jwt_token
$feed = $tok.feed_token
if (-not $jwt -or -not $feed) { throw "Tokens missing in $newTokens" }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outCsv = "out\trades_live_$ts.csv"

Write-Host "[2/2] Starting live_run..." -ForegroundColor Cyan
python -m src.trading_ai.cli.live_run `
  --api-key $API_KEY `
  --client-code $CLIENT `
  --jwt-token "$jwt" `
  --feed-token "$feed" `
  --symbols $SYMS `
  --interval $INTV `
  --use-presets --tick-size $TICK --risk-pct $RISK `
  --opt-enable --opt-sl-pct $OPT_SL --opt-tp1-pct $OPT_TP1 --opt-tp2-pct $OPT_TP2 `
  --out-trades $outCsv
