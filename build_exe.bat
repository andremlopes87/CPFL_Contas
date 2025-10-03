@echo off
setlocal enabledelayedexpansion

REM ---------------------------------------------------------------------------
REM Garante que estamos no diretorio do script, independente de como foi chamado
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul 2>&1

REM ---------------------------------------------------------------------------
REM Escolhe o interpretador Python 3.11 disponivel (py.exe ou python.exe)
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3.11"
if not defined PY_CMD (
    where python >nul 2>&1 && set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [ERRO] Python 3.11 nao encontrado no PATH. Instale o Python 3.11 e tente novamente.
    goto :error
)

REM ---------------------------------------------------------------------------
REM Cria o ambiente virtual se necessario
if not exist .venv (
    echo [INFO] Criando ambiente virtual com %PY_CMD%
    %PY_CMD% -m venv .venv || goto :error
)

set "VENV_PY=.\\.venv\\Scripts\\python.exe"
if not exist "%VENV_PY%" (
    echo [ERRO] Ambiente virtual nao foi criado corretamente.
    goto :error
)

call .\\.venv\\Scripts\\activate.bat || goto :error

REM ---------------------------------------------------------------------------
REM Garante que estamos rodando com Python >= 3.11
for /f "delims=. tokens=1-3" %%a in ('python -c "import sys; print(*sys.version_info[:3])"') do (
    if %%a lss 3 goto :py_version_error
    if %%a==3 if %%b lss 11 goto :py_version_error
)

REM ---------------------------------------------------------------------------
REM Instala dependencias
echo [INFO] Atualizando ferramentas base
python -m pip install --upgrade pip wheel setuptools || goto :error
python -m pip install -r requirements.txt || goto :error
python -m pip install pyinstaller || goto :error

REM ---------------------------------------------------------------------------
REM Limpa artefatos anteriores
echo [INFO] Limpando artefatos anteriores
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist CPFLFetcher.spec del CPFLFetcher.spec

REM ---------------------------------------------------------------------------
REM Executa o PyInstaller com todos os dados necessarios
echo [INFO] Gerando executavel CPFLFetcher.exe
python -m PyInstaller --noconfirm --clean --onefile --name CPFLFetcher ^
    --add-data "config.example.json;." ^
    --add-data "data\\mocks;data\\mocks" ^
    --collect-data certifi ^
    --collect-data pandas ^
    --collect-data numpy ^
    --collect-data charset_normalizer ^
    --collect-submodules pandas ^
    --collect-submodules numpy ^
    --collect-submodules dateutil ^
    --hidden-import dateutil.parser ^
    --hidden-import dateutil.tz ^
    main.py || goto :error

if exist dist\\CPFLFetcher.exe (
    echo.
    echo [SUCESSO] Arquivo criado em dist\\CPFLFetcher.exe
    popd >nul 2>&1
    endlocal
    exit /b 0
) else (
    echo [ERRO] Nao foi possivel localizar dist\\CPFLFetcher.exe
    goto :error
)

:py_version_error
echo [ERRO] O Python ativo nao e 3.11+. Ajuste o PATH ou use "py -3.11".
goto :error

:error
echo.
echo [FALHA] Ocorreu um erro durante a geracao do executavel.
echo         Consulte o log acima para detalhes.
popd >nul 2>&1
endlocal & exit /b 1
