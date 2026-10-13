<#
.SYNOPSIS
    Prepara um PC Windows com GPU NVIDIA para executar o notebook da Entrega 1 (Fase 6).

.DESCRIPTION
    Instala (se faltar) Git e Python 3.12, baixa o repositório da entrega, cria um ambiente
    virtual e instala PyTorch com CUDA 12.6, as dependências do YOLOv5 (no commit usado pelo
    notebook) e o Jupyter. No fim, confirma que o PyTorch enxerga a GPU.
    Pode ser executado de novo sem problema: o que já existe é reaproveitado.

.PARAMETER Dir
    Pasta onde o projeto será colocado. Padrão: %USERPROFILE%\fiap-fase6

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup_windows.ps1
#>
param(
    [string]$Dir = (Join-Path $HOME "fiap-fase6")
)

$ErrorActionPreference = "Stop"  # qualquer erro interrompe o script

$RepoUrl = "https://github.com/Avila237/guilherme-kainan-fiap-fase6.git"  # repositório da entrega
$YoloCommit = "f9578796b8a64889aa9e66dc06914d19f40d338e"  # mesmo commit do YOLOv5 fixado no notebook
$TorchVersion = "2.14.1"  # versão do PyTorch testada no projeto
$TorchvisionVersion = "0.29.1"  # torchvision compatível com essa versão
$TorchIndex = "https://download.pytorch.org/whl/cu126"  # builds com CUDA 12.6 (funciona com drivers NVIDIA a partir da série 528)

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }  # título de cada etapa
function Fail($msg) { Write-Host "`nERRO: $msg" -ForegroundColor Red; exit 1 }  # mensagem de erro e saída

function Invoke-Checked {
    # Executa um programa externo e interrompe o script se ele falhar
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "o comando '$Exe $($Arguments -join ' ')' terminou com código $LASTEXITCODE" }
}

function Update-Path {
    # Recarrega o PATH do sistema, para enxergar programas instalados nesta mesma sessão
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Install-IfMissing {
    # Instala um programa pelo winget se o comando não existir
    param([string]$Command, [string]$WingetId, [string]$Name)
    if (Get-Command $Command -ErrorAction SilentlyContinue) { Write-Host "$Name já instalado."; return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Fail "$Name não encontrado e o winget não está disponível. Instale o $Name manualmente e rode o script de novo." }
    Write-Host "Instalando $Name pelo winget (aceite os termos se ele pedir)..."
    Invoke-Checked winget @("install", "--id", $WingetId, "-e", "--source", "winget")
    Update-Path
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) { Fail "$Name foi instalado, mas não aparece no PATH. Feche e abra o PowerShell e rode o script de novo." }
}

Step "1/7 Verificando a GPU NVIDIA"
if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { Fail "nvidia-smi não encontrado. Instale ou atualize o driver da NVIDIA (https://www.nvidia.com/drivers) e rode o script de novo." }
Invoke-Checked nvidia-smi @("--query-gpu=name,driver_version,memory.total", "--format=csv,noheader")

Step "2/7 Git e Python 3.12"
Install-IfMissing -Command "git" -WingetId "Git.Git" -Name "Git"
Install-IfMissing -Command "py" -WingetId "Python.Python.3.12" -Name "Python 3.12"
& py -3.12 --version
if ($LASTEXITCODE -ne 0) {
    # O launcher 'py' existe, mas sem o 3.12: instala a versão certa
    Invoke-Checked winget @("install", "--id", "Python.Python.3.12", "-e", "--source", "winget")
    Update-Path
    Invoke-Checked py @("-3.12", "--version")
}

Step "3/7 Repositório da entrega em $Dir"
if (Test-Path (Join-Path $Dir ".git")) {
    Invoke-Checked git @("-C", $Dir, "pull", "--ff-only")  # já existe: atualiza
} else {
    Invoke-Checked git @("clone", $RepoUrl, $Dir)  # primeira vez: clona
}

Step "4/7 Ambiente virtual Python"
$Venv = Join-Path $Dir ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Python)) { Invoke-Checked py @("-3.12", "-m", "venv", $Venv) }
Invoke-Checked $Python @("-m", "pip", "install", "--upgrade", "pip")

Step "5/7 PyTorch $TorchVersion com CUDA 12.6"
# Instala antes das dependências do YOLOv5, para que elas não troquem pelo PyTorch sem CUDA
Invoke-Checked $Python @("-m", "pip", "install", "torch==$TorchVersion", "torchvision==$TorchvisionVersion", "--index-url", $TorchIndex)

Step "6/7 YOLOv5 (commit fixo) e Jupyter"
# Mesma pasta que o notebook usa ao ser aberto de notebooks\ (BASE = <pasta do notebook>\content)
$YoloDir = Join-Path $Dir "notebooks\content\yolov5"
if (-not (Test-Path (Join-Path $YoloDir ".git"))) { Invoke-Checked git @("clone", "-q", "https://github.com/ultralytics/yolov5", $YoloDir) }
Invoke-Checked git @("-C", $YoloDir, "checkout", "-q", $YoloCommit)
Invoke-Checked $Python @("-m", "pip", "install", "-r", (Join-Path $YoloDir "requirements.txt"))
Invoke-Checked $Python @("-m", "pip", "install", "jupyterlab", "ipykernel", "nbconvert")

Step "7/7 Conferindo se o PyTorch enxerga a GPU"
$check = 'import torch; assert torch.cuda.is_available(), "CUDA indisponivel"; print("PyTorch", torch.__version__, "| CUDA", torch.version.cuda, "|", torch.cuda.get_device_name(0))'
& $Python -c $check
if ($LASTEXITCODE -ne 0) { Fail "o PyTorch não encontrou a GPU. Atualize o driver da NVIDIA e rode o script de novo." }

Write-Host "`nTudo pronto." -ForegroundColor Green
Write-Host "Para treinar e gerar o notebook executado, rode:"
Write-Host "    powershell -ExecutionPolicy Bypass -File `"$(Join-Path $Dir 'scripts\windows\run_windows.ps1')`""
