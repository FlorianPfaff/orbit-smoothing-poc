"""Run an existing frozen benchmark once and always attempt its inclusive report.

This controller adds no preparation, retry, checkpoint repair or source update.
SIGINT/SIGTERM unwind the existing worker cleanup before report generation.
"""
from dataclasses import asdict
from pathlib import Path
import signal
import shutil
import sys
import time
import traceback
import uuid

from .config import load_config
from . import protocol as protocol
from .report import create_report


class CampaignInterrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(f"Campaign interrupted by signal {signum}")


def run_to_report(config_path, startup_receipt, *, max_attempts=None, project=None):
    """Resume only through the unchanged protocol, retaining one receipt per call."""
    config_path = Path(config_path).resolve()
    startup_receipt = Path(startup_receipt).resolve()
    config = load_config(config_path)
    project = Path(project or protocol.project_root()).resolve()
    root = protocol._root(config, None, project)
    startup = protocol.read_json(startup_receipt)
    configuration = protocol.artifact(config_path)
    if (startup.get("status") != "verified" or startup.get("configuration") != configuration
            or startup.get("execution_context") != asdict(config.execution_context)):
        raise ValueError("Startup runtime verification does not match this configuration")
    if max_attempts is not None and (isinstance(max_attempts, bool) or max_attempts <= 0):
        raise ValueError("max_attempts must be positive")
    controller = root / "controller"
    with protocol.exclusive(controller):
        receipt = controller / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex + ".json")
        started = time.monotonic()
        saved_config = receipt.with_name(receipt.stem + ".config.json")
        saved_startup = receipt.with_name(receipt.stem + ".startup.json")
        startup_identity = protocol.artifact(startup_receipt)
        shutil.copyfile(config_path, saved_config)
        shutil.copyfile(startup_receipt, saved_startup)
        if (protocol.file_hash(saved_config) != configuration["sha256"]
                or protocol.file_hash(saved_startup) != startup_identity["sha256"]):
            raise ValueError("Launch provenance changed while saving its immutable copy")
        record = {"schema_version": 1, "scope": "One launch of the frozen serial benchmark followed by an inclusive report; no automatic attempt retries or source edits",
                  "status": "running", "phase": "initial_report", "started_at": protocol.timestamp(),
                  "configuration": configuration, "configuration_copy": protocol.artifact(saved_config),
                  "startup_receipt": protocol.artifact(saved_startup), "startup_receipt_origin": startup_identity,
                  "controller_source": protocol.artifact(__file__), "max_attempts": max_attempts,
                  "signals": [], "run": None, "report": None,
                  "hard_kill_policy": "An uncatchable kill may leave this receipt running. A later explicit launch first regenerates the inclusive report, then uses the unchanged checkpoint/recovery rules."}
        protocol.write_json(receipt, record)
        exit_code = 1
        handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}

        def interrupted(number, _frame):
            nonlocal exit_code
            record["signals"].append(number)
            if record["phase"] == "final_report":
                record.update(status="interrupted", interrupted_signal=number)
                exit_code = 128 + number
                return
            raise CampaignInterrupted(number)

        for number in handlers:
            signal.signal(number, interrupted)
        try:
            # Also refresh the report before a resume, including after a hard
            # kill left no terminal checkpoint. This never repairs that fit.
            record["initial_report"] = create_report(config, project=project)
            record["phase"] = "run"
            protocol.write_json(receipt, record)
            record["run"] = protocol.run(config, max_attempts=max_attempts, project=project)
            record["status"] = record["run"]["status"]
            exit_code = 1 if record["status"] in ("blocked", "failed") else 0
            if protocol.artifact(config_path) != configuration:
                raise ValueError("Configuration file changed during campaign execution")
        except (CampaignInterrupted, KeyboardInterrupt) as error:
            number = error.signum if isinstance(error, CampaignInterrupted) else signal.SIGINT
            if number not in record["signals"]:
                record["signals"].append(number)
            record.update(status="interrupted", error=str(error), interrupted_signal=number)
            exit_code = 128 + number
        except BaseException as error:
            record.update(status="failed", error=type(error).__name__ + ": " + str(error), traceback=traceback.format_exc())
            exit_code = 1
        finally:
            record["phase"] = "final_report"
            protocol.write_json(receipt, record)
            try:
                record["report"] = create_report(config, project=project)
                record["report_artifacts"] = []
                for key, suffix in (("html", ".report.html"), ("report", ".report.json")):
                    saved = receipt.with_name(receipt.stem + suffix)
                    pending = saved.with_name(saved.name + ".copying")
                    shutil.copyfile(record["report"][key], pending)
                    pending.replace(saved)
                    record["report_artifacts"].append(protocol.artifact(saved))
                if record["status"] == "complete" and record["report"]["status"] != "complete":
                    record["status"] = "partial"
            except BaseException as error:
                record["report_error"] = type(error).__name__ + ": " + str(error)
                record["report_traceback"] = traceback.format_exc()
                if record["status"] != "interrupted":
                    record["status"] = "failed"; exit_code = 1
            finally:
                for number, handler in handlers.items():
                    signal.signal(number, handler)
                record.update(phase="finished", exit_code=exit_code,
                              elapsed_seconds=time.monotonic()-started, finished_at=protocol.timestamp())
                protocol.write_json(receipt, record)
        return {"status": record["status"], "exit_code": exit_code,
                "receipt": protocol.artifact(receipt), "run": record["run"], "report": record["report"],
                **({"error": record["error"]} if "error" in record else {}),
                **({"report_error": record["report_error"]} if "report_error" in record else {})}


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--startup-receipt", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int)
    args = parser.parse_args(argv)
    try:
        result = run_to_report(args.config, args.startup_receipt, max_attempts=args.max_attempts)
    except (OSError, ValueError, RuntimeError) as error:
        result = {"status": "blocked", "exit_code": 1, "error": str(error)}
    print(json.dumps(result, indent=2, allow_nan=False))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
