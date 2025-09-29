# CPFL Contas - Pipeline Automático de Extração de Faturas

Pipeline completo em Python para consolidar faturas de energia da CPFL Energia a partir de PDFs depositados em pastas monitoradas. A solução suporta múltiplos clientes, valida e deduplica faturas e gera planilha-mestre, arquivos JSON por fatura e logs de resumo.

## Visão geral da abordagem

1. **Entrada**: PDFs das faturas em pastas por cliente (ex.: sincronizadas manualmente, via download automático ou anexos de e-mail). Cada cliente tem uma pasta de entrada configurável.
2. **Processamento**: Script `python main.py sync` percorre as pastas, lê os PDFs com `pdfplumber`, extrai campos-chave via expressões regulares e normaliza datas/valores.
3. **Validação & Deduplicação**: Regras básicas garantem que valores e datas são válidos. A chave `hash_fatura = MD5(numero_instalacao|mes_referencia|valor_total)` evita duplicidades.
4. **Saída**: 
   - `data/output/cpfl_faturas_master.csv` com uma linha por fatura.
   - `data/output/cpfl_faturas_master.xlsx`.
   - `data/output/json/<hash>.json` para auditoria.
   - Arquivos PDF processados são movidos para `data/archive/`.

Os mocks em `data/mocks/` permitem testar sem credenciais reais.

## Pré-requisitos

- Python 3.10+
- Tesseract OCR opcional (somente se precisar adaptar para PDFs imagem; não é necessário para os mocks incluídos).

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## Configuração

1. Copie os exemplos de configuração:
   ```bash
   cp .env.example .env
   cp config/clients_config.sample.json config/clients_config.json
   ```
2. Edite `config/clients_config.json` preenchendo os dados de cada cliente e a pasta de entrada dos PDFs. Exemplo:
   ```json
   {
     "clientes": [
       {
         "cliente": "Cliente XPTO",
         "numero_instalacao": "1234567",
         "numero_cliente": "7654321",
         "login": "USUARIO_PORTAL",
         "senha": "SENHA_PORTAL",
         "cpf4": "1234",
         "pasta_entrada": "data/incoming/cliente_xpto"
       }
     ]
   }
   ```
   - Deixe `login`, `senha`, `cpf4` vazios se não usar autenticação automática.
   - A pasta informada precisa existir; o script cria subpastas automaticamente ao rodar.
3. Ajuste `.env` se desejar alterar diretórios padrão (`CPFL_INBOX_DIR`, `CPFL_ARCHIVE_DIR`, `CPFL_OUTPUT_DIR`).

## Runner (execução ponta a ponta)

```bash
python main.py sync
```

Logs são exibidos no console. No final é apresentado um resumo com contagem de faturas novas, atualizadas e ignoradas.

## Estrutura dos dados de saída

### Colunas da tabela-mestre (`cpfl_faturas_master.csv`)

| Coluna | Formato | Descrição |
|--------|---------|-----------|
| `cliente` | texto | Nome de referência do cliente. |
| `numero_instalacao` | texto numérico sem máscara | ID da instalação (somente dígitos). |
| `numero_cliente` | texto numérico sem máscara | ID do cliente (somente dígitos). |
| `mes_referencia` | `MM/AAAA` | Mês de competência da fatura. |
| `vencimento` | `DD/MM/AAAA` | Data de vencimento normalizada. |
| `valor_total` | decimal com ponto (`123.45`) | Valor total da fatura. |
| `consumo_kwh` | decimal com ponto | Consumo medido em kWh. |
| `quantidade_faturada` | decimal com ponto | Quantidade faturada (kWh) informada no quadro "Quant. Faturada". |
| `tarifa_com_tributos` | decimal com ponto (5 casas) | Tarifa completa aplicada (R$/kWh) do campo "Tarifa com Tributos". |
| `valor_total_operacao` | decimal com ponto (`123.45`) | Valor total da operação conforme demonstrativo fiscal. |
| `bandeira_tarifaria` | texto | Bandeira tarifária informada. |
| `tusd` | decimal com ponto | Valor de TUSD. |
| `te` | decimal com ponto | Valor de TE. |
| `icms` | decimal com ponto | Valor de ICMS. |
| `pis_cofins` | decimal com ponto | Valor de PIS/COFINS. |
| `endereco_uc` | texto | Endereço da unidade consumidora. |
| `link_pdf` | texto | Link original, se extraído. |
| `hash_fatura` | texto | Hash MD5 `numero_instalacao|mes_referencia|valor_total`. |
| `status_pagamento` | texto | Status informado (Pago/Em aberto etc.). |
| `arquivo_origem` | texto | Caminho do PDF processado (já movido para o arquivo). |

### JSON por fatura

Para cada linha, há um arquivo em `data/output/json/<hash>.json` com os mesmos campos acima.

## Mocks para testes offline

- `data/mocks/cliente_teste/` contém três PDFs fictícios representando faturas CPFL com dados verossímeis, incluindo um modelo atualizado com campos "Conta/Mês", "Quant. Faturada", "Tarifa com Tributos" e "Valor Total da Operação".
- Para testar:
  ```bash
  mkdir -p data/incoming/cliente_teste
  cp data/mocks/cliente_teste/*.pdf data/incoming/cliente_teste/
  python main.py sync
  ```
  O pipeline processa os arquivos fictícios e gera a saída completa, permitindo validação sem credenciais.

## Verificações automáticas

- Validação de duplicidade por `hash_fatura`.
- Checks básicos: `valor_total > 0`, `consumo_kwh >= 0`, datas válidas.
- Log final resume contagem de faturas novas/atualizadas/ignoradas.

## Instruções para produção

1. Obtenha as credenciais de acesso ao portal CPFL ou configure a coleta de PDFs (ex.: download automático via Playwright, app de e-mail, etc.) alimentando as pastas de entrada.
2. Preencha `.env` e `config/clients_config.json` com dados reais (login/senha/cpf4 se for automatizar o download; mantenha-os fora de logs).
3. Programe uma rotina (cron, agendador do sistema, tarefas do Windows) para executar `python main.py sync` conforme desejado.
4. Os relatórios consolidados ficam em `data/output/` e os PDFs processados em `data/archive/`.

## Troubleshooting

| Problema | Possível causa | Solução |
|----------|----------------|---------|
| Campos não extraídos | Layout diferente do PDF | Ajuste regex em `cpfl/pdf_parser.py` ou considere OCR com Tesseract (`pytesseract`) se o PDF for imagem. |
| Datas/valores inválidos | Texto com formatação atípica | Revise o PDF; adicione regex extra ou normalização em `cpfl/utils.py`. |
| Captcha no portal | Bloqueio de automação | Reforçar coleta via e-mail ou baixar manualmente e depositar na pasta. |
| IMAP bloqueado | Segurança do provedor | Habilite senhas de app ou use OAuth. |
| Timeout em download automático | Instabilidade do site | Implementar retries/backoff caso adicione automação de coleta. |

## Segurança e LGPD

- Guarde `.env` e `config/clients_config.json` fora de versionamento (já listados em `.gitignore`).
- Defina permissões de pasta restritas para proteger credenciais.
- Os logs são direcionados ao console; redirecione para arquivo seguro se necessário.
- Não exponha `login`, `senha` ou CPF em prints/logs. O código evita registro desses valores.

## Desenvolvimento futuro

- É possível adicionar módulo Playwright ou Selenium usando as mesmas configurações de cliente.
- Para PDFs escaneados, integre OCR com `pytesseract` e `pdf2image`.

## Licença

Projeto de referência interno para automação de leitura de faturas CPFL.
