"""Generate the reference QuantStats HTML tear sheet on synthetic GBM returns."""
import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
import quantstats as qs

qs.extend_pandas()

SEED = 42
rng = np.random.default_rng(SEED)

# ~2 years of business days
idx = pd.bdate_range(start="2024-08-23", end="2026-08-21")
n = len(idx)

# Geometric Brownian motion daily log-returns: mu annual drift, sigma annual vol
def gbm_returns(mu, sigma, n, rng):
    dt = 1.0 / 252.0
    log_r = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * rng.standard_normal(n)
    return np.expm1(log_r)  # simple daily returns

# Strategy: 12% drift, 18% vol; Benchmark: 8% drift, 15% vol (correlated)
dt = 1.0 / 252.0
z_common = rng.standard_normal(n)
z_strat = 0.7 * z_common + np.sqrt(1 - 0.7**2) * rng.standard_normal(n)
z_bench = z_common

mu_s, sig_s = 0.26, 0.18
mu_b, sig_b = 0.08, 0.15
strat = np.expm1((mu_s - 0.5 * sig_s**2) * dt + sig_s * np.sqrt(dt) * z_strat)
bench = np.expm1((mu_b - 0.5 * sig_b**2) * dt + sig_b * np.sqrt(dt) * z_bench)

returns = pd.Series(strat, index=idx, name="Strategy")
benchmark = pd.Series(bench, index=idx, name="Benchmark")

out = "/home/user/troyrhinehart/casino/references/quantstats/reference_tearsheet.html"
qs.reports.html(
    returns,
    benchmark=benchmark,
    rf=0.0,
    title="Reference Strategy Tearsheet",
    output=out,
    download_filename=out,
)
print("written:", out)
print("n_days:", n, "period:", idx[0].date(), "->", idx[-1].date())
print("strategy CAGR:", qs.stats.cagr(returns))
print("benchmark CAGR:", qs.stats.cagr(benchmark))
print("sharpe:", qs.stats.sharpe(returns))
