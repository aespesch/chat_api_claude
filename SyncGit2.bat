@echo off
SETLOCAL

:: 1. Verifica se um argumento (comentário) foi passado
IF "%~1"=="" (
    echo.
    echo [ERRO] Comentario do commit nao encontrado.
    echo.
    echo Uso correto:
    echo syncgit.bat "Sua mensagem de commit aqui"
    echo.
    goto :eof
)

:: Armazena o comentário em uma variável
SET MSG=%~1

echo.
echo === Iniciando Sincronizacao Git ===
echo.

:: 2. Executa a sequência de comandos
echo ^> Executando: git pull...
git pull
IF %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha ao realizar o Pull. Verifique se ha conflitos.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ^> Executando: git add -A...
git add -A

echo.
echo ^> Executando: git commit -m "%MSG%"...
git commit -m "%MSG%"

echo.
echo ^> Executando: git push...
git push

echo.
echo === Sincronizacao concluida com sucesso! ===
echo.

ENDLOCAL