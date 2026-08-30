param(
  [string]$ProjectRoot = ".",
  [string]$OutputDir = ".dv-workflow"
)

$ErrorActionPreference = "SilentlyContinue"
$root = (Resolve-Path $ProjectRoot).Path
$out = Join-Path $root $OutputDir
New-Item -ItemType Directory -Force $out | Out-Null

$skipRegex = '\\(\.git|node_modules|\.dv-workflow|csrc|INCA_libs|work|build|out|dist)\\'
$files = Get-ChildItem -Path $root -Recurse -File -Force |
  Where-Object { $_.FullName -notmatch $skipRegex }

function Pick([string[]]$patterns) {
  @($files | Where-Object {
    $x = $_.FullName.ToLower()
    foreach ($p in $patterns) {
      if ($x -match $p) { return $true }
    }
    return $false
  } | Select-Object -First 400 -ExpandProperty FullName)
}

$inv = [ordered]@{
  generated_at=(Get-Date).ToString("o")
  project_root=$root
  total_files=@($files).Count
  project_files=@($files | Select-Object -First 500 -ExpandProperty FullName)
  rtl=Pick @('\.(sv|svh|v|vh|vhd|vhdl)$','\\rtl\\','\\dut\\')
  uvm_vip=Pick @('uvm','vip','bfm','sequencer','driver','monitor','scoreboard','env')
  tests_sequences=Pick @('test','sequence','scenario','testlist','runlist')
  docs=Pick @('\.(pdf|doc|docx|md|txt|xlsx|xls|csv)$','spec','architecture','design')
  vplan=Pick @('vplan','testplan','verification[_ -]?plan','coverage[_ -]?plan')
  build_regression=Pick @('makefile','compile','build','regress','regression','vcs','xrun','questa','bsub','qsub','\.tcl$','\.ps1$','\.sh$','\.csh$')
  coverage=Pick @('cover','coverage','assert','sva')
  protocol_hints=[ordered]@{
    usb=Pick @('usb','xhci','utmi','ulpi','pipe')
    pcie=Pick @('pcie','pci[_ -]?express','ltssm','tlp','dllp')
    csi2=Pick @('csi2','csi-2','mipi[_ -]?csi','dphy','cphy')
    dsi=Pick @('mipi[_ -]?dsi','\\dsi\\','dsi_host','dsi_tx','dsi_rx')
    ethernet=Pick @('ethernet','xgmii','usxgmii','sgmii','rgmii','gmii','\\mac\\','\\pcs\\')
    canfd=Pick @('canfd','can[_ -]?fd','busoff')
    amba=Pick @('axi4','axi3','axis','axi-stream','apb','ahb','ace')
  }
}

$path = Join-Path $out "inventory.json"
$inv | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $path
Write-Host "DV inventory: $path"
