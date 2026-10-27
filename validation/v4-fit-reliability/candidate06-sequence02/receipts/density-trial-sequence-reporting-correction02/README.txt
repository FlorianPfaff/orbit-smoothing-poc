SOURCE ONLY; no imports, AST, tests, Python or native execution by the author.

Preserves correction01 and actual candidate06-postsequence-audit-tests01 (176 passed, 1 failed). The sole measured failure was the existing lifecycle AST equality check rejecting the intentionally changed one-line aggregate-reporting predicate. sequence.py and test_sequence.py are byte-identical to correction01; no second control change is introduced.

The copied lifecycle test now verifies that the exact original reporting statement occurs once in original run(), and the exact authorized conditional predicate plus error text occurs once in corrected run(). Only that exact AST statement is normalized back to the original statement. The entire run() function and every other previously protected lifecycle/execution function must then match the original AST. run() is not exempted, and unrelated statement/predicate/message changes remain failures. The original checked/gate_audit exemptions predate this correction and remain unchanged.

Root owns separate serial test qualification. This source changes no old result, numerical policy or scientific failure. Pulse remains passed and density remains failed. This is not a launch-ready sequence.
