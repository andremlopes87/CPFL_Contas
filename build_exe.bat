@echo off
setlocal enabledelayedexpansion

REM Garante que estamos no diretorio do script, independente de como foi chamado
pushd "%~dp0" >nul 2>&1

if not exist .venv (
    echo [INFO] Criando ambiente virtual Python 3.11
    py -3.11 -m venv .venv || goto :error
)

call .\.venv\Scripts\activate.bat || goto :error

echo [INFO] Atualizando ferramentas base
python -m pip install --upgrade pip wheel setuptools || goto :error
python -m pip install -r requirements.txt || goto :error
python -m pip install pyinstaller || goto :error

echo [INFO] Limpando artefatos anteriores
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist CPFLFetcher.spec del CPFLFetcher.spec

echo [INFO] Gerando executavel CPFLFetcher.exe
python -m PyInstaller --onefile --name CPFLFetcher ^
    --add-data "config.example.json;." ^
    --add-data "data\mocks;data\mocks" ^
    --collect-data certifi ^
    --collect-data pandas ^
    main.py || goto :error

if exist dist\CPFLFetcher.exe (
    echo.
    echo [SUCESSO] Arquivo criado em dist\CPFLFetcher.exe
    popd >nul 2>&1
    endlocal
    exit /b 0
) else (
    echo [ERRO] Nao foi possivel localizar dist\CPFLFetcher.exe
    goto :error
)

:error
echo.
echo [FALHA] Ocorreu um erro durante a geracao do executavel.
echo         Consulte o log acima para detalhes.
popd >nul 2>&1
endlocal & exit /b 1
