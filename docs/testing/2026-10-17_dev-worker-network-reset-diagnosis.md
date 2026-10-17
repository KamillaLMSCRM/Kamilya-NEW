# DEV worker startup reset: evidence and remaining boundary

Date: 2026-10-17. Scope: existing Render DEV only. Production not changed.
Status: worker recovers and responds; exact reset sender NOT_LOCALIZED.

## Established facts

1. On accepted DEV021 source7425daea, the worker's first SSH process started
   14:24:42.310828Z and failed14:24:42.701388Z during `connect`, before OpenSSH
   reported TCP establishment. The single existing retry connected14:24:45.763682Z.
2. The same release's API first attempt failed14:22:38.018232Z after TCP connect
   while reading the SSH banner. It had not reached key exchange/authentication.
3. The diagnostic target equals the fixed numeric runtime IPv4 and port22.
   The launcher uses `-F none`, a minimal process environment and explicit trust;
   there is no DNS or ambient SSH proxy/config selection in this path.
4. A simultaneous600-second capture on the destination used all interfaces,
   all IPv4 peers and TCP22 SYN/RST/FIN headers. It captured71 packets, received71
   by filter, dropped0 in the kernel, parsed71, and did not truncate retained events.
5. No new SYN or RST appeared during either first attempt. The same is true with
   each window broadened by0.5seconds on both sides. The successful retries are
   positive controls, correlating exactly with destination SSH authentication:

| Consumer | Retry SYN UTC | Opaque flow | Accepted auth UTC |
|---|---|---|---|
| API | 14:22:39.085765 | 3bf01061408e | 14:22:40.554673 |
| Worker | 14:24:43.780002 | 3043637de5cb | 14:24:45.611679 |

6. Narrow SSH journals have no matching first-attempt authentication/MaxStartups
   refusal. Separate `forward_connect_failed` messages refer to downstream
   forwarding targets and must not be conflated with the SSH transport reset.
7. Earlier read-only host checks found no matching SSH restart, OOM,
   conntrack-full, SYN-flood or link-down class. These are supporting negatives,
   not proof of the upstream sender.
8. Actual DEV021 and DEV022 worker controls use the canonical brokerDB1 shared
   with API, return exactly one pong and ai/documents/maintenance queues. No
   business/model tasks were submitted by these controls.
9. DEV022 worker reproduced a banner-read reset14:44:52.936212Z, then the existing
   single retry connected14:44:55.698409Z. The DEV021 destination capture had
   already ended; do not claim packet correlation for this later sample.

## Interpretation and limits

The failure is before the observed destination-host SSH/authentication path.
No code-level key, authorization, DNS, stage-parser or capture-filter defect has
been established as its cause. The API's completed TCP connect followed by a
banner reset without a corresponding destination-host SYN indicates an earlier
network point, but does not identify that point.

This evidence cannot distinguish client-side networking, Render egress/NAT,
transit infrastructure or the destination provider's edge before the host.
[Render documents outbound routing resets](https://render.com/docs/outbound-connection-resets),
but that mechanism is only a hypothesis for this incident, not a verified cause.
Successful retry proves recovery, not repair of the underlying network cause.

Subsecond provider/host clock skew remains uncertain. The retained71-event TSV
is a complete sanitized transcription of the completed tool output, not a native
pcap. No packet payload, raw SSH diagnostics, credentials or private keys were
published. Independent local review recomputed71 events, the widened empty
windows and both successful flow/auth correlations, accepting this bounded
conclusion only.

Ignored evidence folder: `.release-evidence/cabinet-actions-20261017/`:
`proxy-capture021-summary.json`, `proxy-capture021-events.tsv`,
`proxy-journal021-correlation.json`, capture/journal collectors and exact release
receipts. Capture exit124 is the planned timeout, not a failed worker check.

## Required next evidence, not an authorized mutation

To name the exact reset sender, obtain client/Render-side packet or flow telemetry
for the two failed socket attempts, correlated with destination-edge/transit
telemetry if necessary. Apparent packet source alone may not identify the device
that generated a reset. [Render's Free web services do not expose shell/SSH](https://render.com/docs/ssh);
do not upgrade the tier, add a billable diagnostic service or change security as
a workaround. No provider support message has been sent; external coordination
requires a separate owner decision. A private technical request can use the DEV
service/deployment IDs, UTC windows and sanitized markers, without credentials,
tenant data or employee/course content.

Retain existing bounded recovery and readiness checks. Do not change keys,
trust pins, ports, firewall, retry count/timeouts, model routing, ASUS, billing
or production based on an unproven upstream hypothesis.
