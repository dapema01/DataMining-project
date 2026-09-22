#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fertility_konjunktur_corr.py
============================

Correlate Swedish fertility against the business-cycle indicators in SCB's
"Konjunkturklockan" export (14 indicators x 2 measures, monthly).

The point of the script is not just to print a correlation matrix. Naive
year-on-year correlation of two trending series produces large, confident,
meaningless numbers. So this does four things properly:

  1. CONCEPTION-TIME EXPOSURE, NOT CALENDAR-YEAR MATCHING.
     A child born in year t was conceived ~9 months earlier, and the decision
     to try was taken some months before that. Matching births in year t to
     GDP in year t therefore mismeasures the timing by roughly a year. For
     each birth year the script averages each monthly indicator over an
     exposure window that ends `gestation + lag` months before the mean birth
     date, and sweeps `lag` over a user-set grid.

  2. DETRENDING. Fertility fell steadily after 2010 and several indicators
     trend too. Both series are detrended (first difference by default;
     linear or Hodrick-Prescott also available) before correlating.

  3. AUTOCORRELATION-AWARE INFERENCE. Annual macro series are serially
     correlated, so the nominal p-value from n=25 observations is too
     optimistic. The script reports an effective-sample-size-adjusted p
     (Pyper-Peterman / modified Chelton) alongside the naive one, plus a
     moving-block-bootstrap confidence interval.

  4. MULTIPLICITY CONTROL. 14 indicators x 2 measures x ~5 lags is ~140
     tests; at alpha=0.05 you expect ~7 false positives. Benjamini-Hochberg
     FDR q-values are reported across the whole grid.

Usage
-----
With konjunkturklockan.csv and Fruktbarhet_riket_kvinnor.csv in the working
directory, no arguments are needed:

    python3 fertility_konjunktur_corr.py

Otherwise, or for other inputs:

    # any flat year/value file, header or not, extra dimension columns fine
    python3 fertility_konjunktur_corr.py \
        --konjunktur konjunkturklockan.csv \
        --fertility Fruktbarhet_riket_kvinnor.csv \
        --outdir results/

    # one region out of a file covering several
    python3 fertility_konjunktur_corr.py \
        --fertility fruktbarhet_lan.csv --fert-filter "region=03 Uppsala"

    # fertility straight out of a long-format SCB table (e.g. TAB1264)
    python3 fertility_konjunktur_corr.py \
        --fertility TAB1264_sv.csv --fertility-format scb-long

    # inspect a fertility file's schema without running the analysis
    python3 fertility_konjunktur_corr.py --fertility TAB1264_sv.csv --inspect

The fertility loader locates the year and value columns by content, not by
position, sniffs whether there is a header row (a headerless file otherwise
loses its first observation), and refuses to silently pool a multi-valued
dimension such as region.

Outputs (in --outdir)
---------------------
    correlations.csv        every indicator x measure x lag, fully annotated
    top_findings.txt        the readable summary, same content as stdout
    exposure_panel.csv      the annual indicator panel actually correlated
    fertility_series.csv    the fertility series actually correlated
    heatmap_<measure>.png   correlation by indicator x lag
    scatter_top.png         scatter plots of the strongest associations

Dependencies: pandas, numpy, scipy. matplotlib optional (plots are skipped
without it). statsmodels optional (only for --detrend hp).
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# Labels SCB uses for aggregate / total rows. Long SCB tables interleave
# region-level and age-level totals with the detail rows; summing naively
# double- or triple-counts. Matched case-insensitively against dimension
# columns.
AGGREGATE_PATTERNS = [
    r"^riket$",
    r"^hela\s+riket$",
    r"^totalt?$",
    r"^samtliga",
    r"^alla\s",
    r"^summa",
    r"^alder\s+totalt$",
    r"^ålder\s+totalt$",
    r"^alla\s+åldrar$",
    r"^-$",
    r"totalt$",
]

# Column-name hints used when auto-detecting a long-format fertility file.
YEAR_HINTS = ["år", "ar", "year", "tid", "period"]
VALUE_HINTS = ["värde", "varde", "value", "antal", "tal", "observations"]

MEASURE_LEVEL = "Konjunkturläge"
MEASURE_CHANGE = "Förändring från föregående period"


# --------------------------------------------------------------------------
# I/O helpers
# --------------------------------------------------------------------------


def _row_is_header(first_row: pd.Series, rest: pd.DataFrame) -> bool:
    """Decide whether row 0 is a header or already data.

    SCB exports are inconsistent: some carry a header row, some (notably
    hand-trimmed extracts from Statistikdatabasen) start straight at the
    data. Guessing wrong silently deletes an observation, so decide it
    explicitly: row 0 is a header only if it contains no year-like or
    decimal-numeric cell while the rows below it do.
    """
    def numeric_like(values: pd.Series) -> float:
        text = values.astype(str).str.strip().str.replace(",", ".", regex=False)
        return float(pd.to_numeric(text, errors="coerce").notna().mean())

    if rest.empty:
        return False
    return numeric_like(first_row) == 0.0 and numeric_like(rest.iloc[0]) > 0.0


def read_csv_robust(path: Path, **kwargs) -> pd.DataFrame:
    """Read a CSV without knowing its encoding, separator, or header up front.

    SCB ships files in ISO-8859-1 as often as UTF-8, semicolon-separated as
    often as comma-separated, and with or without a header row. Try the
    plausible combinations, keep the first that yields more than one column,
    and sniff the header rather than assuming one.
    """
    encodings = ["utf-8-sig", "utf-8", "iso-8859-1", "cp1252"]
    separators = kwargs.pop("sep", None)
    separators = [separators] if separators else [";", ",", "\t"]
    forced_header = kwargs.pop("header", "sniff")

    last_error: Exception | None = None
    for enc in encodings:
        for sep in separators:
            try:
                raw = pd.read_csv(path, sep=sep, encoding=enc, header=None, **kwargs)
            except Exception as exc:  # noqa: BLE001 - genuinely want any failure
                last_error = exc
                continue
            if raw.shape[1] < 2:
                continue

            if forced_header == "sniff":
                has_header = _row_is_header(raw.iloc[0], raw.iloc[1:])
            else:
                has_header = forced_header == 0

            if has_header:
                df = raw.iloc[1:].reset_index(drop=True)
                df.columns = [str(c).strip().lstrip("﻿") for c in raw.iloc[0]]
            else:
                df = raw
                df.columns = [f"col{i}" for i in range(raw.shape[1])]

            df = df.infer_objects()
            df.attrs["encoding"] = enc
            df.attrs["sep"] = sep
            df.attrs["had_header"] = has_header
            return df
    if last_error is not None:
        raise last_error
    raise ValueError(f"Could not parse {path} into more than one column.")


