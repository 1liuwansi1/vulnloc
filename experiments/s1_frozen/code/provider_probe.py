"""One real, tiny provider turn; infrastructure capability evidence only."""

import json, os
from pathlib import Path
from core import ROOT, read_config, canonical
from runner import Spending, append
from methods import Session
from transport import PiRpcLLM

out = Path(os.environ["RESULTS_DIR"])
cfg = read_config(ROOT / "06_experiments/c06_repair/development.json")
spend = Spending(out, cfg, False)
spend.unit = {"purpose": "infrastructure-provider-probe"}
with (out / "events.jsonl").open("x") as ev:
    llm = PiRpcLLM(
        "Reply with only JSON; do not use tools.",
        provider=cfg["provider"],
        model=cfg["model"],
        thinking=cfg["thinking"],
        event_log=ev,
        pi_bin=cfg["pi_bin"],
        turn_timeout=120,
    )
    session = Session(llm, spend)
    try:
        text = session.ask('Return exactly {"ready":true}.')
        obj = json.loads(text)
        if obj != {"ready": True}:
            raise RuntimeError("Probe response mismatch")
        (out / "probe.json").write_text(
            canonical(
                {
                    "evidence": "NOT_RESEARCH_DATA",
                    "response": session.calls[0]["response"],
                    "reported_cost_usd": spend.total,
                }
            )
        )
        print(
            canonical(
                {
                    "ready": True,
                    "reported_cost_usd": spend.total,
                    "observed": session.calls[0]["response"].get("observed"),
                }
            )
        )
    finally:
        llm.close()
        if Path(llm.stderr_path).exists():
            (out / "pi_stderr.log").write_bytes(Path(llm.stderr_path).read_bytes())
