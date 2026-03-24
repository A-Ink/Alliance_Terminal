Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  N7 TERMINAL : AUTOMATED DEPLOYMENT SCRIPT" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 1. Check Python
Write-Host "`n[*] Verifying Python 3.11 Environment..."
if (!(Get-Command "py" -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Python Launcher 'py' not found. Please install Python 3.11 from python.org." -ForegroundColor Red
    Pause
    exit
}

# 2. Virtual Environment
Write-Host "[*] Initializing Virtual Environment..."
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
Write-Host "[*] Installing core dependencies (OpenVINO, UI, etc.)..."
.\.venv\Scripts\pip install -r requirements.txt

# 3. Llama.cpp Interactive Prompt
Write-Host "`n==============================================" -ForegroundColor Yellow
Write-Host "  INTEL SYCL GGUF ENGINE OPTION" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Yellow
Write-Host "To run massive GGUF models natively on your iGPU, the SYCL Llama.cpp Engine is recommended."
Write-Host "This requires the Intel oneAPI Base Toolkit and Microsoft Build Tools."
$response = Read-Host "Would you like to install the Intel SYCL native Engine? (Y/N)"

if ($response -match "^[yY]") {
    Write-Host "`n[*] Installing Intel oneAPI Base Toolkit..." -ForegroundColor Cyan
    winget install --id Intel.OneAPI.BaseToolkit -e --accept-package-agreements --accept-source-agreements
    
    # Locate existing VS installation or install fresh
    $vsPath = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vs_installer.exe"
    Write-Host "`n[*] Installing Microsoft C++ Build Tools..." -ForegroundColor Cyan
    if (Test-Path $vsPath) {
        Write-Host "Visual Studio Installer found. Modifying workloads..."
        Start-Process -FilePath $vsPath -ArgumentList "modify --installPath `"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools`" --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive" -Wait
    } else {
        winget install Microsoft.VisualStudio.2022.BuildTools --force --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools" --accept-package-agreements --accept-source-agreements
    }

    Write-Host "`n[*] Compiling Llama.cpp using Intel DPCPP (SYCL) from bleeding-edge Git repository..." -ForegroundColor Cyan
    
    cmd.exe /c "call `"C:\Program Files (x86)\Intel\oneAPI\setvars.bat`" && call `"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat`" && set CMAKE_ARGS=-DGGML_SYCL=on -DGGML_SYCL_F16=on -DGGML_SYCL_TARGET=INTEL -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icx && `".\.venv\Scripts\python.exe`" -m pip install --upgrade --no-cache-dir --force-reinstall `"git+https://github.com/abetlen/llama-cpp-python.git`""
    
    Write-Host "`n[SUCCESS] SYCL Llama.cpp Engine Compiled!" -ForegroundColor Green
} else {
    Write-Host "`n[*] Skipping SYCL Engine. OpenVINO INT4 models will still function normally." -ForegroundColor Cyan
}

Write-Host "`n==============================================" -ForegroundColor Green
Write-Host "  INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "Run 'python download_model.py' to acquire AI Core models."
Write-Host "Run 'python main.py' to launch the Terminal."
Pause
