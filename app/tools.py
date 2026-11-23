"""The tools the agents call.

user_id and campaign_id always come from the run config, which the server fills in from the signed
login token. They are never tool arguments, so the model cannot be talked into another brand's data."""
import ast
import json
import operator
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from . import db, memory
from .creative import render_svg


def _ctx(config: RunnableConfig) -> tuple[str, str]:
    configurable = config.get("configurable", {})
    return configurable["user_id"], configurable["campaign_id"]


class AdVariant(BaseModel):
    angle: str = Field(description="The persuasion angle in 2 to 4 words, e.g. 'price', 'social proof'")
    headline: str = Field(description="Ad headline, at most 40 characters")
    primary_text: str = Field(description="Ad body text, 1 to 2 short sentences, at most 220 characters")
    cta: str = Field(description="Call-to-action button text, at most 18 characters")


@tool
def save_ad_variants(variants: list[AdVariant], config: RunnableConfig) -> str:
    """Save new ad copy variants for the current campaign. Returns the labels they were given."""
    user_id, campaign_id = _ctx(config)
    labels = []
    for variant in variants[:3]:
        labels.append(db.add_variant(user_id, campaign_id, variant.angle[:40], variant.headline[:60],
                                     variant.primary_text[:300], variant.cta[:22]))
    db.log(user_id, campaign_id, "variants_saved", ", ".join(labels))
    return f"Saved variants: {', '.join(labels)}"


@tool
def render_creative(label: str, layout: Literal["bold", "split", "minimal"],
                    bg_color: str, accent_color: str, motif: Literal["rings", "grid", "burst"],
                    badge: str, config: RunnableConfig) -> str:
    """Render the square ad creative for one variant of the current campaign.
    label: the variant label (A, B, C...). bg_color and accent_color: hex colours like #0b1020.
    badge: a short tag of at most 20 characters shown in the corner, e.g. 'NEW' or '20% OFF'."""
    user_id, campaign_id = _ctx(config)
    variant = next((v for v in db.list_variants(user_id, campaign_id) if v["label"] == label.upper().strip()), None)
    if not variant:
        return f"No variant with label {label} in this campaign."
    spec = {"layout": layout, "bg_color": bg_color, "accent_color": accent_color, "motif": motif, "badge": badge}
    business = (db.user_by_id(user_id) or {}).get("business", "")
    db.set_creative(user_id, campaign_id, variant["label"], spec,
                    render_svg(spec, variant["headline"], variant["cta"], business))
    return f"Creative rendered for variant {variant['label']}."


@tool
def get_campaign_results(config: RunnableConfig) -> str:
    """Read the performance of the current campaign: impressions, clicks, conversions and spend (PKR)
    for every variant, plus the campaign status and budget."""
    user_id, campaign_id = _ctx(config)
    campaign = db.get_campaign(user_id, campaign_id)
    if not campaign:
        return "Campaign not found."
    return json.dumps({
        "status": campaign["status"], "daily_budget_pkr": campaign["daily_budget"], "days": campaign["days"],
        "variants": [{"label": v["label"], "angle": v["angle"], "headline": v["headline"]}
                     for v in db.list_variants(user_id, campaign_id)],
        "results": db.list_results(user_id, campaign_id) or "No results yet: the campaign has not been launched.",
    })


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _evaluate(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.operand))
    raise ValueError("only numbers and + - * / % ** ( ) are allowed")


@tool
def calculator(expressions: list[str]) -> str:
    """Evaluate arithmetic expressions exactly. Use it for every metric: CTR = clicks / impressions * 100,
    CPC = spend / clicks, CPA = spend / conversions. Pass several expressions in one call."""
    lines = []
    for expression in expressions[:12]:
        try:
            lines.append(f"{expression} = {round(_evaluate(ast.parse(expression[:120], mode='eval').body), 4)}")
        except ZeroDivisionError:
            lines.append(f"{expression} = undefined (division by zero)")
        except Exception as error:
            lines.append(f"{expression} = error: {error}")
    return "\n".join(lines)


@tool
def save_recommendation(winner_label: str, summary: str, fixes: list[str], config: RunnableConfig) -> str:
    """Save your analysis of the results: the winning variant label, a one-sentence summary with the key
    numbers, and 2 to 3 concrete fixes to try next. Call this once, after computing the metrics."""
    user_id, campaign_id = _ctx(config)
    winner = winner_label.upper().strip()[:2]
    db.add_recommendation(user_id, campaign_id, winner, summary[:400], [fix[:200] for fix in fixes[:4]])
    variant = next((v for v in db.list_variants(user_id, campaign_id) if v["label"] == winner), None)
    if variant:
        memory.save_learning(user_id, campaign_id, {"winner_angle": variant["angle"], "summary": summary[:200]})
    db.log(user_id, campaign_id, "recommendation_saved", winner)
    return "Recommendation saved."


@tool
def save_brand_preference(preference: str, config: RunnableConfig) -> str:
    """Remember a standing instruction about how this brand wants its ads written, so it applies to every
    future campaign (e.g. 'never offer discounts', 'always write in Roman Urdu'). Only for lasting brand
    preferences. Never for payment details, passwords or one-off requests."""
    user_id, _ = _ctx(config)
    if memory.save_preference(user_id, preference):
        return "Saved to brand memory."
    return "Not saved: that looks like sensitive information, which is never stored."


COPY_TOOLS = [save_ad_variants]
CREATIVE_TOOLS = [render_creative]
ANALYST_TOOLS = [get_campaign_results, calculator, save_recommendation, save_brand_preference]
