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
Write-Host "  [M] MTP Build (Build from latest llama.cpp master - REQUIRED for Qwen 3.6 MTP models)" -ForegroundColor Yellow
Write-Host "  [S] Skip   (Only use NPU/OpenVINO models)" -ForegroundColor Gray

$gpuChoice = Read-Host "`nSelect GPU backend (1/2/P/M/S)"

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
        Write-Host "[NOTE] Pre-built wheels may not support MTP models (Qwen 3.6). Use option [M] if needed." -ForegroundColor Yellow
    } else {
        Write-Host "`n[WARN] Pre-built install failed. Try option [1] to compile from source." -ForegroundColor Yellow
    }
} elseif ($gpuChoice -match "^[mM]") {
    Write-Host "`n[*] Building llama-cpp-python from LATEST llama.cpp master (MTP/SSM support)..." -ForegroundColor Yellow
    Write-Host "    This is REQUIRED for Qwen 3.6 MTP and other next-gen architectures." -ForegroundColor Gray
    
    $mtpChoice = Read-Host "`n    Which backend do you want to build MTP for? (C = CUDA / V = Vulkan)"
    
    if ($mtpChoice -match "^[cC]") {
        # 1. Dynamically search for ANY installed CUDA version (e.g. v13.2, v12.6)
        $cudaBase = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
        if (Test-Path $cudaBase) {
            $latestCuda = Get-ChildItem $cudaBase -Directory | Sort-Object Name -Descending | Select-Object -First 1
            if ($latestCuda) {
                $cudaPath = Join-Path $latestCuda.FullName "bin"
                if (Test-Path $cudaPath) {
                    $env:Path = "$cudaPath;" + $env:Path
                    $cudaAvailable = $true
                    $env:CUDACXX = Join-Path $cudaPath "nvcc.exe"
                }
            }
        }

        # 2. If it is STILL not available, install via winget
        if (-not $cudaAvailable) {
            Write-Host "`n[!] CUDA Toolkit not found. Auto-installing CUDA 12.6 via winget..." -ForegroundColor Cyan
            winget install Nvidia.CUDA --version 12.6 --accept-package-agreements --accept-source-agreements
            
            Write-Host "    Refreshing environment variables..." -ForegroundColor Gray
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            $fallbackPath = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin"
            if (Test-Path $fallbackPath) { 
                $env:Path = "$fallbackPath;" + $env:Path 
                $env:CUDACXX = Join-Path $fallbackPath "nvcc.exe"
            }
        }
        Write-Host "    -> Compiling with CUDA Toolkit..." -ForegroundColor Cyan
        $env:CMAKE_ARGS = "-DGGML_CUDA=on -DGGML_CUDA_FA_ALL_QUANTS=on"
    } elseif ($mtpChoice -match "^[vV]") {
        if (-not $vulkanAvailable) {
            Write-Host "`n[!] Vulkan SDK not found. Auto-installing via winget..." -ForegroundColor Cyan
            winget install LunarG.VulkanSDK --accept-package-agreements --accept-source-agreements
            
            # Refresh environment variables
            Write-Host "    Refreshing environment variables..." -ForegroundColor Gray
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            $env:VULKAN_SDK = [System.Environment]::GetEnvironmentVariable("VULKAN_SDK","Machine")
        }
        Write-Host "    -> Compiling with Vulkan SDK..." -ForegroundColor Cyan
        $env:CMAKE_ARGS = "-DGGML_VULKAN=on"
    } else {
        Write-Host "    -> Compiling CPU-only..." -ForegroundColor Yellow
        $env:CMAKE_ARGS = ""
    }

    # VS Build Tools check
    $vsPath = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vs_installer.exe"
    if (!(Test-Path $vsPath)) {
        Write-Host "[!] VS Build Tools not found. Attempting to install via winget..."
        winget install Microsoft.VisualStudio.2022.BuildTools --force --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools" --accept-package-agreements --accept-source-agreements
    }

    # Install Ninja to bypass MSVC CUDA integration issues
    Write-Host "    -> Installing Ninja build system..." -ForegroundColor Gray
    .\.venv\Scripts\python.exe -m pip install ninja

    # Uninstall existing version first
    .\.venv\Scripts\python.exe -m pip uninstall llama-cpp-python -y 2>$null

    # Build from source against latest llama.cpp inside MSVC environment
    Write-Host "    -> Initializing MSVC Environment..." -ForegroundColor Gray
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsInstallPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    $vcvars = "$vsInstallPath\VC\Auxiliary\Build\vcvars64.bat"
    
    $env:FORCE_CMAKE = "1"
    $env:CMAKE_GENERATOR = "Ninja"
    
    if (Test-Path $vcvars) {
        Write-Host "    -> Launching Ninja build process..." -ForegroundColor Cyan
        cmd.exe /c "`"$vcvars`" && .\.venv\Scripts\python.exe -m pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir --no-binary llama-cpp-python"
    } else {
        Write-Host "[!] Could not find vcvars64.bat at $vcvars. Attempting direct build..." -ForegroundColor Yellow
        .\.venv\Scripts\python.exe -m pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir --no-binary llama-cpp-python
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n[SUCCESS] Latest llama-cpp-python built with MTP support!" -ForegroundColor Green
    } else {
        Write-Host "`n[WARN] Build failed. You may still need to restart your terminal if the CUDA/Vulkan install didn't fully register." -ForegroundColor Yellow
        Write-Host "       If it fails again after a restart, try: pip install llama-cpp-python --pre --force-reinstall" -ForegroundColor Gray
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

