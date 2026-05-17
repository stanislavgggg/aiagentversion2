"""
AI Service — Claude with Composio MCP.
Claude сам тянет данные из Mailchimp через MCP.
Бэкенд просто передаёт запросы и хранит историю чата.
"""
import anthropic
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services.db import GeneratedContent

settings = get_settings()

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

GEO_LANGUAGES = {
    "ES": "Spanish",
    "HR": "Croatian",
    "LT": "Lithuanian",
    "LV": "Latvian",
    "RS": "Serbian",
}

SYSTEM_PROMPT = """You are an expert email marketing AI assistant for an iGaming affiliate company.

You have LIVE access to the company's Mailchimp account via tools. 
ALWAYS use your Mailchimp tools to fetch real data before answering any question about campaigns.
Never guess or make up campaign data - always fetch it first.

Company context:
- GEOs: Spain (ES), Croatia (HR), Serbia (RS), Lithuania (LT), Latvia (LV)
- Audience types: Casino, Sportsbook, VIP
- Goal: maximize FTDs (first-time deposits) and revenue, not just open rates

When analyzing campaigns:
1. Fetch real data via Mailchimp tools
2. Find patterns: subject lines, open rates, CTR, GEO, audience, send time
3. Give specific data-backed insights with actual numbers

When generating content:
1. First fetch top performing campaigns for that GEO/audience
2. Base new content on proven patterns from the real data
3. Write in the correct language for the GEO
4. Use urgency, exclusivity, sports/casino hooks that worked before

Always respond in the same language the user writes in (Russian or English).
Reference actual campaign names and numbers when possible.
"""


def _get_mcp_servers() -> list[dict]:
    """Return Composio MCP server config for Claude API call."""
    return [
        {
            "type": "url",
            "url": settings.composio_mcp_url,
            "name": "mailchimp",
            "authorization_token": settings.composio_api_key,
        }
    ]


async def chat_with_mcp(
    messages: list[dict],
    geo: Optional[str] = None,
) -> str:
    """
    Send messages to Claude with Composio MCP.
    Claude fetches Mailchimp data itself via MCP tools.
    """
    system = SYSTEM_PROMPT
    if geo:
        system += f"\n\nFocus this analysis specifically on GEO: {geo} ({GEO_LANGUAGES.get(geo, geo)})."

    response = await client.beta.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system,
        messages=messages,
        mcp_servers=_get_mcp_servers(),
        betas=["mcp-client-2025-04-04"],
    )

    text_parts = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(text_parts) if text_parts else "No response generated."


async def generate_content(
    content_type: str,
    geo: str,
    audience_type: str,
    offer: str,
    db: AsyncSession,
    extra: str = "",
) -> dict:
    """
    Generate email content. Claude fetches top campaigns via MCP first,
    then generates based on real winning patterns.
    """
    language = GEO_LANGUAGES.get(geo, "English")

    prompts = {
        "newsletter": f"""
Use your Mailchimp tools to fetch the top 10 campaigns by open rate and CTR for {geo} {audience_type} audience.

Then generate a complete newsletter based on what actually worked:
- GEO: {geo} ({language})
- Audience: {audience_type}
- Offer: {offer}
{f'- Extra: {extra}' if extra else ''}

Return ONLY valid JSON (no markdown):
{{
  "subject_lines": ["option1", "option2", "option3"],
  "preview_text": "...",
  "body": "full newsletter body in {language}",
  "ctas": ["CTA 1", "CTA 2", "CTA 3"],
  "send_recommendation": "best day/time based on our historical data",
  "based_on": ["list campaign names you referenced"]
}}
""",
        "subject_lines": f"""
Fetch our best performing campaigns for {geo} {audience_type} from Mailchimp.
Look at what subject lines got the highest open rates.

Generate 5 new subject lines for offer: {offer}
Language: {language}

Return ONLY valid JSON (no markdown):
[{{"subject": "...", "style": "urgency|curiosity|offer|emoji|personalization", "reasoning": "why based on our data"}}]
""",
        "ab_test": f"""
Fetch campaign data for {geo} {audience_type} from Mailchimp.
Identify what we haven't tested yet or what showed variance.

Design an A/B test for: {offer}

Return ONLY valid JSON (no markdown):
{{
  "test_element": "subject_line|send_time|cta|offer_framing",
  "variant_a": {{"label": "Control", "content": "...", "reasoning": "..."}},
  "variant_b": {{"label": "Challenger", "content": "...", "reasoning": "..."}},
  "success_metric": "open_rate|ctr|conversions",
  "expected_lift": "X%",
  "duration_days": 7,
  "split": "50/50",
  "reasoning": "based on patterns in our data..."
}}
""",
        "ctas": f"""
Fetch our top CTR campaigns for {geo} {audience_type} from Mailchimp.
Analyze what CTA language drove the most clicks.

Generate 5 CTA button texts for: {offer}
Language: {language}, max 5 words each.

Return ONLY valid JSON (no markdown):
[{{"cta": "...", "style": "action|urgency|benefit|curiosity", "reasoning": "..."}}]
""",
    }

    prompt = prompts.get(content_type, prompts["newsletter"])

    response = await client.beta.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        mcp_servers=_get_mcp_servers(),
        betas=["mcp-client-2025-04-04"],
    )

    raw = "\n".join(
        block.text for block in response.content if hasattr(block, "text")
    )

    try:
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(clean)
    except Exception:
        result = {"raw": raw}

    # Persist to DB
    record = GeneratedContent(
        content_type=content_type,
        geo=geo,
        audience_type=audience_type,
        language=language,
        prompt_used=f"{content_type}: geo={geo}, audience={audience_type}, offer={offer}",
        result=json.dumps(result) if not isinstance(result, str) else result,
    )
    db.add(record)
    await db.commit()

    return result