def parse_scb_month(series: pd.Series) -> pd.PeriodIndex:
    """Convert SCB's '2000M01' month labels to a monthly PeriodIndex."""
    cleaned = series.astype(str).str.strip().str.upper().str.replace("M", "-", regex=False)
    return pd.PeriodIndex(cleaned, freq="M")


# --------------------------------------------------------------------------
# Loading: the business-cycle side
# --------------------------------------------------------------------------


def load_konjunktur(path: Path, verbose: bool = True) -> pd.DataFrame:
    """Load Konjunkturklockan into a monthly panel.

    Returns a DataFrame indexed by month with a MultiIndex column
    (indikator, tabellinnehåll).
    """
    raw = read_csv_robust(path)
    raw.columns = [c.strip().lstrip("﻿") for c in raw.columns]

    required = {"indikator", "tabellinnehåll", "månad", "Värde"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(
            f"{path.name} is missing expected column(s): {sorted(missing)}. "
            f"Found: {list(raw.columns)}"
        )

    raw["month"] = parse_scb_month(raw["månad"])
    raw["Värde"] = pd.to_numeric(raw["Värde"], errors="coerce")

    panel = raw.pivot_table(
        index="month",
        columns=["indikator", "tabellinnehåll"],
        values="Värde",
        aggfunc="mean",
    ).sort_index()

    if verbose:
        n_missing = int(panel.isna().sum().sum())
        total = panel.size
        print(
            f"[konjunktur] {panel.shape[1]} series, "
            f"{panel.index.min()}..{panel.index.max()} "
            f"({panel.shape[0]} months), "
            f"{n_missing}/{total} missing values ({n_missing / total:.1%})"
        )
        # Flag series with substantial interior gaps -- the edges are expected.
        for col in panel.columns:
            s = panel[col]
            interior = s.loc[s.first_valid_index() : s.last_valid_index()]
            gaps = int(interior.isna().sum())
            if gaps > 3:
                print(
                    f"[konjunktur]   note: {col[0]} / {col[1]} has {gaps} "
                    f"missing months inside its coverage "
                    f"({s.first_valid_index()}..{s.last_valid_index()})"
                )
    return panel


# --------------------------------------------------------------------------
# Loading: the fertility side
# --------------------------------------------------------------------------


def _looks_like_aggregate(values: pd.Series) -> pd.Series:
    """Boolean mask: which entries look like an SCB aggregate/total label?"""
    text = values.astype(str).str.strip().str.lower()
    mask = pd.Series(False, index=values.index)
    for pattern in AGGREGATE_PATTERNS:
        mask |= text.str.match(pattern, na=False)
    return mask


def _guess_column(columns: list[str], hints: list[str]) -> str | None:
    lowered = {c: c.strip().lower() for c in columns}
    for col, low in lowered.items():
        if low in hints:
            return col
    for col, low in lowered.items():
        if any(h in low for h in hints):
            return col
    return None


def inspect_fertility_file(path: Path) -> None:
    """Print a fertility file's schema so the user can choose columns."""
    df = read_csv_robust(path, nrows=5000)
    print(f"\n=== {path.name} ===")
    print(f"encoding={df.attrs.get('encoding')}  sep={df.attrs.get('sep')!r}")
    print(f"columns: {list(df.columns)}")
    print(f"\nfirst rows:\n{df.head(8).to_string()}")
    print("\nper-column cardinality and sample values (first 5000 rows):")
    for col in df.columns:
        uniques = df[col].dropna().unique()
        sample = ", ".join(str(u) for u in uniques[:8])
        flagged = ""
        if df[col].dtype == object:
            n_agg = int(_looks_like_aggregate(df[col]).sum())
            if n_agg:
                flagged = f"  <-- {n_agg} rows look like AGGREGATE/TOTAL labels"
        print(f"  {col!r}: {len(uniques)} distinct | {sample}{flagged}")
    print(
        "\nRerun with --fertility-format scb-long (plus --fert-year-col / "
        "--fert-value-col / --fert-dim-cols if auto-detection picks wrong)."
    )


def _find_year_column(df: pd.DataFrame) -> str | None:
    """Find the year column by content: mostly 4-digit values in 1900-2100."""
    best, best_score = None, 0.0
    for col in df.columns:
        nums = pd.to_numeric(
            df[col].astype(str).str.strip().str.extract(r"^(\d{4})$")[0],
            errors="coerce",
        )
        score = float(((nums >= 1900) & (nums <= 2100)).mean())
        if score > best_score:
            best, best_score = col, score
    return best if best_score > 0.8 else None


def _find_value_column(df: pd.DataFrame, exclude: list[str]) -> str | None:
    """Find the measurement column: the most-numeric column that isn't a year."""
    best, best_score = None, 0.0
    for col in df.columns:
        if col in exclude:
            continue
        nums = pd.to_numeric(
            df[col].astype(str).str.strip().str.replace(",", ".", regex=False),
            errors="coerce",
        )
        score = float(nums.notna().mean())
        # A column of clean 4-digit integers is another year/id column, not a
        # measurement -- penalise it.
        if score > 0.8 and nums.dropna().between(1900, 2100).mean() > 0.9:
            if (nums.dropna() % 1 == 0).mean() > 0.95:
                score *= 0.2
        if score > best_score:
            best, best_score = col, score
    return best if best_score > 0.8 else None


def describe_units(values: pd.Series) -> tuple[str, str]:
    """Guess whether the series is a rate (TFR/ASFR) or raw birth counts."""
    median = float(values.median())
    if 0.3 <= median <= 8:
        return ("rate", "children per woman (TFR/ASFR-like)")
    if median > 500:
        return ("count", "birth counts")
    return ("unknown", "unrecognised scale")


def load_fertility_series(
    path: Path,
    year_col: str | None,
    value_col: str | None,
    filters: dict[str, str] | None = None,
    agg: str = "auto",
    verbose: bool = True,
) -> pd.Series:
    """Load a fertility series from a flat file, header or no header.

    Handles the common shapes of an SCB Statistikdatabasen extract:
      region,sex,year,value      (no header -- e.g. Fruktbarhet_riket_kvinnor)
      år;TFR                     (two columns, with header)
      any column order, comma or semicolon, UTF-8 or ISO-8859-1.

    Columns are located by content rather than position, extra dimension
    columns (region, sex) are reported, and multi-valued dimensions must be
    resolved with --fert-filter rather than being silently pooled.
    """
    df = read_csv_robust(path)
    df.columns = [str(c).strip().lstrip("﻿") for c in df.columns]

    if verbose:
        header_note = "with header" if df.attrs.get("had_header") else "no header row"
        print(
            f"[fertility] {path.name}: {header_note}, "
            f"sep={df.attrs.get('sep')!r}, encoding={df.attrs.get('encoding')}, "
            f"{len(df)} rows, columns={list(df.columns)}"
        )

    # Apply user filters before detection so they can disambiguate.
    if filters:
        for col, val in filters.items():
            if col not in df.columns:
                raise ValueError(
                    f"--fert-filter column {col!r} not found. "
                    f"Available: {list(df.columns)}"
                )
            before = len(df)
            df = df[df[col].astype(str).str.strip() == val]
            if verbose:
                print(f"[fertility]   filter {col}={val!r}: {before} -> {len(df)} rows")
            if df.empty:
                raise ValueError(f"--fert-filter {col}={val!r} matched no rows.")

    year_col = year_col or _guess_column(list(df.columns), YEAR_HINTS) or _find_year_column(df)
    if year_col is None:
        raise ValueError(
            f"Could not identify a year column in {path.name} "
            f"(columns: {list(df.columns)}). Pass --fert-year-col."
        )
    if value_col is None:
        value_col = _guess_column(
            [c for c in df.columns if c != year_col], VALUE_HINTS
        ) or _find_value_column(df, exclude=[year_col])
    if value_col is None:
        raise ValueError(
            f"Could not identify a value column in {path.name} "
            f"(columns: {list(df.columns)}). Pass --fert-value-col."
        )

    dim_cols = [c for c in df.columns if c not in (year_col, value_col)]
    if verbose:
        print(f"[fertility]   year={year_col!r}, value={value_col!r}")
        for col in dim_cols:
            uniques = df[col].astype(str).str.strip().unique()
            if len(uniques) == 1:
                print(f"[fertility]   {col!r}: constant {uniques[0]!r} -- fine")
            else:
                print(
                    f"[fertility]   {col!r}: {len(uniques)} distinct values "
                    f"{sorted(uniques)[:6]}"
                )

    years = pd.to_numeric(
        df[year_col].astype(str).str.extract(r"(\d{4})")[0], errors="coerce"
    )
    values = pd.to_numeric(
        df[value_col].astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce",
    )
    tidy = pd.DataFrame({"year": years, "fertility": values}).dropna()
    if tidy.empty:
        raise ValueError(
            f"No usable (year, value) pairs parsed from {path.name}. "
            f"Check --fert-year-col / --fert-value-col."
        )

    kind, unit_label = describe_units(tidy["fertility"])

    # Choosing the aggregator matters: summing rates is meaningless, summing
    # counts is correct. Only relevant when a year appears more than once.
    dupes = int(tidy["year"].duplicated().sum())
    if agg == "auto":
        agg = "sum" if kind == "count" else "mean"
    if dupes and verbose:
        print(
            f"[fertility]   {dupes} duplicate year rows -> aggregating with "
            f"'{agg}' (detected as {kind}). Use --fert-agg to override; "
            f"note that summing a rate like TFR is not meaningful."
        )
        if len(dim_cols) > 1 or any(
            df[c].astype(str).str.strip().nunique() > 1 for c in dim_cols
        ):
            print(
                "[fertility]   WARNING: duplicate years come from a "
                "multi-valued dimension above. Pool deliberately or restrict "
                "it with --fert-filter COL=VALUE."
            )

    out = tidy.groupby("year")["fertility"].agg(agg)
    out.index = out.index.astype(int)
    out = out.sort_index()

    if verbose:
        print(
            f"[fertility]   -> {len(out)} years ({out.index.min()}..{out.index.max()}), "
            f"values {out.min():.3g}..{out.max():.3g} [{unit_label}]"
        )
        gaps = sorted(set(range(out.index.min(), out.index.max() + 1)) - set(out.index))
        if gaps:
            print(f"[fertility]   WARNING: missing years in the range: {gaps}")
        if kind == "count":
            print(
                "[fertility]   NOTE: these look like birth COUNTS, not rates. "
                "Counts move with the size of the female population of "
                "childbearing age, itself correlated with the economy through "
                "migration. Convert to ASFR/TFR before interpreting."
            )
    out.attrs["kind"] = kind
    out.attrs["unit_label"] = unit_label
    out.attrs["source"] = path.name
    return out


def load_fertility_scb_long(
    path: Path,
    year_col: str | None,
    value_col: str | None,
    dim_cols: list[str] | None,
    drop_aggregates: bool,
    verbose: bool = True,
) -> pd.Series:
    """Load a long-format SCB table (e.g. TAB1264) and total by year.

    Long SCB tables interleave aggregate rows (riket, 'ålder totalt', ...)
    with detail rows. Summing without filtering double- or triple-counts.
    This drops any row whose dimension columns carry a total-like label --
    and prints exactly what it dropped, because the patterns are heuristics
    and worth eyeballing once against your file.
    """
    df = read_csv_robust(path)
    df.columns = [str(c).strip().lstrip("﻿") for c in df.columns]

    year_col = year_col or _guess_column(list(df.columns), YEAR_HINTS)
    if year_col is None:
        raise ValueError(
            f"Could not identify the year column in {path.name}. "
            f"Columns: {list(df.columns)}. Pass --fert-year-col explicitly."
        )
    if value_col is None:
        candidates = [c for c in df.columns if c != year_col]
        value_col = _guess_column(candidates, VALUE_HINTS)
        if value_col is None:
            numeric = [
                c
                for c in candidates
                if pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9
            ]
            value_col = numeric[-1] if numeric else candidates[-1]

    if dim_cols is None:
        dim_cols = [c for c in df.columns if c not in (year_col, value_col)]

    if verbose:
        print(
            f"[fertility] scb-long: year={year_col!r} value={value_col!r} "
            f"dimensions={dim_cols}"
        )

    n_before = len(df)
    if drop_aggregates and dim_cols:
        mask = pd.Series(False, index=df.index)
        for col in dim_cols:
            col_mask = _looks_like_aggregate(df[col])
            if verbose and col_mask.any():
                dropped_labels = sorted(df.loc[col_mask, col].astype(str).unique())[:10]
                print(
                    f"[fertility]   dropping {int(col_mask.sum())} rows where "
                    f"{col!r} is an aggregate: {dropped_labels}"
                )
            mask |= col_mask
        df = df.loc[~mask]
        if verbose:
            print(
                f"[fertility]   {n_before} rows -> {len(df)} after removing "
                f"aggregate rows ({n_before - len(df)} dropped)"
            )
            if n_before == len(df):
                print(
                    "[fertility]   WARNING: nothing matched the aggregate "
                    "patterns. Run with --inspect and confirm this file really "
                    "contains no total rows before trusting the sums."
                )

    years = pd.to_numeric(
        df[year_col].astype(str).str.extract(r"(\d{4})")[0], errors="coerce"
    )
    values = pd.to_numeric(
        df[value_col].astype(str).str.replace(",", ".", regex=False), errors="coerce"
    )
    out = (
        pd.DataFrame({"year": years, "fertility": values})
        .dropna()
        .groupby("year")["fertility"]
        .sum()
    )
    out.index = out.index.astype(int)
    if verbose:
        print(
            f"[fertility]   -> {len(out)} years "
            f"({out.index.min()}..{out.index.max()}), "
            f"values {out.min():,.0f}..{out.max():,.0f}"
        )
        print(
            "[fertility]   NOTE: these are birth COUNTS, not rates. Counts move "
            "with the size of the female population of childbearing age, which "
            "is itself correlated with the economy through migration. Convert to "
            "ASFR/TFR with population denominators before drawing conclusions."
        )
    return out.sort_index()


# --------------------------------------------------------------------------
# Exposure windows
# --------------------------------------------------------------------------


@dataclass
class ExposureSpec:
    gestation_months: int
    window_months: int
    lag_months: int
    birth_month: int  # mean birth month within the year (1-12)

    def window_for_year(self, year: int) -> tuple[pd.Period, pd.Period]:
        """Return (start, end) months of the exposure window for birth year."""
        mean_birth = pd.Period(year=year, month=self.birth_month, freq="M")
        end = mean_birth - self.gestation_months - self.lag_months
        start = end - (self.window_months - 1)
        return start, end

    def describe(self, year: int) -> str:
        start, end = self.window_for_year(year)
        return f"{start}..{end}"


def build_exposure_panel(
    monthly: pd.DataFrame,
    years: list[int],
    spec: ExposureSpec,
    min_coverage: float = 0.75,
) -> pd.DataFrame:
    """Average each monthly indicator over the exposure window of each year.

    A year's value is NaN if fewer than `min_coverage` of the window's months
    are observed, so the 2000-2001 gap in Näringslivets efterfrågan does not
    silently become a one-month average.
    """
    rows = {}
    for year in years:
        start, end = spec.window_for_year(year)
        window = monthly.loc[(monthly.index >= start) & (monthly.index <= end)]
        expected = spec.window_months
        if window.empty:
            rows[year] = pd.Series(np.nan, index=monthly.columns)
            continue
        coverage = window.notna().sum() / expected
        means = window.mean(skipna=True)
        means[coverage < min_coverage] = np.nan
        rows[year] = means
    panel = pd.DataFrame(rows).T
    panel.index.name = "year"
    return panel


# --------------------------------------------------------------------------
# Detrending
# --------------------------------------------------------------------------


def detrend(series: pd.Series, method: str) -> pd.Series:
    """Remove the trend so the correlation reflects cyclical co-movement."""
    s = series.astype(float)
    if method == "none":
        return s
    if method == "diff":
        return s.diff()
    if method == "linear":
        valid = s.dropna()
        if len(valid) < 3:
            return s * np.nan
        x = valid.index.values.astype(float)
        slope, intercept = np.polyfit(x, valid.values, 1)
        resid = valid.values - (slope * x + intercept)
        return pd.Series(resid, index=valid.index).reindex(s.index)
    if method == "hp":
        try:
            from statsmodels.tsa.filters.hp_filter import hpfilter
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "--detrend hp needs statsmodels: pip install statsmodels"
            ) from exc
        valid = s.dropna()
        if len(valid) < 5:
            return s * np.nan
        cycle, _ = hpfilter(valid, lamb=6.25)  # 6.25 = Ravn-Uhlig for annual data
        return cycle.reindex(s.index)
    raise ValueError(f"Unknown detrend method: {method}")


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


