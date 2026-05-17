"""
Production AI Service.
- Streaming responses (token by token)
- Retry logic with exponential backoff
- Graceful error messages for users
- Full logging
- MCP with Composio
"""
import anthropic
import json
from typing import Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import get_settings
from services.db import GeneratedContent
from services.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)

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
ALWAYS use your Mailchimp tools to fetch real data before answering questions about campaigns.
Never invent or guess campaign data — always fetch it first.

Company context:
- GEOs: Spain (ES), Croatia (HR), Serbia (RS), Lithuania (LT), Latvia (LV)
- Audience types: Casino, Sportsbook, VIP
- Goal: maximize FTDs (first-time deposits) and revenue, not just open rates

When analyzing campaigns:
1. Fetch real data via Mailchimp tools
2. Find patterns: subject lines, open rates, CTR, GEO, audience, send time
3. Give specific data-backed insights with actual numbers from the data

When generating content:
1. First fetch top performing campaigns for that GEO/audience
2. Base new content on proven patterns from real historical data
3. Write in the correct language for the GEO
4. Use urgency, exclusivity, sports/casino hooks that worked before

Always respond in the same language the user writes in (Russian or English).
Reference actual campaign names and numbers when possible.
Keep responses clear and actionable for non-technical email marketers.
"""

USER_FRIENDLY_ERRORS = {
    "authentication": "❌ Mailchimp connection issue. Please contact your admin.",
    "rate_limit": "⏳ Too many requests. Please wait a moment and try again.",
    "timeout": "⏳ Request timed out. Please try again.",
    "mcp": "❌ Cannot connect to Mailchimp right now. Please try again in a moment.",
    "default": "❌ Something went wrong. Please try again.",
}


def _get_mcp_servers() -> list[dict]:
    return [
        {
            "type": "url",
            "url": f"https://mcp.composio.dev/mailchimp?apiKey={settings.composio_api_key}",
            "name": "mailchimp",
        }
    ]


def _friendly_error(error: Exception) -> str:
    """Convert technical errors to user-friendly messages."""
    msg = str(error).lower()
    if "authentication" in msg or "authorization" in msg or "token" in msg:
        return USER_FRIENDLY_ERRORS["authentication"]
    if "rate" in msg and "limit" in msg:
        return USER_FRIENDLY_ERRORS["rate_limit"]
    if "timeout" in msg or "timed out" in msg:
        return USER_FRIENDLY_ERRORS["timeout"]
    if "mcp" in msg:
        return USER_FRIENDLY_ERRORS["mcp"]
    return USER_FRIENDLY_ERRORS["default"]


async def chat_stream(
    messages: list[dict],
    geo: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Stream AI response token by token.
    Yields Server-Sent Events formatted strings.
    """
    system = SYSTEM_PROMPT
    if geo:
        system += f"\n\nFocus analysis on GEO: {geo} ({GEO_LANGUAGES.get(geo, geo)})."

    logger.info("chat_stream_start", geo=geo, message_count=len(messages))

    try:
        async with client.beta.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system,
            messages=messages,
            mcp_servers=_get_mcp_servers(),
            betas=["mcp-client-2025-04-04"],
        ) as stream:
            async for text in stream.text_stream:
                yield f"data: {json.dumps({'text': text})}\n\n"

        yield f"data: {json.dumps({'done': True})}\n\n"
        logger.info("chat_stream_complete", geo=geo)

    except anthropic.APIStatusError as e:
        logger.error("chat_stream_api_error", error=str(e), status_code=e.status_code)
        error_msg = _friendly_error(e)
        yield f"data: {json.dumps({'error': error_msg})}\n\n"

    except anthropic.APITimeoutError:
        logger.error("chat_stream_timeout")
        yield f"data: {json.dumps({'error': USER_FRIENDLY_ERRORS['timeout']})}\n\n"

    except Exception as e:
        logger.error("chat_stream_unexpected_error", error=str(e))
        yield f"data: {json.dumps({'error': _friendly_error(e)})}\n\n"


async def chat_with_mcp(
    messages: list[dict],
    geo: Optional[str] = None,
) -> str:
    """
    Non-streaming chat for generate endpoints.
    With retry logic.
    """
    system = SYSTEM_PROMPT
    if geo:
        system += f"\n\nFocus analysis on GEO: {geo} ({GEO_LANGUAGES.get(geo, geo)})."

    for attempt in range(3):
        try:
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

        except anthropic.APIStatusError as e:
            logger.warning("chat_retry", attempt=attempt + 1, error=str(e))
            if attempt == 2:
                raise
            if e.status_code in (429, 529):
                import asyncio
                await asyncio.sleep(2 ** attempt)

        except Exception as e:
            logger.error("chat_error", error=str(e))
            if attempt == 2:
                raise
            import asyncio
            await asyncio.sleep(1)

    raise Exception("Max retries exceeded")


async def generate_content(
    content_type: str,
    geo: str,
    audience_type: str,
    offer: str,
    db: AsyncSession,
    extra: str = "",
) -> dict:
    language = GEO_LANGUAGES.get(geo, "English")

    prompts = {
        "newsletter": f"""
Use Mailchimp tools to fetch top 10 campaigns by open rate and CTR for {geo} {audience_type} audience.

Generate a complete newsletter based on what actually worked:
- GEO: {geo} ({language}), Audience: {audience_type}, Offer: {offer}
{f'- Extra context: {extra}' if extra else ''}

Return ONLY valid JSON (no markdown fences):
{{
  "subject_lines": ["option1", "option2", "option3"],
  "preview_text": "...",
  "body": "full newsletter body in {language}",
  "ctas": ["CTA 1", "CTA 2", "CTA 3"],
  "send_recommendation": "best day/time based on our data",
  "based_on": ["campaign names referenced"]
}}
""",
        "subject_lines": f"""
Fetch best performing campaigns for {geo} {audience_type} from Mailchimp.
Look at what subject lines got the highest open rates.

Generate 5 new subject lines for offer: {offer}
Language: {language}

Return ONLY valid JSON (no markdown fences):
[{{"subject": "...", "style": "urgency|curiosity|offer|emoji|personalization", "reasoning": "why based on our data"}}]
""",
        "ab_test": f"""
Fetch campaign data for {geo} {audience_type} from Mailchimp.

Design an A/B test for: {offer}

Return ONLY valid JSON (no markdown fences):
{{
  "test_element": "what to test",
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
Fetch top CTR campaigns for {geo} {audience_type} from Mailchimp.

Generate 5 CTA button texts for: {offer}
Language: {language}, max 5 words each.

Return ONLY valid JSON (no markdown fences):
[{{"cta": "...", "style": "action|urgency|benefit|curiosity", "reasoning": "..."}}]
""",
    }

    logger.info("generate_content_start", content_type=content_type, geo=geo, audience=audience_type)

    try:
        response = await client.beta.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompts.get(content_type, prompts["newsletter"])}],
            mcp_servers=_get_mcp_servers(),
            betas=["mcp-client-2025-04-04"],
        )

        raw = "\n".join(block.text for block in response.content if hasattr(block, "text"))

        try:
            clean = raw.strip()
            for fence in ["```json", "```"]:
                clean = clean.lstrip(fence)
            clean = clean.rstrip("```").strip()
            result = json.loads(clean)
        except Exception:
            result = {"raw": raw}

    except Exception as e:
        logger.error("generate_content_error", error=str(e), content_type=content_type)
        raise Exception(_friendly_error(e))

    # Persist
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

    logger.info("generate_content_complete", content_type=content_type, geo=geo)
    return result
