@echo off
setlocal enabledelayedexpansion
chcp 65001

:: --- Configuração ---
:: Lista de caminhos separados por ponto e vírgula
set "folders=D:\USER\Toni\Financeiro\Site;D:\USER\Toni\Cursos\LLM\Claude\chat_api_claude;D:\python;D:\USER\Toni\Obsidian"

echo ============================================
echo   Iniciando Sincronização Global do Git
echo ============================================

:: --- Loop de Execução ---
for %%G in ("%folders:;=" "%") do (
    pushd %%~G
    if errorlevel 1 (
        echo [ERRO] Pasta nao encontrada: %%~G
    ) else (
        echo.
        echo ********************************************
        echo * Processando: %%~nxG
        echo * Diretorio:   %%~G
        echo ********************************************
        
        call SyncGit.bat "Auto"
        
        popd
    )
)

echo.
echo ============================================
echo   Sincronização Concluída!
echo ============================================
