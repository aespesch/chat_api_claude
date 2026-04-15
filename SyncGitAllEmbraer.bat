@echo off
setlocal enabledelayedexpansion
chcp 65001

:: --- Configuração ---
:: Lista de caminhos separados por ponto e vírgula
set "folders=C:\DATA\chat_api_claude;C:\DATA\Python;C:\DATA\obsidian"

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
