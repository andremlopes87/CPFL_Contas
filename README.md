# CPFL Energia - Coletor HTTP sem navegador

Ferramenta completa em Python para extrair histórico de faturas da CPFL Energia utilizando as mesmas chamadas HTTP da SPA oficial. O coletor roda 100% sem automação de navegador, suporta múltiplas UCs, consolida resultados em CSV, persiste os JSONs brutos e, opcionalmente, baixa os PDFs quando a API expõe os links.

## Visão geral

* **Autonomia de autenticação** – Usa `access_token` existente, tenta `refresh_token` e, se necessário, dispara um servidor local para receber o token/key via bookmarklet (1 clique).
* **Integração completa** – Executa `/user/roles`, handshake `/user/validar-integracao`, consulta `/historico-contas/contas-quitadas` e `/historico-contas/validar-situacao` para cada UC.
* **Parsing resiliente** – Normaliza campos mesmo quando a API muda nomes (`Itens`, `Lista`, `Resultado` etc.). Extrai `mes_referencia`, `vencimento`, `valor`, `consumo_kwh`, `conta_id`, `status`, `instalacao_real`, `documento` e mantém extras.
* **Saídas organizadas** – Salva JSONs em `out/json/<uc>/TIMESTAMP_*.json`, CSV único em `out/faturas.csv` e PDFs opcionais em `out/downloads/`.
* **Testes offline** – Inclui mocks e `python -m cpfl.cli dry-run` para validar o parser sem credenciais reais.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuração (`config.json`)

1. Copie o template:
   ```bash
   cp config.example.json config.json
   ```
2. Preencha os campos principais:
   ```json
   {
     "global": {
       "base_url": "https://servicosonline.cpfl.com.br/agencia-webapi/api",
       "client_id": "agencia-virtual-cpfl-web",
       "download_pdfs": false,
       "output_dir": "out"
     },
     "unidades_consumidoras": [
       {
         "id": "uc_casa",
         "descricao": "Residencial",
         "key": "HASH_DA_URL",
         "access_token": "JWT",
         "refresh_token": "JWT_REFRESH",
         "expires_at": "2024-09-01T12:00:00Z",
         "payload": {
           "Instalacao": "CRIPTO...",
           "ContaContrato": "CRIPTO...",
           "ParceiroNegocio": "CRIPTO..."
         }
       }
     ]
   }
   ```
   * `payload` contém o corpo usado pelos endpoints (`Instalacao`, `ContaContrato`, `ParceiroNegocio` etc.). É possível apontar para um arquivo externo com `"payload_file"`/`"payload_key"` quando os dados estiverem em `inst_cache.json`.
   * `key` vem da URL `#/integracao-agd?key=...`.
   * Tokens são atualizados automaticamente no próprio `config.json` após refresh ou bookmarklet.

## Execução principal

```bash
python -m cpfl.cli run
```

Comportamento esperado:

1. **Validação do token** – Chama `/user/roles`; se 401/403, tenta refresh (`/token`).
2. **Bookmarklet automático** – Caso o refresh falhe, abre o servidor local (porta 8765 por padrão) e exibe o snippet do bookmarklet. Execute-o em uma aba já logada na CPFL para enviar `access_token`, `refresh_token` e `key` automaticamente.
3. **Coleta por UC** – Realiza handshake e baixa os dois JSONs (`contas-quitadas` e `validar-situacao`), salvando cópias em `out/json/<uc>/` com carimbo de tempo.
4. **Parsing e CSV** – Consolida todas as faturas em `out/faturas.csv`, ordenadas por UC, vencimento e tipo (`quitada`/`aberta`).
5. **PDF opcional** – Se `download_pdfs` estiver ativo (via config ou `--download-pdfs`), tenta baixar cada link detectado, salvando em `out/downloads/<uc>/`.

Parâmetros úteis:

* `--download-pdfs / --no-download-pdfs` – Sobrescreve o flag do config.
* `--period-start AAAA-MM` e `--period-end AAAA-MM` – Filtra as linhas do CSV por mês de referência.
* `--bookmarklet-timeout` – Tempo em segundos aguardando o envio do bookmarklet (default 180s).

## Bookmarklet

Para obter tokens manualmente (quando o refresh não estiver disponível), execute:

```bash
python -m cpfl.cli bookmarklet
```

Cole o snippet exibido como bookmarklet no navegador logado e clique uma única vez. O coletor receberá automaticamente `access_token`, `refresh_token`, `expires_at` e `key`, gravando-os em `config.json` e retomando o fluxo.

## Testes e validação offline

* `python -m cpfl.cli dry-run` – Usa os mocks em `data/mocks/` para gerar um CSV fictício e validar o parser/localização de campos.
* `pytest` – Executa os testes unitários do parser e cenários de dry-run.

## Inspeção de HAR

Caso possua um `cpfl.har` (exportado do DevTools), rode:

```bash
python -m cpfl.cli inspect-har data/mocks/cpfl.har
```

O comando lista endpoints da API encontrados e cabeçalhos relevantes para ajustar configurações avançadas.

## Estrutura de saída

```
out/
├── faturas.csv
├── downloads/
│   └── <uc>/...
└── json/
    └── <uc>/20240130T102030_contas_quitadas.json
```

Cada linha do CSV possui:

| Campo | Descrição |
|-------|-----------|
| `_uc` | Slug da UC (derivado de `descricao`/`id`). |
| `_tipo` | `quitada` ou `aberta`. |
| `mes_referencia` | Mês normalizado `AAAA-MM` quando informado. |
| `vencimento` | Data ISO `AAAA-MM-DD` quando presente. |
| `valor` | Valor monetário com duas casas decimais. |
| `consumo_kwh` | Consumo numérico, sem unidades. |
| `conta_id` | Identificador da fatura quando disponível. |
| `status` | Texto do status retornado pela API. |
| `instalacao_real`/`documento` | Extras se o payload trouxer esses campos. |
| `extra_*` | Outros metadados relevantes (ex.: `extra_numerocliente`). |
| `pdf_hint` | URLs relativas/absolutas usadas para baixar PDFs. |

## Requisitos

* Python 3.10+
* Bibliotecas listadas em `requirements.txt` (`requests`, `python-dateutil`, `pytest` para testes).

## Boas práticas

* Mantenha `config.json` fora do controle de versão.
* Atualize os payloads sempre que a CPFL alterar o formato; os testes com mocks ajudam a validar rapidamente.
* Evite rodar o bookmarklet em ambientes não confiáveis – os tokens são sensíveis.

## Licença

Uso interno. Ajuste conforme sua política de compliance.
