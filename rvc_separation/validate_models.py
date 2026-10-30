"""Real model loading and aligned short inference; writes readiness only on success."""
import argparse
import json
from pathlib import Path
import numpy as np
from .audio import write_float
from .engine import infer
from .models import ROOT, register_validation
from tools.gpu_task_lock import GPUTaskLock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--input")
    args = parser.parse_args()
    directory = ROOT / "logs" / "separation" / "validation"
    directory.mkdir(parents=True, exist_ok=True)
    source = args.input
    if not source:
        time = np.arange(44100 * 2, dtype=np.float32) / 44100
        waveform = .04 * np.sin(2 * np.pi * 220 * time) + .02 * np.sin(2 * np.pi * 440 * time)
        source = write_float(directory / "load-test.wav", np.stack([waveform, waveform]))
    with GPUTaskLock("分离模型兼容验证 · " + args.model):
        arrays, details = infer(args.model, source, lambda event: print(json.dumps(event, ensure_ascii=False), flush=True), allow_unvalidated=True)
        for index, data in enumerate(arrays):
            write_float(directory / f"{args.model}_{index}.wav", data)
        register_validation(args.model, details)
        print(json.dumps(details, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
