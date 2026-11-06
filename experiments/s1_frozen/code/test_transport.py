"""Run prior RPC scenarios against the new transport without touching frozen reports."""

import importlib.util, json, sys
from pathlib import Path
from core import ROOT
import transport
from runner import code_hashes

sys.modules["pi_rpc"] = transport
old = ROOT / "06_experiments/scripts/c06/test_pi_rpc_multiturn.py"
spec = importlib.util.spec_from_file_location("old_rpc_scenarios", old)
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)
results = []
for name in (
    "normal2",
    "normal5",
    "cross_turn",
    "order_swapped",
    "empty_answer",
    "malformed",
    "timeout",
    "delayed",
):
    ok, detail = getattr(suite, "test_" + name)()
    results.append({"case": name, "pass": ok, "detail": detail})
for name in (
    "provider_503",
    "stop_error",
    "error_message",
    "retry_failed",
    "rpc_failed",
    "stream_error",
    "aborted",
    "provider_event",
):
    llm = transport.PiRpcLLM(
        "test",
        pi_bin=[
            sys.executable,
            str(ROOT / "06_experiments/scripts/c06/fake_pi.py"),
            name,
        ],
        turn_timeout=2,
    )
    response = llm.prompt("test")
    llm.close()
    results.append({"case": name, "pass": response["provider_error"]})
llm = transport.PiRpcLLM(
    "test",
    pi_bin=[
        sys.executable,
        str(ROOT / "06_experiments/scripts/c06/fake_pi.py"),
        "complete_empty",
    ],
    turn_timeout=2,
)
response = llm.prompt("test")
llm.close()
results.append(
    {
        "case": "complete_empty_is_billable_model_output",
        "pass": response["cost_available"]
        and response["saw_message_end"]
        and not response["provider_error"],
    }
)
report = {
    "code": code_hashes(),
    "experimental_llm_calls": 0,
    "all_pass": all(r["pass"] for r in results),
    "cases": results,
}
(ROOT / "06_experiments/c06_repair/transport_tests.json").write_text(
    json.dumps(report, indent=2)
)
print(json.dumps(report, indent=2))
sys.exit(0 if report["all_pass"] else 1)
