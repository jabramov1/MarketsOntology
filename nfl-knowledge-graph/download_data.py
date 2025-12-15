#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd


def write_table(df: pd.DataFrame, out_dir: Path, stem: str, fmt: str) -> None:
    """Write dataframe to parquet/csv/both with consistent naming."""
    fmt = fmt.lower()
    if fmt not in {"parquet", "csv", "both"}:
        raise ValueError(f"Unknown format: {fmt}")
    if fmt in {"parquet", "both"}:
        df.to_parquet(out_dir / f"{stem}.parquet", index=False)
    if fmt in {"csv", "both"}:
        df.to_csv(out_dir / f"{stem}.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--out", type=str, default="data")
    parser.add_argument("--pbp-sample", type=int, default=10000, help="Sample N plays for faster loading (0 = all)")
    parser.add_argument(
        "--format",
        type=str,
        default="both",
        choices=["parquet", "csv", "both"],
        help="Write parquet for processing speed and/or CSV for readability. Default: both.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import nfl_data_py as nfl
    except ImportError as e:
        raise SystemExit("nfl_data_py not installed. Run: pip install nfl_data_py") from e

    year = args.season

    print(f"Downloading team descriptions…")
    teams = nfl.import_team_desc()
    write_table(teams, out_dir, "team_desc", args.format)

    print(f"Downloading schedules for {year}…")
    sched = nfl.import_schedules([year])
    write_table(sched, out_dir, f"schedules_{year}", args.format)

    print(f"Downloading rosters for {year}…")
    # nfl_data_py API differs by version; try known function names in order
    rosters = None
    for fn_name in ["import_rosters", "import_seasonal_rosters", "__import_rosters"]:
        fn = getattr(nfl, fn_name, None)
        if fn:
            rosters = fn([year])
            break
    if rosters is None:
        raise SystemExit(
            "Could not find a rosters import function in nfl_data_py. "
            "Expected one of: import_rosters, import_seasonal_rosters."
        )
    write_table(rosters, out_dir, f"rosters_{year}", args.format)

    print(f"Downloading injuries for {year}…")
    try:
        injuries = nfl.import_injuries([year])
        write_table(injuries, out_dir, f"injuries_{year}", args.format)
    except Exception as e:
        print(f"WARNING: injury import failed ({e}). Continuing without injuries.")
        write_table(pd.DataFrame(), out_dir, f"injuries_{year}", args.format)

    print(f"Downloading play-by-play for {year}… (this can be large)")
    pbp = nfl.import_pbp_data([year], downcast=True)
    if args.pbp_sample and args.pbp_sample > 0 and len(pbp) > args.pbp_sample:
        pbp = pbp.sample(args.pbp_sample, random_state=42).reset_index(drop=True)
    write_table(pbp, out_dir, f"pbp_{year}", args.format)

    print("Done.")
    print(f"Wrote files to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
