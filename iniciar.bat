@echo off
title Pague Menos PromoRadar - PromoBug Hunter
cd /d "%~dp0"

echo ===================================================
echo  Iniciando Painel Web de PromoBugs Pague Menos...
echo  Acesse: http://localhost:8000
echo ===================================================

python "%~dp0main.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERRO] Ocorreu um problema ao executar o aplicativo.
    echo Verifique se o Python esta instalado e acessivel no seu sistema.
)
pause