def lag1_autocorr(x: np.ndarray) -> float:
    if len(x) < 3:
        return 0.0
    x = x - x.mean()
    denom = np.sum(x * x)
    if denom == 0:
        return 0.0
    return float(np.sum(x[:-1] * x[1:]) / denom)


def effective_n(x: np.ndarray, y: np.ndarray) -> float:
    """Pyper-Peterman / modified Chelton effective sample size.

    Serially correlated series carry less independent information than their
    length suggests. n_eff = n * (1 - r1x*r1y) / (1 + r1x*r1y).
    """
    n = len(x)
    r1x, r1y = lag1_autocorr(x), lag1_autocorr(y)
    prod = r1x * r1y
    if prod >= 0.999:
        return 3.0
    n_eff = n * (1 - prod) / (1 + prod)
    return float(np.clip(n_eff, 3.0, n))


def p_from_r(r: float, n: float) -> float:
    """Two-sided p-value for a correlation given (effective) sample size."""
    if not np.isfinite(r) or n <= 2:
        return np.nan
    r = float(np.clip(r, -0.999999, 0.999999))
    t = r * np.sqrt((n - 2) / (1 - r * r))
    return float(2 * stats.t.sf(abs(t), df=n - 2))


def block_bootstrap_ci(
    x: np.ndarray,
    y: np.ndarray,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Moving-block bootstrap CI for Pearson r, preserving serial structure."""
    n = len(x)
    if n < 6:
        return (np.nan, np.nan)
    block = max(2, int(np.ceil(n ** (1 / 3))))
    n_blocks = int(np.ceil(n / block))
    max_start = n - block
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        xb, yb = x[idx], y[idx]
        if xb.std() == 0 or yb.std() == 0:
            out[i] = np.nan
            continue
        out[i] = np.corrcoef(xb, yb)[0, 1]
    out = out[np.isfinite(out)]
    if out.size < 100:
        return (np.nan, np.nan)
    return (
        float(np.percentile(out, 100 * alpha / 2)),
        float(np.percentile(out, 100 * (1 - alpha / 2))),
    )


def benjamini_hochberg(pvals: pd.Series) -> pd.Series:
    """BH FDR q-values, NaNs passed through."""
    valid = pvals.dropna().sort_values()
    m = len(valid)
    if m == 0:
        return pd.Series(np.nan, index=pvals.index)
    ranks = np.arange(1, m + 1)
    q = valid.values * m / ranks
    q = np.minimum.accumulate(q[::-1])[::-1]  # enforce monotonicity
    out = pd.Series(np.nan, index=pvals.index)
    out.loc[valid.index] = np.clip(q, 0, 1)
    return out


# --------------------------------------------------------------------------
# The analysis
# --------------------------------------------------------------------------


def run_analysis(
    monthly: pd.DataFrame,
    fertility: pd.Series,
    lags: list[int],
    spec_base: ExposureSpec,
    detrend_method: str,
    min_years: int,
    min_coverage: float,
    n_boot: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[int, pd.DataFrame], pd.Series]:
    years = sorted(int(y) for y in fertility.dropna().index)
    fert_detrended = detrend(fertility.loc[years], detrend_method)

    records = []
    panels: dict[int, pd.DataFrame] = {}

    for lag in lags:
        spec = ExposureSpec(
            gestation_months=spec_base.gestation_months,
            window_months=spec_base.window_months,
            lag_months=lag,
            birth_month=spec_base.birth_month,
        )
        panel = build_exposure_panel(monthly, years, spec, min_coverage)
        panels[lag] = panel

        for col in panel.columns:
            indikator, measure = col
            econ_detrended = detrend(panel[col], detrend_method)

            joined = pd.concat(
                {"econ": econ_detrended, "fert": fert_detrended}, axis=1
            ).dropna()
            n = len(joined)
            if n < min_years:
                continue

            x = joined["econ"].to_numpy(float)
            y = joined["fert"].to_numpy(float)
            if x.std() == 0 or y.std() == 0:
                continue

            r, p_naive = stats.pearsonr(x, y)
            rho, p_spear = stats.spearmanr(x, y)
            n_eff = effective_n(x, y)
            p_adj = p_from_r(r, n_eff)
            lo, hi = block_bootstrap_ci(x, y, n_boot=n_boot, seed=seed)

            records.append(
                {
                    "indikator": indikator,
                    "measure": measure,
                    "lag_months": lag,
                    "exposure_window_example": spec.describe(years[len(years) // 2]),
                    "n_years": n,
                    "first_year": int(joined.index.min()),
                    "last_year": int(joined.index.max()),
                    "pearson_r": r,
                    "p_naive": p_naive,
                    "n_effective": n_eff,
                    "p_autocorr_adjusted": p_adj,
                    "boot_ci_low": lo,
                    "boot_ci_high": hi,
                    "spearman_rho": rho,
                    "p_spearman": p_spear,
                }
            )

    results = pd.DataFrame(records)
    if results.empty:
        return results, panels, fert_detrended

    results["q_value_BH"] = benjamini_hochberg(results["p_autocorr_adjusted"])
    results["abs_r"] = results["pearson_r"].abs()
    results = results.sort_values("abs_r", ascending=False).reset_index(drop=True)
    return results, panels, fert_detrended


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def run_specification_curve(
    monthly: pd.DataFrame,
    fertility: pd.Series,
    lags: list[int],
    spec_base: ExposureSpec,
    methods: list[str],
    min_years: int,
    min_coverage: float,
    seed: int,
) -> pd.DataFrame:
    """Re-run every correlation under each detrending method.

    The detrending choice is a researcher degree of freedom, and on 25 annual
    observations it can flip a result. Rather than picking one and reporting
    it, this reports r under all of them so sign instability is visible.
    """
    frames = []
    for method in methods:
        try:
            res, _, _ = run_analysis(
                monthly=monthly,
                fertility=fertility,
                lags=lags,
                spec_base=spec_base,
                detrend_method=method,
                min_years=min_years,
                min_coverage=min_coverage,
                n_boot=0,  # CIs are not the point here; keep it fast
                seed=seed,
            )
        except SystemExit as exc:  # e.g. hp without statsmodels
            print(f"[robustness] skipping detrend={method}: {exc}")
            continue
        if res.empty:
            continue
        res = res[["indikator", "measure", "lag_months", "pearson_r",
                   "p_autocorr_adjusted", "q_value_BH"]].copy()
        res["detrend"] = method
        frames.append(res)

    if not frames:
        return pd.DataFrame()

    long = pd.concat(frames, ignore_index=True)
    wide = long.pivot_table(
        index=["indikator", "measure", "lag_months"],
        columns="detrend",
        values="pearson_r",
    )
    qwide = long.pivot_table(
        index=["indikator", "measure", "lag_months"],
        columns="detrend",
        values="q_value_BH",
    )

    summary = pd.DataFrame(index=wide.index)
    for method in wide.columns:
        summary[f"r_{method}"] = wide[method]
    summary["r_min"] = wide.min(axis=1)
    summary["r_max"] = wide.max(axis=1)
    summary["r_range"] = summary["r_max"] - summary["r_min"]
    signs = np.sign(wide)
    summary["sign_stable"] = (
        signs.apply(lambda row: row.dropna().abs().sum() == abs(row.dropna().sum()),
                    axis=1)
    )
    summary["n_specs"] = wide.notna().sum(axis=1)
    summary["min_q"] = qwide.min(axis=1)
    summary["robust"] = (
        summary["sign_stable"]
        & (summary["min_q"] < 0.10)
        & (summary["n_specs"] >= max(2, len(wide.columns) - 1))
    )
    return summary.reset_index().sort_values("r_range")


def format_robustness(summary: pd.DataFrame, methods: list[str]) -> str:
    lines: list[str] = []
    add = lines.append
    add("=" * 78)
    add("SPECIFICATION CURVE -- does the result survive the detrending choice?")
    add("=" * 78)
    add(f"Methods compared: {methods}")
    add("")
    if summary.empty:
        add("No specifications ran.")
        return "\n".join(lines)

    flips = summary[~summary["sign_stable"]]
    add(f"Tests run under >=2 specifications : {len(summary)}")
    add(f"Sign FLIPS across specifications   : {len(flips)} "
        f"({len(flips) / len(summary):.0%})")
    add("")

    robust = summary[summary["robust"]].sort_values("r_min", key=abs, ascending=False)
    add("-" * 78)
    add("ROBUST: same sign in every specification AND q < 0.10 in at least one")
    add("-" * 78)
    if robust.empty:
        add("  None.")
    else:
        rcols = [c for c in summary.columns if c.startswith("r_")
                 and c not in ("r_min", "r_max", "r_range")]
        header = "".join(f"{c.replace('r_', ''):>9}" for c in rcols)
        add(f"{'indicator':<30}{'meas':<8}{'lag':>4}{header}{'min q':>8}")
        for _, row in robust.head(20).iterrows():
            measure = "level" if row["measure"] == MEASURE_LEVEL else "change"
            cells = "".join(
                f"{row[c]:>+9.2f}" if np.isfinite(row[c]) else f"{'--':>9}"
                for c in rcols
            )
            add(
                f"{row['indikator'][:29]:<30}{measure:<8}"
                f"{int(row['lag_months']):>4}{cells}{row['min_q']:>8.3f}"
            )
    add("")
    add("-" * 78)
    add("HOW TO USE THIS")
    add("-" * 78)
    add(textwrap.dedent("""\
        A result that changes sign when you switch from first-differencing to
        an HP filter is not a result; it is a description of the filter. Only
        rows listed as robust above are worth writing up as associations, and
        even those are associations on ~25 national-level annual observations,
        which is not enough to support a causal claim.

        If the specifications disagree badly, that is itself worth reporting.
        For Swedish TFR over 2000-2025 the likely reason is that the secular
        post-2010 fertility decline -- a Nordic-wide phenomenon visible in
        Finland and Norway too, and not obviously a business-cycle effect --
        is large relative to any cyclical variation, so whatever the filter
        does with that decline drives the correlation."""))
    return "\n".join(lines)


def format_report(
    results: pd.DataFrame,
    fertility: pd.Series,
    detrend_method: str,
    spec: ExposureSpec,
    lags: list[int],
    top_n: int = 15,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("=" * 78)
    add("FERTILITY vs BUSINESS CYCLE -- correlation results")
    add("=" * 78)
    add("")
    add(f"Fertility series : {fertility.attrs.get('source', 'input')} -- "
        f"{fertility.index.min()}-{fertility.index.max()} "
        f"({len(fertility)} years), "
        f"{fertility.attrs.get('unit_label', 'unknown units')}, "
        f"range {fertility.min():.3g}-{fertility.max():.3g}")
    add(f"Detrending       : {detrend_method}")
    add(f"Exposure window  : {spec.window_months} months, ending "
        f"{spec.gestation_months} months (gestation) + lag before the mean "
        f"birth date (month {spec.birth_month})")
    add(f"Lags tested      : {lags} months")
    add(f"Tests run        : {len(results)}")
    add("")

    if results.empty:
        add("No indicator had enough overlapping years to correlate.")
        return "\n".join(lines)

    add("-" * 78)
    add(f"TOP {top_n} BY |r|")
    add("-" * 78)
    add(
        f"{'indicator':<32}{'measure':<10}{'lag':>5}{'r':>8}{'95% CI':>18}"
        f"{'p_adj':>9}{'q':>8}{'n':>4}"
    )
    for _, row in results.head(top_n).iterrows():
        measure = "level" if row["measure"] == MEASURE_LEVEL else "change"
        ci = (
            f"[{row['boot_ci_low']:+.2f},{row['boot_ci_high']:+.2f}]"
            if np.isfinite(row["boot_ci_low"])
            else "        n/a"
        )
        add(
            f"{row['indikator'][:31]:<32}{measure:<10}{row['lag_months']:>5}"
            f"{row['pearson_r']:>+8.3f}{ci:>18}"
            f"{row['p_autocorr_adjusted']:>9.3f}{row['q_value_BH']:>8.3f}"
            f"{row['n_years']:>4}"
        )
    add("")

    survivors = results[results["q_value_BH"] < 0.10]
    add("-" * 78)
    add("SURVIVING MULTIPLICITY CONTROL (BH q < 0.10)")
    add("-" * 78)
    if survivors.empty:
        add("None. With ~25 annual observations and this many tests, that is the")
        add("expected outcome unless an effect is strong. Treat the table above as")
        add("hypothesis-generating, not as findings.")
    else:
        for _, row in survivors.iterrows():
            measure = "level" if row["measure"] == MEASURE_LEVEL else "change"
            direction = "procyclical" if row["pearson_r"] > 0 else "countercyclical"
            add(
                f"  {row['indikator']} ({measure}), lag {row['lag_months']}m: "
                f"r={row['pearson_r']:+.3f}, q={row['q_value_BH']:.3f} "
                f"-> {direction}"
            )
    add("")

    add("-" * 78)
    add("BEST LAG PER INDICATOR (measure = level)")
    add("-" * 78)
    level = results[results["measure"] == MEASURE_LEVEL]
    if not level.empty:
        best = level.loc[level.groupby("indikator")["abs_r"].idxmax()]
        for _, row in best.sort_values("abs_r", ascending=False).iterrows():
            add(
                f"  {row['indikator'][:34]:<36} lag {row['lag_months']:>2}m  "
                f"r={row['pearson_r']:+.3f}  p_adj={row['p_autocorr_adjusted']:.3f}"
            )
    add("")

    add("-" * 78)
    add("READING THIS")
    add("-" * 78)
    add(textwrap.dedent("""\
        * p_adj corrects the nominal p-value for serial correlation via the
          effective sample size; it is the one to quote, and it is always the
          more conservative of the two.
        * q is the Benjamini-Hochberg FDR across every test in the grid. A
          small r with q > 0.10 is noise you looked at many times.
        * The 14 indicators are not independent -- GDP, hours worked,
          employment and business-sector production move together -- so
          "several indicators agree" is much weaker evidence than it looks.
        * The 1980s parental-leave reforms sit outside this window (data starts
          2000), but pronatalist policy, migration composition and the
          2008 and 2020 shocks are all live confounders inside it.
        * Correlation on ~25 annual points cannot separate "the economy drives
          fertility" from "both respond to something else". A panel across
          municipalities or counties buys far more identifying variation than
          a longer national time series would."""))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Plots
# --------------------------------------------------------------------------


def make_plots(
    results: pd.DataFrame,
    panels: dict[int, pd.DataFrame],
    fert_detrended: pd.Series,
    detrend_method: str,
    outdir: Path,
) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[plots] matplotlib not installed -- skipping plots.")
        return []

    written: list[Path] = []

    for measure, tag in [(MEASURE_LEVEL, "level"), (MEASURE_CHANGE, "change")]:
        subset = results[results["measure"] == measure]
        if subset.empty:
            continue
        grid = subset.pivot_table(
            index="indikator", columns="lag_months", values="pearson_r"
        )
        order = grid.abs().max(axis=1).sort_values(ascending=False).index
        grid = grid.loc[order]

        fig, ax = plt.subplots(figsize=(1.1 * len(grid.columns) + 5, 0.45 * len(grid) + 2))
        vmax = float(np.nanmax(np.abs(grid.values))) or 1.0
        im = ax.imshow(grid.values, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_xticks(range(len(grid.columns)))
        ax.set_xticklabels([f"{c}m" for c in grid.columns])
        ax.set_yticks(range(len(grid.index)))
        ax.set_yticklabels(grid.index, fontsize=9)
        ax.set_xlabel("additional lag before conception window")
        ax.set_title(
            f"Correlation with fertility -- {measure}\n"
            f"(detrend: {detrend_method})",
            fontsize=11,
        )
        for i in range(grid.shape[0]):
            for j in range(grid.shape[1]):
                val = grid.values[i, j]
                if np.isfinite(val):
                    ax.text(
                        j, i, f"{val:+.2f}",
                        ha="center", va="center", fontsize=8,
                        color="white" if abs(val) > 0.6 * vmax else "black",
                    )
        fig.colorbar(im, ax=ax, label="Pearson r", shrink=0.8)
        fig.tight_layout()
        path = outdir / f"heatmap_{tag}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(path)

    top = results.head(6)
    if not top.empty:
        ncols = 3
        nrows = int(np.ceil(len(top) / ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(4.2 * ncols, 3.6 * nrows))
        axes = np.atleast_1d(axes).ravel()
        for ax, (_, row) in zip(axes, top.iterrows()):
            panel = panels[row["lag_months"]]
            econ = detrend(panel[(row["indikator"], row["measure"])], detrend_method)
            joined = pd.concat({"econ": econ, "fert": fert_detrended}, axis=1).dropna()
            ax.scatter(joined["econ"], joined["fert"], s=28, alpha=0.8)
            for year, r_ in joined.iterrows():
                ax.annotate(str(int(year))[2:], (r_["econ"], r_["fert"]),
                            fontsize=6, alpha=0.6,
                            xytext=(3, 3), textcoords="offset points")
            if len(joined) > 2:
                slope, intercept = np.polyfit(joined["econ"], joined["fert"], 1)
                xs = np.linspace(joined["econ"].min(), joined["econ"].max(), 50)
                ax.plot(xs, slope * xs + intercept, lw=1.2, color="crimson")
            measure = "level" if row["measure"] == MEASURE_LEVEL else "change"
            ax.set_title(
                f"{row['indikator'][:26]} ({measure}, {row['lag_months']}m)\n"
                f"r={row['pearson_r']:+.2f}, q={row['q_value_BH']:.2f}",
                fontsize=9,
            )
            ax.set_xlabel("indicator (detrended)", fontsize=8)
            ax.set_ylabel("fertility (detrended)", fontsize=8)
            ax.tick_params(labelsize=7)
        for ax in axes[len(top):]:
            ax.axis("off")
        fig.tight_layout()
        path = outdir / "scatter_top.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(path)

    return written


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def parse_filters(items: list[str] | None) -> dict[str, str]:
    """Parse repeated --fert-filter COL=VALUE options into a dict."""
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(
                f"--fert-filter expects COL=VALUE, got {item!r}"
            )
        col, val = item.split("=", 1)
        out[col.strip()] = val.strip()
    return out


def find_default(candidates: list[str]) -> Path | None:
    """Look for a known filename in the working directory."""
    for name in candidates:
        p = Path(name)
        if p.exists():
            return p
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Correlate Swedish fertility with Konjunkturklockan indicators.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              %(prog)s --konjunktur konjunkturklockan.csv --fertility tfr.csv
              %(prog)s --konjunktur k.csv --fertility TAB1264_sv.csv \\
                       --fertility-format scb-long --detrend hp
              %(prog)s --fertility TAB1264_sv.csv --inspect
        """),
    )
    p.add_argument("--konjunktur", type=Path,
                   help="Konjunkturklockan CSV "
                        "(default: konjunkturklockan.csv in this directory).")
    p.add_argument("--fertility", type=Path,
                   help="Fertility CSV: TFR/ASFR series or a long SCB table "
                        "(default: Fruktbarhet_riket_kvinnor.csv here).")
    p.add_argument("--fertility-format", choices=["simple", "scb-long"],
                   default="simple",
                   help="'simple' = a flat year/value file, with or without a "
                        "header and with any number of extra dimension columns "
                        "(the default; handles Fruktbarhet_riket_kvinnor.csv). "
                        "'scb-long' = long SCB table needing aggregate-row "
                        "removal and summation, e.g. TAB1264.")
    p.add_argument("--fert-year-col", help="Override year column name.")
    p.add_argument("--fert-value-col", help="Override value column name.")
    p.add_argument("--fert-filter", action="append", metavar="COL=VALUE",
                   help="Keep only rows where COL equals VALUE. Repeatable. "
                        "Use to pick one region/sex when the file has several.")
    p.add_argument("--fert-agg", choices=["auto", "mean", "sum", "first"],
                   default="auto",
                   help="How to combine duplicate years: 'auto' means sum for "
                        "counts, mean for rates (default).")
    p.add_argument("--fert-dim-cols", nargs="*",
                   help="scb-long only: dimension columns to screen for "
                        "aggregate rows.")
    p.add_argument("--keep-aggregates", action="store_true",
                   help="Do NOT drop SCB aggregate/total rows (rarely correct).")
    p.add_argument("--inspect", action="store_true",
                   help="Print the fertility file's schema and exit.")

    p.add_argument("--lags", type=int, nargs="+", default=[0, 6, 12, 18, 24, 36],
                   help="Extra lag in months before the conception window "
                        "(default: 0 6 12 18 24 36).")
    p.add_argument("--gestation-months", type=int, default=9,
                   help="Months from conception to birth (default: 9).")
    p.add_argument("--window-months", type=int, default=12,
                   help="Length of the exposure window (default: 12).")
    p.add_argument("--birth-month", type=int, default=7,
                   help="Mean birth month within the year (default: 7).")
    p.add_argument("--detrend", choices=["diff", "linear", "hp", "none"],
                   default="diff",
                   help="Detrending applied to both series (default: diff).")
    p.add_argument("--min-years", type=int, default=10,
                   help="Minimum overlapping years to report a correlation.")
    p.add_argument("--min-coverage", type=float, default=0.75,
                   help="Fraction of the window that must be observed (0-1).")
    p.add_argument("--n-boot", type=int, default=2000,
                   help="Bootstrap replicates (0 disables CIs).")
    p.add_argument("--seed", type=int, default=0, help="Bootstrap RNG seed.")
    p.add_argument("--outdir", type=Path, default=Path("results"),
                   help="Output directory (default: results/).")
    p.add_argument("--no-plots", action="store_true", help="Skip figures.")
    p.add_argument("--robustness", action="store_true",
                   help="Also re-run every correlation under each detrending "
                        "method and report which results keep their sign. "
                        "Strongly recommended before quoting any number.")
    p.add_argument("--robustness-methods", nargs="+",
                   default=["diff", "linear", "hp"],
                   help="Detrending methods for --robustness "
                        "(default: diff linear hp).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.fertility is None:
        args.fertility = find_default(
            ["Fruktbarhet_riket_kvinnor.csv", "fruktbarhet_riket_kvinnor.csv"]
        )
    if args.fertility is None:
        print(
            "error: no fertility file given and none found in this directory. "
            "Pass --fertility.",
            file=sys.stderr,
        )
        return 2
    if not args.fertility.exists():
        print(f"error: fertility file not found: {args.fertility}", file=sys.stderr)
        return 2

    if args.inspect:
        inspect_fertility_file(args.fertility)
        return 0

    if args.konjunktur is None:
        args.konjunktur = find_default(["konjunkturklockan.csv", "Konjunkturklockan.csv"])
    if args.konjunktur is None:
        print(
            "error: no Konjunkturklockan file given and none found in this "
            "directory. Pass --konjunktur.",
            file=sys.stderr,
        )
        return 2
    if not args.konjunktur.exists():
        print(f"error: konjunktur file not found: {args.konjunktur}", file=sys.stderr)
        return 2

    monthly = load_konjunktur(args.konjunktur)

    if args.fertility_format == "simple":
        fertility = load_fertility_series(
            args.fertility,
            args.fert_year_col,
            args.fert_value_col,
            filters=parse_filters(args.fert_filter),
            agg=args.fert_agg,
        )
    else:
        fertility = load_fertility_scb_long(
            args.fertility,
            args.fert_year_col,
            args.fert_value_col,
            args.fert_dim_cols,
            drop_aggregates=not args.keep_aggregates,
        )

    if len(fertility) < args.min_years:
        print(
            f"error: fertility series has only {len(fertility)} years; "
            f"need at least --min-years ({args.min_years}).",
            file=sys.stderr,
        )
        return 1

    econ_years = {p.year for p in monthly.index}
    overlap = sorted(set(fertility.index) & econ_years)
    if len(overlap) < args.min_years:
        print(
            f"error: only {len(overlap)} years overlap between the fertility "
            f"series ({fertility.index.min()}-{fertility.index.max()}) and the "
            f"economic data ({min(econ_years)}-{max(econ_years)}).",
            file=sys.stderr,
        )
        return 1
    # Drop fertility years the exposure windows cannot reach anyway.
    fertility = fertility.loc[
        (fertility.index >= min(econ_years)) & (fertility.index <= max(econ_years) + 1)
    ]

    spec = ExposureSpec(
        gestation_months=args.gestation_months,
        window_months=args.window_months,
        lag_months=0,
        birth_month=args.birth_month,
    )

    print(
        f"[analysis] {len(fertility)} fertility years, "
        f"{monthly.shape[1]} series, lags {args.lags}, detrend={args.detrend}"
    )

    results, panels, fert_detrended = run_analysis(
        monthly=monthly,
        fertility=fertility,
        lags=args.lags,
        spec_base=spec,
        detrend_method=args.detrend,
        min_years=args.min_years,
        min_coverage=args.min_coverage,
        n_boot=args.n_boot,
        seed=args.seed,
    )

    args.outdir.mkdir(parents=True, exist_ok=True)

    report = format_report(results, fertility, args.detrend, spec, args.lags)
    print("\n" + report)
    (args.outdir / "top_findings.txt").write_text(report, encoding="utf-8")

    if not results.empty:
        results.drop(columns=["abs_r"]).to_csv(
            args.outdir / "correlations.csv", index=False, encoding="utf-8"
        )
        best_lag = results.iloc[0]["lag_months"]
        panels[best_lag].to_csv(
            args.outdir / "exposure_panel.csv", encoding="utf-8"
        )
        pd.DataFrame(
            {"fertility": fertility, "fertility_detrended": fert_detrended}
        ).to_csv(args.outdir / "fertility_series.csv", index_label="year",
                 encoding="utf-8")

        if not args.no_plots:
            for path in make_plots(
                results, panels, fert_detrended, args.detrend, args.outdir
            ):
                print(f"[plots] wrote {path}")

    if args.robustness:
        print("\n[robustness] re-running under each detrending method...")
        summary = run_specification_curve(
            monthly=monthly,
            fertility=fertility,
            lags=args.lags,
            spec_base=spec,
            methods=args.robustness_methods,
            min_years=args.min_years,
            min_coverage=args.min_coverage,
            seed=args.seed,
        )
        robustness_report = format_robustness(summary, args.robustness_methods)
        print("\n" + robustness_report)
        (args.outdir / "robustness.txt").write_text(
            robustness_report, encoding="utf-8"
        )
        if not summary.empty:
            summary.to_csv(
                args.outdir / "specification_curve.csv", index=False, encoding="utf-8"
            )

    print(f"\nWrote outputs to {args.outdir.resolve()}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())