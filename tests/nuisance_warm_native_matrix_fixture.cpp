// Compile against actual pinned GROOPS base/matrix.h, not substitute classes.
// Syntax-only: no native processing, numerical fit, executable or link step.
#include "base/matrix.h"
#include "nuisanceWarmState.h"
void instantiateNativeMatrixAndVector(orbitPocWarm::Ledger &ledger,
                                     const Matrix &matrix,const Vector &vector,
                                     Vector &mutableVector)
{
  ledger.matrix("matrix",matrix);
  ledger.unchangedMatrix("matrix",matrix);
  ledger.matrix("vector",vector);
  ledger.unchangedMatrix("vector",vector);
  ledger.values("coordinates",mutableVector);
}
