# Contexto do Projecto — Trading Research MVP (para CrewAI Studio)

## O que é este projecto

Pipeline autónomo de **research de trading** — sem execução de ordens, sem dinheiro real.
O sistema:
1. Lê trendbars do cTrader (H1, 4 pares: EURUSD, GBPUSD, USDJPY, XAUUSD)
2. Chama o Mistral AI para research e planos de trade
3. Filtra por risco, faz ranking e gera um relatório JSON

O pipeline já funciona a 100%. O problema pendente é: **os crews CrewAI não estão a usar o Mistral** — estão a cair no mock porque o objeto `LLM` do crewai 1.14.5 retorna `None` no `.choices`.

---

## Arquitectura dos Crews (Layer 3)

```
Crew 1 — Research Synthesizer    crews/research_synthesizer.py
Crew 2 — Setup Validation        crews/setup_validation.py
Crew 3 — Trade Plan              crews/trade_plan.py
Crew 4 — Execution Monitor       crews/execution_monitor.py  (scaffolded, não ligado)
Crew 5 — Post-Trade Review       crews/post_trade_review.py  (scaffolded, não ligado)
```

Os crews são chamados em `graph.py` como **fallback** quando o `llm_direct.py` falha.
O caminho primário actual é: `llm_direct.py` → Mistral via LiteLLM directamente (sem CrewAI).

---

## O problema a resolver

### Ficheiro: `agents/llm_factory.py`

```python
def _make_mistral(model=None):
    from crewai import LLM
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    os.environ["MISTRAL_API_KEY"] = api_key
    return LLM(
        model=f"mistral/{model or 'mistral-small-latest'}",
        temperature=0.2,
        max_tokens=2048,
    )
```

Este código cria um `LLM` object válido mas quando o CrewAI tenta invocá-lo internamente,
o `.choices[0].message.content` retorna `None` — o crew silenciosamente cai no mock.

### O que precisa de ser corrigido

1. **Verificar como o crewai 1.14.5 invoca o LLM** — pode ser via `.call()` em vez de `.completion()`
2. **Passar o `api_key` correctamente** — em crewai 1.x com LiteLLM, a chave pode ter de ir via env var `MISTRAL_API_KEY` (já feito) **e** também via parâmetro directo
3. **Testar com um crew mínimo** antes de ligar tudo

---

## Schemas relevantes (Pydantic v2)

```python
class MarketCandidate(BaseModel):
    asset: str          # ex: "XAUUSD"
    market: str         # "ctrader" | "stocks" | "forex"
    reason: str         # texto com métricas: "0.697% lookback move, 2.030% range"
    metrics: dict       # move_pct, last_bar_move_pct, range_pct, period, scan_score

class ResearchItem(BaseModel):
    asset: str
    market: str
    summary: str
    bullish_factors: list[str]
    bearish_factors: list[str]
    catalysts: list[str]
    source_quality_score: float   # 0.0–1.0

class TradeOpportunity(BaseModel):
    asset: str
    direction: "long" | "short" | "neutral"
    setup_type: str
    thesis: str
    counter_thesis: str
    entry_logic: str
    stop_logic: str
    target_logic: str
    confidence_initial: float     # >= 0.55 para passar o filtro
    requires_human_approval: bool = True   # NUNCA mudar para False
    metrics: dict                 # move_pct, range_pct do scanner
```

---

## Como o Crew 1 está estruturado (Research Synthesizer)

```python
# crews/research_synthesizer.py

def run_research_synthesizer(candidates, config) -> List[ResearchItem]:
    provider = config.get("models", {}).get("research", "mock")
    llm = make_llm(provider)        # <-- retorna None com Mistral (BUG)
    if llm is None:
        return _mock_research(candidates)   # cai aqui sempre
    return _crew_research(candidates, llm)  # nunca chega aqui
```

O `_crew_research()` existe e está implementado mas nunca é chamado.

---

## Agentes disponíveis (agents/__init__.py)

Os agentes são criados em `agents/__init__.py` com funções como:
- `macro_research_analyst(llm)` — Crew 1
- `market_context_analyst(llm)` — Crew 1
- `contrarian_checker(llm)` — Crew 1
- `setup_validator(llm)` — Crew 2
- `probability_scorer(llm)` — Crew 2
- `risk_annotation_agent(llm)` — Crew 2
- `trade_plan_architect(llm)` — Crew 3
- `risk_reward_calculator(llm)` — Crew 3

---

## Versões instaladas

- Python 3.11
- crewai 1.14.5
- litellm >= 1.40
- LLM provider: Mistral AI (MISTRAL_API_KEY no .env)
- Modelo: `mistral/mistral-small-latest`

---

## Tarefa para o CrewAI Studio

**Objectivo**: Fazer `make_llm("mistral")` retornar um objeto que o crewai 1.14.5
consiga usar para invocar o Mistral via LiteLLM sem retornar `None` no output.

**Abordagem sugerida**:
1. No CrewAI Studio, criar um crew de teste mínimo com 1 agente + 1 task
2. Ligar ao Mistral com `MISTRAL_API_KEY`
3. Verificar qual o formato correcto de invocação no crewai 1.14.5
4. Actualizar `agents/llm_factory.py` com o fix

**Restrição imutável**: `requires_human_approval: true` em todos os `TradeOpportunity`.
Nunca ligar execução de ordens.
