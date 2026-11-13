param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "Stop"

function Load-JsonFile($path) {
    if (-not (Test-Path $path)) {
        return @{}
    }
    $obj = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
    return ConvertTo-Hashtable $obj
}

function ConvertTo-Hashtable($obj) {
    if ($null -eq $obj) { return $null }
    if ($obj -is [System.Collections.IEnumerable] -and -not ($obj -is [string])) {
        $list = @()
        foreach ($item in $obj) {
            $list += ,(ConvertTo-Hashtable $item)
        }
        return $list
    }
    if ($obj -is [pscustomobject]) {
        $hash = @{}
        foreach ($p in $obj.PSObject.Properties) {
            $hash[$p.Name] = ConvertTo-Hashtable $p.Value
        }
        return $hash
    }
    return $obj
}

function Merge-Hashtable($base, $override) {
    $merged = @{}
    foreach ($k in $base.Keys) { $merged[$k] = $base[$k] }
    foreach ($k in $override.Keys) {
        if ($merged[$k] -is [hashtable] -and $override[$k] -is [hashtable]) {
            $merged[$k] = Merge-Hashtable $merged[$k] $override[$k]
        } else {
            $merged[$k] = $override[$k]
        }
    }
    return $merged
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$defaultPaths = Join-Path $projectRoot "configs/paths.default.json"
$defaultRuntime = Join-Path $projectRoot "configs/runtime.default.json"

$cfg = @{
    paths = Load-JsonFile $defaultPaths
    runtime = Load-JsonFile $defaultRuntime
}

if ($ConfigPath -ne "") {
    $userCfg = Load-JsonFile $ConfigPath
    $cfg = Merge-Hashtable $cfg $userCfg
}

function Resolve-ProjectPath($value) {
    if ([System.IO.Path]::IsPathRooted($value)) { return $value }
    return Join-Path $projectRoot $value
}

$paths = $cfg.paths
$checks = @(
    @{ Name = "RPU DB"; Path = Resolve-ProjectPath $paths.rpu_db_path; Type = "File" },
    @{ Name = "Innovation Output"; Path = Resolve-ProjectPath $paths.innovation_output_dir; Type = "Dir" },
    @{ Name = "Impact Output"; Path = Resolve-ProjectPath $paths.impact_output_dir; Type = "Dir" },
    @{ Name = "Signals Output"; Path = Resolve-ProjectPath $paths.paper_signals_output_dir; Type = "Dir" },
    @{ Name = "Analysis Output"; Path = Resolve-ProjectPath $paths.analysis_output_dir; Type = "Dir" }
)

Write-Host "=== Health Check ==="
Write-Host "Project Root: $projectRoot"
Write-Host ""

$failed = $false
foreach ($item in $checks) {
    $exists = Test-Path $item.Path
    $status = if ($exists) { "OK" } else { "MISSING" }
    Write-Host ("[{0}] {1}: {2}" -f $status, $item.Name, $item.Path)
    if (-not $exists) { $failed = $true }
}

Write-Host ""
Write-Host "=== Removed Root Launcher Check ==="
$removedRootLaunchers = @(
    "run_v2_full.py",
    "calculate_impact_v2.py",
    "merge_signals.py",
    "query_paper.py"
)

foreach ($script in $removedRootLaunchers) {
    $path = Join-Path $projectRoot $script
    $exists = Test-Path $path
    $status = if ($exists) { "FAIL" } else { "OK" }
    Write-Host ("[{0}] {1}" -f $status, $script)
    if ($exists) { $failed = $true }
}

Write-Host ""
Write-Host "=== Canonical Script Check ==="
$canonicalScripts = @(
    "scripts/pipeline/run_v2_full.py",
    "scripts/pipeline/calculate_impact_v2.py",
    "scripts/legacy/calculate_impact_v2_lowmem.py",
    "scripts/legacy/calculate_impact_v2_optimized.py",
    "scripts/pipeline/merge_signals.py",
    "scripts/query/query_paper.py",
    "scripts/query/infer_single_paper_deberta.py",
    "scripts/query/query_one_paper_score.py",
    "scripts/query/query_classics_scores.py",
    "scripts/analyze/analyze_distributions.py",
    "scripts/analyze/analyze_trends.py",
    "scripts/legacy/apply_abstract_layer.py",
    "scripts/legacy/convert_rpu_to_spans.py",
    "scripts/legacy/inference_research_structure.py",
    "scripts/legacy/inspect_opinion_meta.py",
    "scripts/legacy/mine_phrases.py",
    "scripts/legacy/normalize_cores.py",
    "scripts/legacy/rpu_full_extraction.py",
    "scripts/legacy/rpu_full_extraction_deberta.py",
    "scripts/legacy/rpu_validator.py",
    "scripts/legacy/supplement_paper_metadata.py",
    "scripts/train/train_deberta_multihead.py",
    "scripts/train/train_research_structure_extractor.py"
)

foreach ($script in $canonicalScripts) {
    $path = Join-Path $projectRoot $script
    $exists = Test-Path $path
    $status = if ($exists) { "OK" } else { "MISSING" }
    Write-Host ("[{0}] {1}" -f $status, $script)
    if (-not $exists) { $failed = $true }
}

Write-Host ""
Write-Host "=== Validation Entry Check ==="
$validationCliScripts = @()

foreach ($script in $validationCliScripts) {
    $path = Join-Path $projectRoot $script
    $exists = Test-Path $path
    $status = if ($exists) { "OK" } else { "MISSING" }
    Write-Host ("[{0}] {1}" -f $status, $script)
    if (-not $exists) { $failed = $true }
}

$validationCanonicalScripts = @(
    "scripts/legacy/validation/check_emerging_topic_scores.py",
    "scripts/legacy/validation/check_extraction_quality.py",
    "scripts/legacy/validation/check_landmark_paper_scores.py",
    "scripts/legacy/validation/validate_impact_v2.py",
    "scripts/legacy/validation/validate_innovation_distribution.py",
    "scripts/legacy/validation/validate_v2_results.py"
)

foreach ($script in $validationCanonicalScripts) {
    $path = Join-Path $projectRoot $script
    $exists = Test-Path $path
    $status = if ($exists) { "OK" } else { "MISSING" }
    Write-Host ("[{0}] {1}" -f $status, $script)
    if (-not $exists) { $failed = $true }
}

Write-Host ""
Write-Host "=== Root Whitelist Check ==="
$allowedRootFiles = @(
    ".gitignore",
    "README.md",
    "project_config.py",
    "core_mapping.json",
    "phrase_table.json",
    "span_labels.json",
    "verb_innovation_weights.json",
    "research_structure_training_data.xlsx"
)

$rootFiles = Get-ChildItem -Path $projectRoot -File | Select-Object -ExpandProperty Name
$unexpected = @()
foreach ($f in $rootFiles) {
    if ($allowedRootFiles -notcontains $f) {
        $unexpected += $f
    }
}

if ($unexpected.Count -eq 0) {
    Write-Host "[OK] root whitelist clean"
} else {
    Write-Host "[WARN] unexpected root files detected:" -ForegroundColor Yellow
    foreach ($f in $unexpected | Sort-Object) {
        Write-Host ("  - {0}" -f $f)
    }
}

$allowedRootDirs = @(
    ".claude",
    ".taskflow",
    "__pycache__",
    "anomaly_detection",
    "artifacts",
    "configs",
    "data",
    "docs",
    "models",
    "output_7_deberta_full",
    "scripts",
    "src",
    "tools"
)

$rootDirs = Get-ChildItem -Path $projectRoot -Directory | Select-Object -ExpandProperty Name
$unexpectedDirs = @()
foreach ($d in $rootDirs) {
    if ($allowedRootDirs -notcontains $d) {
        $unexpectedDirs += $d
    }
}

if ($unexpectedDirs.Count -eq 0) {
    Write-Host "[OK] root directory whitelist clean"
} else {
    Write-Host "[WARN] unexpected root directories detected:" -ForegroundColor Yellow
    foreach ($d in $unexpectedDirs | Sort-Object) {
        Write-Host ("  - {0}" -f $d)
    }
}

$coreModules = @(
    "src/innovation_core/config_manager.py",
    "src/innovation_core/error_handling.py",
    "src/innovation_core/performance_metrics.py",
    "src/innovation_core/performance_reporter.py"
)

foreach ($module in $coreModules) {
    $path = Join-Path $projectRoot $module
    $exists = Test-Path $path
    $status = if ($exists) { "OK" } else { "MISSING" }
    Write-Host ("[{0}] {1}" -f $status, $module)
    if (-not $exists) { $failed = $true }
}

Write-Host ""
Write-Host "=== Hardcoded Path Scan ==="

$scanRules = @(
    @{ Name = "Windows absolute path"; Pattern = '\b[A-Za-z]:[\\/][^\s]+[\\/][^\s]+' },
    @{ Name = "Legacy runtime dir literal"; Pattern = '(output_7_deberta_full|innovation_v2_output|impact_output|paper_signals_output|analysis_output)[\\/]' }
)

function Collect-HardcodedHits($files, $rules, $rootPath) {
    $hits = @()
    foreach ($file in $files) {
        foreach ($rule in $rules) {
            $matches = Select-String -Path $file.FullName -Pattern $rule.Pattern -Encoding UTF8
            foreach ($m in $matches) {
                $relativePath = $m.Path.Substring($rootPath.Length + 1)
                $lineText = $m.Line.Trim()
                if ($lineText.Length -gt 120) {
                    $lineText = $lineText.Substring(0, 117) + "..."
                }
                $hits += @{
                    Rule = $rule.Name
                    Path = $relativePath
                    Line = $m.LineNumber
                    Text = $lineText
                }
            }
        }
    }
    return $hits
}

$scriptFiles = @()
$scriptPath = Join-Path $projectRoot "scripts"
if (Test-Path $scriptPath) {
    $scriptFiles += Get-ChildItem -Path $scriptPath -Recurse -File -Include *.py
}

$docFiles = @()
$docPath = Join-Path $projectRoot "docs"
if (Test-Path $docPath) {
    $docFiles += Get-ChildItem -Path $docPath -Recurse -File -Include *.md
}

$scriptHits = Collect-HardcodedHits $scriptFiles $scanRules $projectRoot
$docHits = Collect-HardcodedHits $docFiles $scanRules $projectRoot

if ($scriptHits.Count -eq 0) {
    Write-Host "[OK] scripts hardcoded-path scan clean"
} else {
    Write-Host ("[FAIL] detected {0} hardcoded-path hits in scripts:" -f $scriptHits.Count) -ForegroundColor Red
    $maxShow = 20
    $shown = 0
    foreach ($w in $scriptHits) {
        if ($shown -ge $maxShow) { break }
        Write-Host ("  - [{0}] {1}:{2} {3}" -f $w.Rule, $w.Path, $w.Line, $w.Text)
        $shown++
    }
    if ($scriptHits.Count -gt $maxShow) {
        Write-Host ("  ... {0} more entries omitted" -f ($scriptHits.Count - $maxShow))
    }
    $failed = $true
}

if ($docHits.Count -eq 0) {
    Write-Host "[OK] docs hardcoded-path scan clean"
} else {
    Write-Host ("[WARN] detected {0} hardcoded-path hits in docs (warn-only):" -f $docHits.Count) -ForegroundColor Yellow
    $maxShow = 20
    $shown = 0
    foreach ($w in $docHits) {
        if ($shown -ge $maxShow) { break }
        Write-Host ("  - [{0}] {1}:{2} {3}" -f $w.Rule, $w.Path, $w.Line, $w.Text)
        $shown++
    }
    if ($docHits.Count -gt $maxShow) {
        Write-Host ("  ... {0} more entries omitted" -f ($docHits.Count - $maxShow))
    }
}

Write-Host ""
if ($failed) {
    Write-Host "Health check finished with missing items." -ForegroundColor Yellow
    exit 1
}

Write-Host "Health check passed." -ForegroundColor Green
exit 0
