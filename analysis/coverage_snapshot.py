"""Plot fixed-epoch coverage across independent seeds from the report CSV."""
import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main(root):
    with (root / "report/fixed_epoch_coverage.csv").open(newline="") as stream:
        rows = [row for row in csv.DictReader(stream)
                if row["atmosphere"] == "disturbed"
                and row["model"] in ("white", "colored", "density")
                and abs(float(row["elapsed_hours"]) - 12) < 1e-9]
    assert len(rows) == 24 and all(int(row["seed_count"]) == 20 for row in rows)
    dest = root / "analysis"
    dest.mkdir(exist_ok=True)
    with (dest / "coverage_at_peak.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    labels = [(o, c) for o in ("leo300", "leo500", "eccentric", "leo800")
              for c in ("normal", "blackout")]
    names = {"leo300": "300 km", "leo500": "500 km", "eccentric": "300 × 800 km", "leo800": "800 km"}
    fig, ax = plt.subplots(figsize=(10, 7), layout="constrained")
    for offset, model, color in ((-.2, "white", "#0072B2"), (0, "colored", "#D55E00"), (.2, "density", "#009E73")):
        group = {(row["orbit"], row["coverage"]): row for row in rows if row["model"] == model}
        values = [float(group[key]["position_joint_95_coverage"]) for key in labels]
        low = [value - float(group[key]["wilson_95_low"]) for key, value in zip(labels, values)]
        high = [float(group[key]["wilson_95_high"]) - value for key, value in zip(labels, values)]
        ax.errorbar(values, [i + offset for i in range(len(labels))], xerr=[low, high],
                    fmt="o", color=color, capsize=3, label=model, markersize=5)
    ax.axvline(.95, color="#333333", linestyle="--", linewidth=1, label="Nominal 95%")
    ax.set(yticks=range(len(labels)),
           yticklabels=[f"{names[o]} · {'normal tracking' if c == 'normal' else '11–13 h blackout'}" for o, c in labels],
           xlabel="Fraction of 20 true positions inside the reported 95% ellipsoid",
           xlim=(-.03, 1.03), title="Uncertainty at the disturbance peak (12 h)\nDots: observed coverage · bars: 95% Wilson intervals across seeds")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=.2)
    ax.legend(loc="lower left", ncols=4, bbox_to_anchor=(0, 1.1), fontsize=9)
    fig.savefig(dest / "coverage_at_peak.png", dpi=300)
    fig.savefig(dest / "coverage_at_peak.pdf")
    plt.close(fig)
    print(f"Saved {len(rows)} fixed-epoch coverage records and figure.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    main(parser.parse_args().input_dir)
