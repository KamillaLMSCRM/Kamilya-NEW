# Isolated ASUS guide narration

Owner authorized remote ASUS inspection and careful TTS installation on 2026-11-13.
This is an offline media-production tool, **not an LMS runtime dependency**.

## Verified host and isolation

- Existing pinned SSH alias `gx10-4`: `gx10-4@10.66.66.7`, hostname `gx10-a721`.
  Use the existing SSH configuration, BatchMode, IdentitiesOnly and strict host-key
  checks. Never copy key contents into a packet, log or model request.
- Task prefix: `/home/gx10-4/.local/share/kamilya-guide-tts-20261113`, user-owned.
- Python: `<prefix>/venv/bin/python`; `qwen-tts==0.1.1`, official ARM64 CPU wheels
  `torch==2.11.0+cpu` and `torchaudio==2.11.0+cpu`, dependency check passed.
  This was the newest matching official CPU wheel pair found for Python 3.12
  ARM64; newer Torch-only wheels do not establish a compatible Torchaudio pair.
- Model: `<prefix>/model`, `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, immutable revision
  `5d83992436eae1d760afd27aff78a71d676296fc`. Public Apache-2.0 safetensors;
  no provider key, paid API, remote Python code, daemon or public listener.
- Fresh venv/cache/model only. No global Python, GPU allocation, existing model
  server configuration, containers, volumes, network or startup configuration changed.
- Protect existing `vllm_node`, `ai-lms-db`, `embedding-server`: compare exact IDs,
  image IDs, started-at, restart count and running state with the saved baseline.
  Pre-existing restart counts are not evidence of this task causing a restart.

## Invocation boundary

Use a uniquely named task-owned user scope, with `MemoryMax=10G`,
`MemorySwapMax=0`, `CPUQuota=400%`, `TasksMax=256`, followed by
`/usr/bin/nice -n 10 <prefix>/venv/bin/python <reviewed-script>`.
`Nice=` is not a supported scope property: the rejected first launch is retained
in evidence; it did not install packages or change existing services.

Set request-process-only `CUDA_VISIBLE_DEVICES=''`, `OMP_NUM_THREADS=4`,
`OPENBLAS_NUM_THREADS=4`, `MKL_NUM_THREADS=4`, `HF_HUB_OFFLINE=1`, and
`TOKENIZERS_PARALLELISM=false`. Load with CPU, float32 and SDPA. Reuse one
loaded model and voice prompt for sequential clips; do not reload for every cue.
During a live scope, read back its actual memory/CPU limits. After scope exit,
systemd returns default/inactive properties; these are not live-limit evidence.

The retained `synthesis.py` is a one-shot smoke, not an idempotent batch renderer.
Do not replay its launcher or overwrite its original result. Batch tooling needs
per-text/model/reference/config hashes and verified completed-clip resume.

## Reference voice and verified sample

Reference is the existing **synthetic male Qwen voice** from the previously
published `01-sources.mp4`, first spoken cue (0.125–8.125 seconds), with its
matching published transcript. No human voice recording was uploaded or cloned.
Files `<prefix>/qwen-male-reference.wav` and `tts-sample-text.json` are task-owned.

Actual smoke: 4.16 seconds of 24 kHz audio in 21.889 seconds including 3.543
seconds loading; real-time factor 4.410 after loading; peak RSS 7,222,696 KiB;
CPU only. This is one sample, not a throughput guarantee for the full guide.

Independent CPU Whisper-base transcription preserved every spoken word, allowing
punctuation and ё/е normalization. This establishes sample text fidelity, not a
human listening verdict or full-guide acceptance. Source and result are retained
privately under `.release-evidence/guide-refresh-20261113/`.

Optional ASR is isolated in `<prefix>/asr-venv`, `faster-whisper==1.2.1` with
`Systran/faster-whisper-base` revision
`ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66` in `<prefix>/asr-model`.
PyAV 19 does not accept the `metadata_errors` parameter used by this Whisper
version. The failed check is preserved. Verified workaround for these synthetic
WAVs: ffmpeg converts to 16 kHz mono signed PCM16; stdlib `wave` verifies shape,
NumPy converts to float32 divided by 32768, and `transcribe` receives the array.
No product decoder or globally installed dependency was changed.

## Stop and recovery

Stop only the exact task-owned scope after identity/readback. Do not stop an ASUS
model server, Docker container, another user's OpenCode/Hermes client or an
unrelated scope. Retain task files and failed receipts until media acceptance.
Removal of this prefix is not part of the installation and has not been done.
No packages or services require reconfiguration to restore the original host.

At the later 2026-11-13 check, both `10.66.66.7` and `10.66.66.20` timed out
on SSH and their known API ports while the workstation WireGuard interface and
route remained up. The sample and its ASR result had already been copied locally.
Final remote readback is UNKNOWN; installation success does not establish current
reachability. Do not reinstall or restart a model/container/VPN to infer recovery;
first reobserve the existing route and exact saved job/process state.

Official sources: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS),
[pinned model](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base/tree/5d83992436eae1d760afd27aff78a71d676296fc).

## Later same-day verified recovery and full narration

The existing route subsequently recovered without this task restarting VPN, host,
model server or containers. `tts-after-network-recovery-readback.json` confirms the
three protected containers retained their exact IDs/images/starts/restarts/running
states. The earlier UNKNOWN observation remains historical evidence.

Batch `narration-r5` completed 33 atomic clips: 297.04 seconds speech in 1190.014
seconds CPU. All WAVs and the receipt were copied to the task evidence folder and
independently SHA256-verified. This is synthesis/custody evidence, not full guide
visual or listening acceptance. Preserve the original complete receipt; resume
only changed source text under identical model/reference/config hashes. Final
screenshots and media approval remain separate release gates.

## Changed-cue resume and final host readback

Later R6/R7 source corrections reused all unchanged clips by exact configuration,
text and WAV hashes. R7 synthesized only `m06-s03-import-preview` (8.56 seconds),
reused 32 clips byte-for-byte, and preserved the prior complete batch separately
as `<prefix>/narration-r6-complete`. All 33 final WAV hashes were verified after
copy to the workstation. Base ASR preserved the material import meaning, including
that a proposal does not apply the file; a 0.1429 word-error rate contains minor
agreement/recognition differences and is not a human-listening claim.

Post-R7 readback: TTS and ASR scopes inactive; the three protected containers
retained exact IDs/images/start times/restart counts/running states. Host free
space 58,929,659,904 bytes; MemAvailable 37,299,855,360 bytes at that observation.
Do not infer a live capacity guarantee from this historical sample. The guide
still requires separate screenshot/media/browser acceptance before publication.

## Completed publication snapshot

Frontend0.11.109/91f359cd36ca2ea9a1cce6bd2e53e068003bb612 published13November2026 after local, DEV and live production guide/help acceptance. Eight videos/33steps; actual release evidence and minor initial-poster advisory are in CODEX_HANDOFF and TEST_RUN_LEDGER. TTS remains a one-shot offline production tool; no runtime listener/daemon was installed. Task-only workstation proxies were stopped; existing ASUS containers remain unchanged.

## Frame-aligned step navigation, verified 2026-11-14

Frontend110 derives per-step seek timestamps from the actual encoded chapter MP4 via encoded_step_starts, rather than cumulative WAV durations.30fps quantization/AAC priming can place a nominal audio boundary before the new video scene. Exclude regular keyframes before nominal, require a unique bounded clip boundary and round up to button milliseconds. If mapping is missing/ambiguous, fail generation rather than silently use the old time or the initial poster. Keep accepted media bytes and native paused seeking.

Verify the real displayed frame before any Play; currentTime alone is insufficient. A paused frame requires readyState>=2, while4describes future buffering. Pixel regression compares decoded source content independently, then tests nativePlay separately. Guide110 LOCAL/DEV/production33steps/8chapters accepted; no new TTS batch or cloud runtime dependency was introduced. Earlier109poster advisory was a preliminary diagnosis corrected by this actual encoded-clock evidence.
