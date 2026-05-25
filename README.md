# Trading Research MVP

MVP autónomo para descobrir, filtrar e apresentar oportunidades de trading sem execução real.

## Objetivo

Este projeto testa a lógica mínima da arquitetura:

1. scanner autónomo de mercado;
2. research por candidato;
3. geração de oportunidades;
4. filtro de risco/qualidade;
5. ranking;
6. relatório final;
7. armazenamento em SQLite.

## Segurança

Este MVP não executa ordens, não se liga a brokers e não calcula sizing real. O output é apenas para revisão humana.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Se estiveres em macOS com Python 3.9.6 e os comandos `python`/`pip` não existirem, usa:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## Execução rápida

### Configurar Alpaca localmente

Se quiseres usar a conta paper `trading-bots`, cria um ficheiro `.env` na pasta do projeto:

```bash
cp .env.example .env
```

Edita o `.env` e coloca a tua `ALPACA_API_KEY` e `ALPACA_API_SECRET` locais. O projeto não envia ordens; usa apenas market data para gerar candidatos.

Para testar se as credenciais foram detetadas:

```bash
python3 check_alpaca_config.py
```

### Configurar cTrader Open API localmente

Se tiveres uma app cTrader Open API aprovada, preenche no `.env`:

```env
CTRADER_CLIENT_ID=...
CTRADER_CLIENT_SECRET=...
CTRADER_REDIRECT_URI=http://localhost:8080/callback
CTRADER_SCOPE=accounts
CTRADER_ENV=demo
```

Verifica a configuração:

```bash
python3 check_ctrader_config.py
```

Faz o fluxo OAuth local:

```bash
python3 ctrader_auth.py
```

O script abre o browser, espera pelo redirect em `localhost:8080/callback`, troca o `code` por tokens e guarda em `.ctrader_tokens.json`.

Depois lista as contas associadas ao token:

```bash
python3 check_ctrader_accounts.py
```

Lista símbolos da conta demo:

```bash
python check_ctrader_symbols.py
```

Puxa trendbars/candles dos símbolos em `config.yaml`:

```bash
python check_ctrader_trendbars.py
```

Se `python3` não apontar para o ambiente virtual, usa:

```bash
which python
python check_ctrader_accounts.py
```

ou:

```bash
.venv/bin/python check_ctrader_accounts.py
```

Sem LangGraph, usando o runner simples:

```bash
python3 main.py --runner simple
```

Com LangGraph:

```bash
python3 main.py --runner langgraph
```

## Próxima evolução

Substituir os mocks em `scanner.py`, `research.py` e `opportunity.py` por chamadas reais a Perplexity/API e LLMs, mantendo os mesmos schemas.
# trading-research-mvp
