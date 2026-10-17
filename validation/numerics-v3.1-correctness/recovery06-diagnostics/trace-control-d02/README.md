# Diagnostic row arithmetic trace

This is a diagnostic overlay for a **fresh** generated GROOPS tree after the frozen candidate06 extension. It is not a numerical correction or an acceptance gate. Do not apply it to source03 or a previous build.

```sh
python3 install_row_trace.py --tree /new/groops-source --receipt /new/diagnostic/row-trace-install.json
```

Leave `ORBIT_POC_ROW_TRACE_DIRECTORY` unset for the diagnostic binary's control replay. For the traced replay, set it to an absolute, already-created writable directory. The fixed selected rows are `(receiver, transmitter, epoch, type index)`:

```text
(0,13,30,5) (0,4,115,1) (0,16,8,4) (0,9,114,4) (0,9,113,5)
```

Each process opens its own `row-trace-PID.tsv` for each write and immediately closes it. Trial children therefore inherit no writable trace descriptor. Formatting preserves the caller's floating environment and `errno`. The per-file process ID, evaluation counter and event counter identify ordered events; ordinary and arithmetic-audit evaluations are distinct.

The TSV has no header and has these 16 fields:

```text
artifact_stem phase alpha_hex receiver transmitter epoch row component stage kind operand_index value_hex double_bits evaluation event arithmetic_audit_mode
```

Double values include their exact 64-bit representation. Long-double values use exact hexadecimal floating notation; uninitialized x87 padding bytes are deliberately excluded. A `row` in a full vector/matrix operand is that operand's native index, not necessarily the selected observation index. `signal_composition` and `ambiguity_type_mapping` establish the mappings. The `VTEC_*_shadow` fields are separately evaluated native mapping/trigonometric factors with preserved floating environment; the original update expression is unchanged.

The range expansion is recorded before its Double conversion. The remaining taps expose actual vector operands, scalar states, stage outputs, all configured STEC flags and primitive inputs, the STEC prior row, weighting and retained original rows. Every original scalar arithmetic statement remains intact. Existing vector-expression temporaries are exposed through const references; their calculations and update order are preserved. Clock, signal-bias and ambiguity update rounding is assessed from actual baseline/trial native-state snapshots. This first probe does not trace every individual bias/clock update operation.

Before interpreting a trace, require numerical identity:

```sh
python3 verify_trace_equivalence.py \
  --reference /original06/point-001-nonzero-full-prior \
  --trace-off /new/diagnostic/trace-off \
  --trace-on /new/diagnostic/trace-on \
  --last-generation 8 --receipt /new/diagnostic/equivalence.json
```

The verifier compares retained matrix/target bytes, row bytes after decompression, parameter scales, corrections, coordinates and objective/search diagnostics. Earlier R/z/rhs artifacts may be verified through their original completed native-retention receipts; the final generation must retain the actual bytes. Only spool-directory paths and child CPU-time/RSS fields are excluded from metadata comparison. Any mismatch blocks attribution to the frozen run.

The fixture suite exercises representation, filters, fork isolation, formatter environment preservation, installer failure handling and equivalence mutation rejection:

```sh
python -m pytest test_row_trace.py -q -p no:cacheprovider
```

No result from this diagnostic can replace the unchanged 106 native tests, four refinements, two objective checks or two prescribed failure replays.
