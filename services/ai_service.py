"""
AI Service using Composio + Anthropic the RIGHT way.
- Composio provides tools via session.tools()
- Claude uses function calling (agentic loop)
- No MCP servers needed
"""
import anthropic
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

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

USER_FRIENDLY_ERRORS = {
    "authentication": "❌ Mailchimp connection issue. Please contact your admin.",
    "rate_limit": "⏳ Too many requests. Please wait a moment and try again.",
    "timeout": "⏳ Request timed out. Please try again.",
    "default": "❌ Something went wrong. Please try again.",
}

SYSTEM_PROMPT = """You are an expert email marketing AI assistant for an iGaming affiliate company.

You have access to tools to fetch LIVE data from Mailchimp.
ALWAYS use your tools to fetch real campaign data before answering questions.
Never guess or make up campaign data.

Company context:
- GEOs: Spain (ES), Croatia (HR), Serbia (RS), Lithuania (LT), Latvia (LV)
- Audience types: Casino, Sportsbook, VIP
- Goal: maximize FTDs (first-time deposits) and revenue, not just open rates

When analyzing campaigns:
1. Use tools to fetch real data from Mailchimp
2. Find patterns: subject lines, open rates, CTR, GEO, audience, send time
3. Give specific data-backed insights with actual numbers

When generating content:
1. First fetch top performing campaigns for that GEO/audience
2. Base new content on proven patterns from real historical data
3. Write in the correct language for the GEO
4. Use urgency, exclusivity, sports/casino hooks that worked before

Always respond in the same language the user writes in (Russian or English).
Reference actual campaign names and numbers when possible.
"""


def _friendly_error(error: Exception) -> str:
    msg = str(error).lower()
    if "authentication" in msg or "authorization" in msg or "token" in msg:
        return USER_FRIENDLY_ERRORS["authentication"]
    if "rate" in msg and "limit" in msg:
        return USER_FRIENDLY_ERRORS["rate_limit"]
    if "timeout" in msg:
        return USER_FRIENDLY_ERRORS["timeout"]
    return USER_FRIENDLY_ERRORS["default"]


def _get_composio_tools():
    """Get Mailchimp tools from Composio via AnthropicProvider."""
    try:
        logger.info("composio_import_start")
        from composio import Composio
        logger.info("composio_imported")
        from composio_anthropic import AnthropicProvider
        logger.info("composio_anthropic_imported")

        composio = Composio(
            api_key=settings.composio_api_key,
            provider=AnthropicProvider(),
        )
        logger.info("composio_client_created")
        session = composio.create(user_id=settings.composio_user_id)
        logger.info("composio_session_created")
        tools = session.tools(toolkits=["mailchimp"])
        logger.info("composio_tools_loaded", count=len(tools) if tools else 0)
        return composio, session, tools
    except Exception as e:
        logger.error("composio_tools_error", error=str(e), error_type=type(e).__name__)
        return None, None, []


async def _agentic_loop(
    messages: list[dict],
    system: str,
    tools: list,
    composio,
    user_id: str,
) -> str:
    """Run Claude agentic loop with tool calling."""
    import asyncio

    current_messages = messages.copy()

    for iteration in range(10):  # Max 10 tool call rounds
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system,
            tools=tools if tools else [],
            messages=current_messages,
        )

        if response.stop_reason == "end_turn":
            # Final text response
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            return "\n".join(text_parts)

        if response.stop_reason == "tool_use" and composio:
            # Handle tool calls via Composio
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

            # Execute tools via Composio (sync call in thread)
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: composio.provider.handle_tool_calls(
                    user_id=user_id, response=response
                ),
            )

            current_messages.append({"role": "assistant", "content": response.content})
            current_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_blocks[i].id,
                        "content": json.dumps(result),
                    }
                    for i, result in enumerate(results)
                ],
            })
            logger.info("tool_calls_executed", iteration=iteration, count=len(results))
        else:
            # No more tool calls
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            return "\n".join(text_parts)

    return "Max iterations reached. Please try a more specific question."


async def chat_with_mcp(
    messages: list[dict],
    geo: Optional[str] = None,
) -> str:
    """Chat with Claude using Composio tools for Mailchimp access."""
    system = SYSTEM_PROMPT
    if geo:
        system += f"\n\nFocus on GEO: {geo} ({GEO_LANGUAGES.get(geo, geo)})."

    composio, session, tools = _get_composio_tools()

    try:
        return await _agentic_loop(
            messages=messages,
            system=system,
            tools=tools,
            composio=composio,
            user_id=settings.composio_user_id,
        )
    except anthropic.APIStatusError as e:
        logger.error("chat_api_error", error=str(e))
        raise Exception(_friendly_error(e))
    except Exception as e:
        logger.error("chat_error", error=str(e))
        raise Exception(_friendly_error(e))


async def generate_content(
    content_type: str,
    geo: str,
    audience_type: str,
    offer: str,
    db: AsyncSession,
    extra: str = "",
) -> dict:
    """Generate email content using real Mailchimp data via Composio."""
    language = GEO_LANGUAGES.get(geo, "English")

    prompts = {
        "newsletter": f"""
Use your Mailchimp tools to fetch top 10 campaigns by open rate and CTR for {geo} {audience_type} audience.

Then generate a complete newsletter based on what actually worked:
- GEO: {geo} ({language}), Audience: {audience_type}, Offer: {offer}
{f'- Extra: {extra}' if extra else ''}

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
Generate 5 subject lines for: {offer} in {language}.

Return ONLY valid JSON (no markdown fences):
[{{"subject": "...", "style": "urgency|curiosity|offer|emoji", "reasoning": "why based on our data"}}]
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
  "reasoning": "based on our data..."
}}
""",
        "ctas": f"""
Fetch top CTR campaigns for {geo} {audience_type} from Mailchimp.
Generate 5 CTA button texts for: {offer} in {language}. Max 5 words each.

Return ONLY valid JSON (no markdown fences):
[{{"cta": "...", "style": "action|urgency|benefit|curiosity", "reasoning": "..."}}]
""",
    }

    composio, session, tools = _get_composio_tools()

    try:
        raw = await _agentic_loop(
            messages=[{"role": "user", "content": prompts.get(content_type, prompts["newsletter"])}],
            system=SYSTEM_PROMPT,
            tools=tools,
            composio=composio,
            user_id=settings.composio_user_id,
        )

        try:
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            result = json.loads(clean)
        except Exception:
            result = {"raw": raw}

    except Exception as e:
        logger.error("generate_error", error=str(e), content_type=content_type)
        raise Exception(_friendly_error(e))

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

    logger.info("generate_complete", content_type=content_type, geo=geo)
    return result
