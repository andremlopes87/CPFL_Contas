# CPFL Fetcher (Windows)

Aplicativo em Python empacotado em um executável único (`CPFLFetcher.exe`) para coletar faturas da CPFL Energia usando exclusivamente as chamadas HTTP oficiais da SPA. O fluxo cobre autenticação automática, fallback via bookmarklet, download opcional de PDFs e exportação consolidada em CSV.

## Passo a passo rápido

1. Execute `build_exe.bat` em um prompt do Windows com Python 3.11 instalado. O script cria `dist\CPFLFetcher.exe`.
2. Copie `CPFLFetcher.exe` para a máquina/usuário que fará a coleta e execute com duplo clique.
3. No primeiro uso, informe pelo console os dados solicitados (descrição da UC, preferências, `key`, tokens e payload). O app grava tudo automaticamente em `%APPDATA%\CPFLFetcher\config.json`.
4. Rode novamente o executável (ou continue após preencher os dados) para coletar faturas, gerar `out\faturas.csv` e, se habilitado, baixar PDFs.

## Principais recursos

* **Onboarding guiado** – Na primeira execução o app cria `%APPDATA%\CPFLFetcher\config.json` a partir do template incluso e solicita pelo console tanto as preferências básicas quanto `key`, tokens e payload criptografado.
* **Autenticação resiliente** – Valida tokens em `/user/roles`, tenta renovar via `/token` e, em último caso, habilita o servidor local `http://127.0.0.1:8765/push` para receber o token/key pelo bookmarklet (1 clique).
* **Coleta completa** – Realiza o handshake `/user/validar-integracao`, consulta `/historico-contas/contas-quitadas` e `/historico-contas/validar-situacao`, salvando todos os JSONs e consolidando o histórico em CSV (UTF-8 com BOM) ordenado por UC/vencimento.
* **PDF opcional** – Quando a API retorna URLs válidas, baixa os arquivos para `out/downloads/<uc>/` usando os mesmos headers da sessão autenticada.
* **Ferramentas para testes** – Inclui mocks e comandos `dry-run`/`inspect-har` para validar parsing e descobrir endpoints sem acesso direto ao portal.

## Primeira execução no Windows

1. Copie `CPFLFetcher.exe` para uma pasta de sua preferência.
2. Execute o arquivo (duplo clique). O aplicativo exibirá perguntas básicas:
   * Confirme/edite a descrição das UCs existentes no template.
   * Escolha se deseja baixar PDFs automaticamente.
   * Informe, se quiser, o período padrão (`AAAA-MM`) a ser filtrado.
3. Cole no console os dados da UC quando solicitado:
   * `key` da URL `#/integracao-agd?key=...`.
   * `access_token` e `refresh_token` (se disponíveis) – deixe em branco para capturar depois com o bookmarklet.
   * Campos do payload criptografado (`Instalacao`, `ContaContrato`, `ParceiroNegocio`, etc.).
4. O arquivo de configuração é salvo automaticamente em `%APPDATA%\CPFLFetcher\config.json`. Rode o executável para iniciar a coleta real.
   * Sempre que algum campo essencial estiver ausente, o app voltará a solicitar no console.

As saídas (`out/`) ficam na mesma pasta do `config.json`, garantindo que o executável possa ser movido sem perder histórico.

## Fluxo de autenticação e bookmarklet

1. O app testa o token atual com `GET /user/roles?clientId=agencia-virtual-cpfl-web`.
2. Se 401/403, tenta `POST /token` com `grant_type=refresh_token`.
3. Persistência: tokens e `expires_at` são gravados no `config.json` sempre que renovados.
4. Caso o refresh falhe, o app:
   * Sobe um servidor local em `http://127.0.0.1:8765/push`.
   * Exibe o bookmarklet no console (copie para um favorito no navegador logado).
   * Abre automaticamente a página `Débitos e 2ª via / Histórico`.
   * Ao clicar no bookmarklet, o navegador envia `access_token`, `refresh_token`, `expires_at` e `key` para o app, que prossegue com a coleta.

Os logs mascaram tokens (apenas 6 primeiros/últimos caracteres) para facilitar depuração sem comprometer a segurança.

## Saídas geradas

```
%APPDATA%\CPFLFetcher\
├── config.json
└── out\
    ├── faturas.csv
    ├── downloads\<uc>\*.pdf  (quando habilitado)
    └── json\<uc>\20240130T102030_validar_integracao.json
```

O CSV contém as colunas principais (`_uc`, `_tipo`, `mes_referencia`, `vencimento`, `valor`, `consumo_kwh`, `conta_id`, `status`, `instalacao_real`, `documento`) e quaisquer `extra_*` detectados no payload, além de `pdf_hint` com as URLs capturadas.

Se nenhum dado for retornado, o aplicativo orienta a verificar o payload/handshake salvo nos JSONs.

## Execução avançada (linha de comando)

Mesmo com o `.exe`, os módulos Python continuam disponíveis:

```bash
python -m cpfl.cli run --config %APPDATA%\CPFLFetcher\config.json
python -m cpfl.cli dry-run --samples data/mocks --output out_mock
python -m cpfl.cli inspect-har data/mocks/cpfl.har
```

Use `python -m cpfl.cli bookmarklet` para apenas exibir o snippet do bookmarklet manualmente.

## Testes offline (dry-run)

`python -m cpfl.cli dry-run` gera um `faturas.csv` sintético utilizando os JSONs em `data/mocks/`. Isso valida o parser sem precisar de credenciais reais. Os testes unitários (`pytest`) cobrem esse comportamento.

## Construindo o executável (.exe)

1. Instale Python 3.11 no Windows.
2. Execute o script `build_exe.bat` disponibilizado no repositório:

   ```bat
   build_exe.bat
   ```

   O script cria um ambiente virtual, instala dependências (incluindo PyInstaller) e gera `dist\CPFLFetcher.exe` com os mocks e templates incorporados (`config.example.json`, `data/mocks`).

## Desenvolvimento e testes

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pytest
python -m cpfl.cli dry-run
```

Dependências principais: `requests`, `pandas`, `python-dateutil`, `urllib3` e `pytest` (para testes).

## Segurança e boas práticas

* Mantenha `config.json` fora de repositórios públicos.
* Execute o bookmarklet apenas em uma aba autenticada e confiável.
* Ajuste periodicamente o payload caso a CPFL altere o formato retornado.

## Licença

Uso interno. Adeque conforme a política de compliance da sua organização.
