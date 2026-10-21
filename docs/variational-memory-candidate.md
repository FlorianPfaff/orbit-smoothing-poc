# Bounded fixed-parameter variational evaluation candidate

The archived v4 campaign remains unchanged. Its four 72-hour density memory
exits occur in `OrbitPocEvaluateVariational`, after native propagation wrote a
variational arc. At the configured five-second grid, two full design matrices
need 10,766,960,640 bytes (10.03 GiB) for the copied arc’s 51,840 epochs
and 4,327 parameters. The last epoch is 2024-05-12 23:59:55 UTC.
This allocation exceeds the existing 8 GiB process-tree limit before QR or LM.

This candidate changes only storage in that fixed-parameter evaluator. It calls
the existing `VariationalEquationFromFile::integrateArc` with all original
parameter columns in bounded, chronological blocks. The same native model
instance and its integration accumulator survive every call. Blocks do not
restart propagation, change pulses or density knots, add a statistical boundary,
or introduce priors. The six-row initial-state map and reanchoring solve are
unchanged, and final trajectory interpolation uses the original complete epoch
grid. Only evaluated position and velocity are retained over the whole arc.

Install into a fresh native source tree after the numerics and segmented
extensions (and the wide-tangent candidate if selected):

```sh
python groops/extension/native_variational_memory.py --source /absolute/new-native-tree
```

The installer validates all anchors before writing and records exact source and
implementation hashes in `orbit-poc-variational-memory-extension.json`. It
rejects partial, changed or symlinked installations. An exact repeat verifies
the existing installation. Base installers must not be rerun over this overlay.

`ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS` is unset or `0` by default, preserving the
original evaluator. Values `1` through `65536` enable the candidate; `64` is a
bounded development setting. Noncanonical values reject explicitly. Native
dense-reference query exports used by small gates remain unsupported together
with blocking and reject rather than silently allocating the full design.
Ordinary orbit queries and segmented local-operator exports remain supported.

The full parameter dimension and arithmetic operations are retained, but changing
the row count passed to BLAS can change rounding. Actual native off/on pairs
must therefore pass the unchanged closure/refinement limits. The added tests
cover pulse and density parameters, first-state reanchoring, block sizes crossing
physical boundaries, and off-grid queries. Real-header syntax and installer tests
alone do not establish numerical equivalence or a successful 72-hour fit.

This component does **not** solve the 48-hour GNSS profiling memory exits. Those
runs complete closure and the first QR factor; the saved process records show a
new isolated child just before process-tree RSS exceeds the limit. The GNSS
profile still holds its full position and velocity designs, and fork duplication
is a separate investigation. Memory accounting, limits, rank policy, nuisance
convergence, physical models, weights, and release gates are unchanged.
