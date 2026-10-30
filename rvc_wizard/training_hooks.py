"""Opt-in hooks for atomic checkpoint pairs and cooperative epoch-end stopping.

Only enabled for wizard-owned, single-GPU training via RVC_WIZARD_JOB.
The legacy WebUI keeps its original saving and resuming behavior.
"""
import json
import os
import time
from pathlib import Path
import torch
from .common import ROOT, atomic_json, inside, now, read_json

_last_epoch_time = time.monotonic()


def emit(event, **values):
    print("WIZARD_EVENT " + json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


def atomic_torch_save(value, path):
    path = Path(path)
    temp = path.with_name(path.name + ".writing")
    try:
        with temp.open("wb") as stream:
            torch.save(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def module_state(net):
    return (net.module if hasattr(net, "module") else net).state_dict()


def save_pair(directory, hps, net_g, net_d, optim_g, optim_d, epoch):
    directory = Path(directory)
    paths = [directory / f"G_{epoch:09d}.pth", directory / f"D_{epoch:09d}.pth"]
    for net, optimizer, path in zip((net_g, net_d), (optim_g, optim_d), paths):
        atomic_torch_save({"model": module_state(net), "iteration": epoch,
                           "optimizer": optimizer.state_dict(),
                           "learning_rate": hps.train.learning_rate}, path)
    manifest_path = directory / "wizard-checkpoints.json"
    previous = read_json(manifest_path, {"pairs": []})["pairs"]
    pairs = [p for p in previous if p["epoch"] != epoch]
    pairs.append({"epoch": epoch, "g": paths[0].name, "d": paths[1].name, "saved_at": now()})
    pairs.sort(key=lambda p: p["epoch"])
    # Commit the pair before removing older pairs. Orphans never become resumable.
    atomic_json(manifest_path, {"pairs": pairs[-2:]})
    for pair in pairs[:-2]:
        for key in ("g", "d"):
            inside(directory / pair[key], directory).unlink(missing_ok=True)
    emit("checkpoint", epoch=epoch)


def save_voice(hps, net_g, epoch, final=False, root=ROOT):
    from collections import OrderedDict
    name = hps.name if final else f"{hps.name}_e{epoch}"
    path = Path(root) / "assets" / "weights" / (name + ".pth")
    path.parent.mkdir(parents=True, exist_ok=True)
    state = module_state(net_g)
    result = OrderedDict(weight={key: value.detach().cpu().half() for key, value in state.items() if "enc_q" not in key})
    result["config"] = [hps.data.filter_length // 2 + 1, 32, hps.model.inter_channels,
                        hps.model.hidden_channels, hps.model.filter_channels, hps.model.n_heads,
                        hps.model.n_layers, hps.model.kernel_size, hps.model.p_dropout,
                        hps.model.resblock, hps.model.resblock_kernel_sizes,
                        hps.model.resblock_dilation_sizes, hps.model.upsample_rates,
                        hps.model.upsample_initial_channel, hps.model.upsample_kernel_sizes,
                        hps.model.spk_embed_dim, hps.model.gin_channels, hps.data.sampling_rate]
    result.update(info=f"{epoch}epoch", sr=hps.sample_rate, f0=hps.if_f0, version=hps.version)
    atomic_torch_save(result, path)
    emit("voice", epoch=epoch, path=str(path), final=final)


def epoch_end(rank, epoch, hps, nets, optims):
    global _last_epoch_time
    if rank != 0:
        return False
    directory = inside(os.environ["RVC_WIZARD_JOB"], ROOT / "logs")
    if directory != Path(hps.model_dir).resolve():
        raise ValueError("向导训练目录与命令配置不一致。")
    stopped = (directory / "wizard-stop.request").exists()
    final = epoch >= hps.total_epoch
    save = epoch % hps.save_every_epoch == 0 or stopped or final
    if save:
        save_pair(directory, hps, *nets, *optims, epoch)
    if epoch % 50 == 0 or stopped or final:
        save_voice(hps, nets[0], epoch, final=final)
    current = time.monotonic()
    emit("epoch", epoch=epoch, total=hps.total_epoch, seconds=current - _last_epoch_time)
    _last_epoch_time = current
    if stopped or final:
        emit("stopped" if stopped and not final else "completed", epoch=epoch)
        return True
    return False
