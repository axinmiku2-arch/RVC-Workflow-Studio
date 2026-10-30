# Feature proposal: guided RVC workflows (draft)

**Status:** discussion draft. No issue or pull request has been submitted.

## Problem and proposed direction

RVC already supports voice conversion, training and source separation. A user preparing a singing voice often needs to navigate several steps and carry paths and parameters between them. A guided interface could make progress, output locations and recovery clearer while leaving the existing interfaces available.

Our independent implementation explores a training wizard and an optional single-inference workflow linking separation, voice conversion, vocal effects and accompaniment mixing. This is a workflow integration proposal, not a claim to have invented separation or voice conversion.

## Implementation currently being evaluated

- `training_wizard.py` and `rvc_wizard/` manage inputs, job state, subprocesses, logs and supported resume paths.
- `separation_wizard.py` and `rvc_separation/` manage model selection, previews, stages and export.
- `rvc_conversion/` orchestrates optional separation, RVC inference and postprocessing; `tools/gpu_task_lock.py` coordinates participating GPU tasks.
- `webui.py` contains integration points. The portable installation and public source candidate have not yet completed clean-install and real-model acceptance.

The observed upstream revision `81eed5e8f68b6bed1789f682fe78cdd324495afc` is only a comparison point: the local installation has no Git history, so its actual upstream base is unknown. These files are not a ready-to-merge diff.

## Questions for maintainers

1. Would an opt-in guided interface or smaller progress/status improvements fit the upstream roadmap?
2. Which existing extension boundary, supported Python and platform versions, and UI conventions should an implementation target?
3. Would maintainers prefer a feature request and a narrowly scoped prototype before a PR?

Potential independent slices include task-state reporting, a training progress interface, and an opt-in separation integration boundary. Each would require a separately reviewed diff against a maintainer-approved base. External models and optional effects introduce independent licensing and dependency questions.

## Validation and limits

The current candidate passed 58 local lightweight checks using existing dependencies, including mocked task execution, and two standalone environment checks. These do not demonstrate end-to-end GPU inference, cross-platform support or upstream compatibility. Before any PR, validate the chosen slice against upstream training and inference, failures, cancellation, paths, privacy and relevant licenses; report real and simulated testing separately.
