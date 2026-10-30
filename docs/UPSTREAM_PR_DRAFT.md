# Pull request draft — discussion only

**Do not submit this draft as a PR.** The scope and base require agreement with upstream maintainers first.

## Problem

Users must coordinate multiple training and audio-processing steps. A small, optional improvement to task progress and output reporting could make an existing workflow easier to follow without changing its algorithms.

## Candidate scope

Propose a minimal, independently reviewable progress/status component after maintainer discussion. Keep existing entry points and command-line behavior compatible. Treat our `training_wizard.py` and `rvc_wizard/` implementation as reference material, not a pre-approved patch; the actual changes must be prepared against an agreed upstream revision. A full separation and song workflow is outside this initial PR candidate.

## Compatibility and review

Document UI integration, task ownership, cancellation, path handling and any additional dependencies. Do not package private data or unverified model weights. Retain existing copyright and third-party notices. Confirm expected behavior for existing training and inference before proposing changes.

## Test plan

- Exercise old entry points and parameter defaults on the agreed upstream base.
- Test status and error handling, cancellation, resume where supported, and non-ASCII paths.
- Distinguish simulated subprocess tests from real training and GPU inference; record hardware and dependencies.
- Check licenses and resource provenance for every included component.

Our current independent candidate has passed lightweight local tests but has not established upstream compatibility or completed clean-install and real-model acceptance. No PR has been submitted.
