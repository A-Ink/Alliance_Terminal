Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  N7 TERMINAL : AUTOMATED DEPLOYMENT SCRIPT" -ForegroundColor Cyan
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

# 3. Llama.cpp GPU Backend (CUDA or Vulkan)
Write-Host "`n==============================================" -ForegroundColor Yellow
Write-Host "  GPU INFERENCE ENGINE (CUDA / VULKAN)" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Yellow
Write-Host "To run large GGUF models on your NVIDIA dGPU, a GPU backend is required."
Write-Host ""

# Check for CUDA Toolkit
$cudaAvailable = $false
try {
    $nvccOutput = nvcc --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $cudaAvailable = $true
        Write-Host "[OK] CUDA Toolkit detected:" -ForegroundColor Green
        Write-Host "     $nvccOutput" -ForegroundColor Gray
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
    Write-Host "For NVIDIA RTX GPUs (recommended): Install CUDA Toolkit from:" -ForegroundColor Cyan
    Write-Host "  https://developer.nvidia.com/cuda-downloads" -ForegroundColor White
    Write-Host "  Or via winget: winget install Nvidia.CUDA --accept-package-agreements" -ForegroundColor White
    Write-Host ""
    $installCuda = Read-Host "Would you like to attempt installing CUDA Toolkit via winget? (Y/N)"
    if ($installCuda -match "^[yY]") {
        Write-Host "`n[*] Installing CUDA Toolkit via winget..." -ForegroundColor Cyan
        winget install Nvidia.CUDA --accept-package-agreements --accept-source-agreements
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
Write-Host "  [S] Skip   (Only use NPU/OpenVINO models)" -ForegroundColor Gray

$gpuChoice = Read-Host "`nSelect GPU backend (1/2/S)"

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

