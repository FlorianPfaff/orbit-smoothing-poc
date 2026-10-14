"""Launch-to-report wrapper; run inside the verified common runtime namespace."""
from orbit_poc.numerics.campaign import main

if __name__ == "__main__":
    raise SystemExit(main())
