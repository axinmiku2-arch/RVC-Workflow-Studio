"""One-shot inference process: releases GPU memory after every preview."""
import os
import sys
from pathlib import Path
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("index")
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("semitones", type=int)
    parser.add_argument("index_rate", type=float)
    parser.add_argument("protect", type=float)
    args = parser.parse_args()
    # Config parses sys.argv; give it only its own flags.
    sys.argv = [sys.argv[0], "--noautoopen"]
    os.environ["RVC_CUDA_GRAPH"] = "0"
    os.environ["weight_root"] = str(Path(args.model).parent)
    from configs.config import Config
    from infer.vc.modules import VC
    import soundfile as sf
    vc = VC(Config())
    vc.get_vc(Path(args.model).name)
    status, result = vc.vc_single(0, args.source, args.semitones, "rmvpe", args.index, args.index_rate, 0, 1, args.protect)
    if result is None or result[1] is None:
        raise RuntimeError(status)
    sf.write(args.output, result[1], result[0], subtype="PCM_16")
    print("独立干声试听转换完成。", flush=True)


if __name__ == "__main__":
    main()
