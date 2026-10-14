<#
.SYNOPSIS
    Executa o notebook da Entrega 1 de ponta a ponta e salva uma cópia com todas as saídas.

.DESCRIPTION
    Requer o setup_windows.ps1 já executado. Roda o notebook com o Jupyter (sem abrir o navegador),
    usando a GPU NVIDIA, e grava o resultado em notebooks\<nome>_executado.ipynb.
    Os treinos de 30 e 60 épocas levam alguns minutos numa RTX 4060.

.PARAMETER Dir
    Pasta do projeto usada no setup. Padrão: %USERPROFILE%\fiap-fase6

.PARAMETER Notebook
    Nome do notebook em notebooks\ a executar. Padrão: Entrega1.ipynb (use Entrega2.ipynb para a Entrega 2)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File run_windows.ps1
#>
param(
    [string]$Dir = (Join-Path $HOME "fiap-fase6"),
    [string]$Notebook = "Entrega1.ipynb"
)

$ErrorActionPreference = "Stop"  # qualquer erro interrompe o script

$Python = Join-Path $Dir ".venv\Scripts\python.exe"  # Python do ambiente virtual criado pelo setup
if (-not (Test-Path $Python)) { Write-Host "Ambiente não encontrado em $Dir. Rode o setup_windows.ps1 antes." -ForegroundColor Red; exit 1 }

# Notebook a executar, dentro de notebooks\ (padrão: Entrega 1)
$NotebookPath = Join-Path $Dir "notebooks\$Notebook"
if (-not (Test-Path $NotebookPath)) { Write-Host "Notebook não encontrado: $NotebookPath" -ForegroundColor Red; exit 1 }
$NotebookFile = Get-Item $NotebookPath
$Output = $NotebookFile.BaseName + "_executado.ipynb"

Write-Host "Executando $($NotebookFile.Name). O progresso do treino aparece só no fim; acompanhe a GPU com 'nvidia-smi' em outra janela." -ForegroundColor Cyan
$start = Get-Date
# Executa a partir da pasta do notebook, como o Jupyter faria; sem limite de tempo por célula
& $Python -m jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=-1 --output $Output $NotebookFile.FullName
if ($LASTEXITCODE -ne 0) { Write-Host "A execução falhou. A mensagem de erro está acima." -ForegroundColor Red; exit 1 }

$elapsed = (Get-Date) - $start
Write-Host ("`nConcluído em {0:N0} min. Notebook executado:" -f $elapsed.TotalMinutes) -ForegroundColor Green
Write-Host "    $(Join-Path $NotebookFile.DirectoryName $Output)"
Write-Host "Envie esse arquivo para o Guilherme."
