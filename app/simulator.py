"""Sandbox ad network.

AdForge has no real Meta or Google ad account in this build, so "launching" a campaign runs it
through this simulator. Results are deterministic per variant (same ad, same numbers), which keeps
the demo and the benchmark repeatable. Swapping this module for a real ads API is the only change
needed to go live."""
import hashlib
import re


def simulate(variant: dict, spend: float) -> dict:
    seed = int(hashlib.sha256((variant["id"] + variant["headline"]).encode()).hexdigest(), 16)
    r1, r2, r3 = (seed % 1000) / 1000, ((seed >> 20) % 1000) / 1000, ((seed >> 40) % 1000) / 1000

    cpm = 180 + 120 * r1                      # PKR per 1000 impressions
    ctr = 0.008 + 0.020 * r2
    if len(variant["headline"]) <= 40:        # short headlines get read
        ctr += 0.004
    if re.search(r"\d", variant["headline"]):  # a concrete number earns clicks
        ctr += 0.003
    cvr = 0.02 + 0.05 * r3

    impressions = int(spend / cpm * 1000)
    clicks = int(impressions * ctr)
    return {"impressions": impressions, "clicks": clicks,
            "conversions": int(clicks * cvr), "spend": round(spend, 2)}
