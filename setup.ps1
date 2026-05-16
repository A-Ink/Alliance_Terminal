Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  ALLIANCE TERMINAL V3 : DEPLOYMENT SCRIPT" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 1. Check Python
Write-Host "`n[*] Verifying Python 3.12 Environment..."
if (!(Get-Command "py" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Python Launcher 'py' not found. Please install Python 3.12 from python.org." -ForegroundColor Red
    Pause
    exit
}

# 2. Virtual Environment
Write-Host "[*] Initializing Virtual Environment..."
if (!(Test-Path ".venv")) {
    py -3.12 -m venv .venv
    Write-Host "[OK] Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "[*] Virtual environment already exists." -ForegroundColor Yellow
}

Write-Host "[*] Upgrading pip..."
.\.venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "[*] Installing core dependencies (OpenVINO, UI, etc.)..."
.\.venv\Scripts\pip install -r requirements.txt

# 3. CUDA Toolkit Installation (for dGPU)
Write-Host "`n==============================================" -ForegroundColor Yellow
Write-Host "  CUDA TOOLKIT & GPU INFERENCE ENGINE" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "The dGPU backend requires CUDA Toolkit 12.6 and llama-cpp-python compiled with CUDA support."
Write-Host "Note: CUDA 13.x has known issues with some AI models. CUDA 12.6 is recommended." -ForegroundColor Yellow
Write-Host ""

# Check for CUDA Toolkit
$cudaAvailable = $false
$cudaVersion = ""
try {
    $nvccOutput = nvcc --version 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) {
        $cudaAvailable = $true
        # Extract version number
        if ($nvccOutput -match "release (\d+\.\d+)") {
            $cudaVersion = $Matches[1]
        }
        Write-Host "[OK] CUDA Toolkit detected: v$cudaVersion" -ForegroundColor Green
        
        # Warn about CUDA 13.x
        if ($cudaVersion -match "^13\.") {
            Write-Host "[WARN] CUDA 13.x detected. This version has known issues with Gemma and Qwen models." -ForegroundColor Red
            Write-Host "       Recommended: Downgrade to CUDA Toolkit 12.6" -ForegroundColor Yellow
            Write-Host "       Download: https://developer.nvidia.com/cuda-12-6-0-download-archive" -ForegroundColor White
        }
    }
} catch {
    Write-Host "[INFO] CUDA Toolkit not found (nvcc not in PATH)." -ForegroundColor Yellow
}

# Check for Vulkan SDK
$vulkanAvailable = Test-Path "$env:VULKAN_SDK"
if ($vulkanAvailable) {
    Write-Host "[OK] Vulkan SDK detected at $env:VULKAN_SDK" -ForegroundColor Green
}

if (-not $cudaAvailable -and -not $vulkanAvailable) {
    Write-Host "[WARN] Neither CUDA Toolkit nor Vulkan SDK detected." -ForegroundColor Red
    Write-Host ""
    Write-Host "For NVIDIA RTX GPUs (recommended): Install CUDA Toolkit 12.6 from:" -ForegroundColor Cyan
    Write-Host "  https://developer.nvidia.com/cuda-12-6-0-download-archive" -ForegroundColor White
    Write-Host ""
    Write-Host "After installing CUDA Toolkit, restart your terminal and re-run this script." -ForegroundColor Yellow
    Write-Host ""
    $installCuda = Read-Host "Would you like to attempt installing CUDA Toolkit 12.6 via winget? (Y/N)"
    if ($installCuda -match "^[yY]") {
        Write-Host "`n[*] Installing CUDA Toolkit 12.6 via winget..." -ForegroundColor Cyan
        winget install Nvidia.CUDA --version 12.6 --accept-package-agreements --accept-source-agreements
        Write-Host "[INFO] Please restart your terminal after installation, then re-run this script." -ForegroundColor Yellow
        Pause
        exit
    }
}

Write-Host ""
Write-Host "Available GPU backends:"
if ($cudaAvailable) {
    Write-Host "  [1] CUDA   (Recommended for NVIDIA RTX. Uses Tensor Cores + Flash Attention)" -ForegroundColor Green
}
if ($vulkanAvailable) {
    Write-Host "  [2] Vulkan (Cross-platform. Works with Intel Arc and NVIDIA.)" -ForegroundColor Cyan
}
Write-Host "  [P] Pre-built (Install pre-compiled llama-cpp-python wheel for CUDA 12.x)" -ForegroundColor Magenta
Write-Host "  [S] Skip   (Only use NPU/OpenVINO models)" -ForegroundColor Gray

$gpuChoice = Read-Host "`nSelect GPU backend (1/2/P/S)"

if ($gpuChoice -eq "1" -and $cudaAvailable) {
    Write-Host "`n[*] Compiling llama-cpp-python with CUDA + Flash Attention..." -ForegroundColor Cyan
    
    # VS Build Tools check
    $vsPath = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vs_installer.exe"
    if (!(Test-Path $vsPath)) {
        Write-Host "[!] VS Build Tools not found. Attempting to install via winget..."
        winget install Microsoft.VisualStudio.2022.BuildTools --force --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools" --accept-package-agreements --accept-source-agreements
    }

    $env:CMAKE_ARGS = "-DGGML_CUDA=on -DGGML_CUDA_FA_ALL_QUANTS=on"
    .\.venv\Scripts\python.exe -m pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir
    
    Write-Host "`n[SUCCESS] CUDA Llama.cpp Engine established! (Flash Attention enabled)" -ForegroundColor Green
} elseif ($gpuChoice -eq "2" -and $vulkanAvailable) {
    Write-Host "`n[*] Compiling llama-cpp-python with Vulkan..." -ForegroundColor Cyan
    
    $vsPath = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vs_installer.exe"
    if (!(Test-Path $vsPath)) {
        Write-Host "[!] VS Build Tools not found. Attempting to install via winget..."
        winget install Microsoft.VisualStudio.2022.BuildTools --force --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools" --accept-package-agreements --accept-source-agreements
    }

    $env:CMAKE_ARGS = "-DGGML_VULKAN=on"
    .\.venv\Scripts\python.exe -m pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir
    
    Write-Host "`n[SUCCESS] Vulkan Llama.cpp Engine established!" -ForegroundColor Green
} elseif ($gpuChoice -match "^[pP]") {
    Write-Host "`n[*] Installing pre-compiled llama-cpp-python with CUDA 12.x support..." -ForegroundColor Cyan
    Write-Host "    This skips compilation and uses a pre-built wheel." -ForegroundColor Gray
    
    # Install pre-built wheel from the llama-cpp-python releases
    .\.venv\Scripts\python.exe -m pip install llama-cpp-python --upgrade --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Pre-built CUDA llama-cpp-python installed!" -ForegroundColor Green
    } else {
        Write-Host "`n[WARN] Pre-built install failed. Try option [1] to compile from source." -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[*] Skipping GPU Engine. OpenVINO (NPU) models will function as the primary backend." -ForegroundColor Cyan
}

Write-Host "`n==============================================" -ForegroundColor Green
Write-Host "  INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "1. Activate venv: .\.venv\Scripts\Activate.ps1"
Write-Host "2. Download models: python download_model.py"
Write-Host "3. Launch Terminal: python main.py"
Write-Host "==============================================" -ForegroundColor Green
Pause

