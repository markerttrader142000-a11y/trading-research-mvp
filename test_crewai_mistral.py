"""Script de teste mínimo — corre na máquina do user via terminal."""
import sys, os
sys.path.insert(0, os.path.expanduser("~/Desktop/trading_research_mvp_ctrader_v7"))

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/Desktop/trading_research_mvp_ctrader_v7/.env"))

from agents.llm_factory import make_llm

print("1. A criar LLM object...")
llm = make_llm("mistral")
print(f"   LLM: {llm}")
print(f"   Type: {type(llm)}")

if llm is None:
    print("ERRO: make_llm retornou None — MISTRAL_API_KEY pode não estar definida")
    sys.exit(1)

print("\n2. A testar invocação directa do LLM...")
try:
    result = llm.call([{"role": "user", "content": "Reply with exactly: OK"}])
    print(f"   Result type: {type(result)}")
    print(f"   Result: {result}")
    print("\nSUCESSO: LLM invocado com sucesso!")
except Exception as e:
    print(f"ERRO na invocação: {e}")
    import traceback; traceback.print_exc()
