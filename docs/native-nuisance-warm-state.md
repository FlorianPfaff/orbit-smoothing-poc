# Experimental native nuisance initialization

This candidate adds initialization values to the corrected native nuisance profiler. It does not change forces, observations, weights, priors, rank policy, stationarity thresholds, line-search acceptance, or covariance eligibility. The original frozen benchmark and its executable remain separate.

Build the candidate in a fresh native source/build tree with the existing numerical flags and `--nuisance-warm-starts`. The option requires `--numerics`; it can follow `--segmented`, `--wide-tangent-candidate` and `--nuisance-performance`. The installer pins every source transformation and rejects partial or changed installations. Re-entry verifies installed extensions before configuration and never reapplies the base header-copying installer. Runtime initialization remains off by default.

The runtime interface is:

| Variable | Contract |
| --- | --- |
| `ORBIT_POC_NUISANCE_WARM_STARTS` | `0` or `1`; missing means `0`. |
| `ORBIT_POC_NUISANCE_WARM_MODE` | `receiver_clock_signal_float_v1` (default when enabled), or diagnostic `receiver_clock_v1`. |
| `ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256` | Required 64-character lowercase SHA256 identifying immutable job inputs, model controls, preprocessing and candidate build; physical trial values are excluded. |
| `ORBIT_POC_NUISANCE_WARM_INPUT` | Optional binary seed from the latest accepted strict profile. Missing means a cold profile. |
| `ORBIT_POC_NUISANCE_WARM_INPUT_SHA256` | Required exactly when an input is supplied; hashes the same complete bytes parsed by native code. |
| `ORBIT_POC_NUISANCE_WARM_OUTPUT` | Required fresh binary destination when enabled. Its companion is `OUTPUT.json`. |

Supplying warm options while the switch is disabled rejects. Export-only enabled calls have no input and preserve the normal cold initialization. Import/export occurs only in the outer native profile step. Forked nuisance line-search, replay and numerical-floor children do not call the importer or exporter.

The full mode carries receiver clocks in native seconds, aggregate signal biases in metres, private accumulated code/TEC bias coordinates in their unchanged native bases, and float ambiguities in cycles. The private code/TEC coordinates and shared bias arrays are assigned directly as one typed tuple. Replaying a generic global apriori difference would mix overlapping bias bases and is deliberately unsupported.

The target keeps its own cold ionosphere, including VTEC, gradients, total STEC and accumulated dSTEC. Clock-prior anchors also remain those of the target's cold setup. No ionosphere, physical state, trajectory/force cache, QR factor, local conditional, residual or covariance is imported. Estimated transmitter clocks, resolved ambiguities, unsupported parametrization classes and relative-to-apriori constraints reject.

Before any coordinate is assigned, the reader validates the complete bounded binary payload, its SHA256, schema, exact mode/context, source eligibility, key order, dimensions, finite values and end of file. It compares the target's exact finalized chart and cold-origin hash. The chart includes parameter order, native basis/datum matrices, prior anchors and settings, raw epoch times, observations and weights, receiver/transmitter selections, track bounds/types and each observation's track assignment. Clock-corrected geometry times and physical trial coordinates are excluded. The target's existing zero update then refreshes geometry; a second collection verifies that the selected tuple, cold ionosphere and prior anchors survived unchanged. Any later chart reinitialization in that native process rejects before components can reset their private coordinates.

Every target still performs the existing complete nuisance refit and fresh undamped rank evaluation. A binary seed is exported only after strict nuisance convergence and a fresh full-rank linearization. Floor-limited or exhausted profiles cannot export a seed; their companion explicitly records ineligibility. This seed is initialization evidence, never covariance authorization.

The binary format uses length-prefixed strings, little-endian unsigned integers and IEEE binary64 values. Candidate05 canonicalizes only the two IEEE representations of exact zero when encoding numeric chart, invariant, cold-origin and snapshot values: `-0.0` and `+0.0` both encode as positive zero. Every finite nonzero bit pattern, including the smallest positive and negative subnormal and one-ULP differences, remains exact. No epsilon, rounding or state mutation is used; nonfinite values still reject. The payload bytes and candidate build remain independently hashed, so this does not authorize seed reuse between different builds.

This encoding correction addresses the measured diagnostic04 failure: the existing zero update changed a private code-bias coordinate from negative zero to positive zero. It does not establish that every invariant survives real native profiles; the unchanged cold/warm and perturbed-target gates remain required. Serialization does not change the live source coordinate's sign; imported exact zero has the canonical positive representation.

The format has a 64 MiB input limit, one MiB string limit, one million coordinate limit, strict source-eligibility marker and no trailing bytes. Both payload and companion use exclusive creation. The companion schema is `orbit-poc-native-nuisance-warm-state-v1` and records context/chart/cold-origin/payload hashes, source native prefix and final generation, eligibility, imported-source attribution, coordinate count and the checked target invariants.

Focused tests cover codec/hash correctness, malformed input rejection before mutation, full-coordinate preservation, local invariant and lifecycle guards, the production collector's track/time/weight coverage, and installer/build re-entry. These tests do not establish native cross-physical equivalence. Release evidence requires separate cold-versus-warm target perturbation profiles with nonzero priors, the unchanged objective/rank/convergence gates, and Python accepted-state/rollback tests. Timing and speedup remain unestablished until measured under suitable conditions.

The standalone API fixture `tests/nuisance_warm_native_matrix_fixture.cpp` must also be compiled against the actual pinned GROOPS source headers before a native build. Use `g++ -std=c++17 -fsyntax-only -I groops/extension -I /absolute/native-source/source tests/nuisance_warm_native_matrix_fixture.cpp`. This instantiates both ledger matrix readers with native `Matrix` and `Vector`; native `Vector` exposes a single-index accessor. The check requires the pinned native headers and performs no link or estimation. It complements the isolated runtime fixture and does not establish full native build or scientific correctness.


Candidate06 cold-origin policy is `receiver-clock-starting-guess-excluded-v2`.
The exact chart carries this policy and the typed classification of each selected
receiver clock. Its starting estimate is excluded only from the cross-point cold
origin fingerprint. Receiver-clock prior anchors (`x0Recv` and `x0Trans`), prior
settings, all non-clock cold coordinates, observation support, weights and gauge
bases retain exact checks. The payload still stores each clock exactly, and
import plus zero refresh still checks every selected coordinate exactly. No
rounding, numerical tolerance or nuisance convergence threshold changes.

This separates the code-derived receiver-clock starting guess from any actual
constraint anchor. The candidate05 perturbed-target fixtures had identical
charts but observed differences of one to five ULPs in a few starting clock guesses;
the unchanged v1 origin check therefore rejected them before mutation. The
versioned chart tag causes old snapshots to reject; their origin fingerprints
are never silently interpreted with the new policy. Candidate06 retains payload
schema v1 because the coordinate serialization itself is unchanged. These are
implementation semantics, not evidence that perturbed-target native equivalence
has passed; that still requires separate real profile tests.
