"""
FinAgent org-level content safety guardrail for LiteLLM proxy.

Blocks four harm categories on every request regardless of team/org:
  adult_content    — pornography, CSAM, explicit sexual material
  suicide_self_harm — methods, encouragement, detailed how-to
  medical_advice   — diagnosis, prescription, treatment recommendations
  violence         — weapon synthesis, attack instructions
"""

import re
from typing import Any, Dict, List, Literal, Optional

from fastapi import HTTPException
from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import UserAPIKeyAuth

# ---------------------------------------------------------------------------
# Pattern registry
# Each category has a list of compiled regexes and a user-facing message.
# ---------------------------------------------------------------------------

_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "adult_content": {
        "patterns": [
            r"\b(pornograph\w*|explicit\s+sex(ual)?\s+content|nude\s+photo|erotic\s+content|adult\s+film|XXX\s+content)\b",
            r"\b(sexual\s+exploit\w*|child\s+abuse\s+material|CSAM|child\s+pornograph\w*)\b",
            r"\b(generate|create|write|describe)\b.{0,60}\b(nude|naked|explicit|erotic|sexual)\b",
        ],
        "status_code": 400,
        "message": (
            "Request blocked: adult or explicit sexual content is not permitted. "
            "FinAgent is a financial intelligence platform."
        ),
    },
    "suicide_self_harm": {
        "patterns": [
            r"\b(how\s+(to|do\s+I|can\s+I)\s+(kill|hang|shoot|poison|strangle)\s+(myself|yourself|oneself))\b",
            r"\b(suicide\s+method|self[\-\s]harm\s+method|ways?\s+to\s+(commit\s+suicide|end\s+(my|your)\s+life))\b",
            r"\b(lethal\s+dose\s+of|overdose\s+on\s+\w+|pills?\s+to\s+(die|kill\s+myself))\b",
            r"\b(best\s+(way|method)\s+to\s+(die|commit\s+suicide|end\s+it\s+all|take\s+my\s+(own\s+)?life))\b",
            r"\b(how\s+to\s+(cut|harm|injure)\s+(myself|yourself)\s+(deeply|to\s+bleed|without\s+pain))\b",
            r"\b(want(ing)?\s+to\s+(die|end\s+(my|it\s+all))|no\s+reason\s+to\s+(live|go\s+on))\b",
        ],
        "status_code": 400,
        "message": (
            "Request blocked. If you or someone you know is in crisis, please reach out:\n"
            "  • National Suicide Prevention Lifeline: 988 (call or text, US)\n"
            "  • Crisis Text Line: text HOME to 741741\n"
            "  • International resources: https://www.befrienders.org"
        ),
    },
    "medical_advice": {
        "patterns": [
            r"\b(diagnose\s+(me|my\s+\w+)|what\s+(disease|illness|condition)\s+do\s+I\s+have)\b",
            r"\b(prescribe\s+(me|medication)|what\s+(medication|drug|medicine)\s+should\s+I\s+(take|use|try))\b",
            r"\b(should\s+I\s+(take|stop|change|increase|reduce|double)\s+(my\s+)?(medication|medicine|drug|pill|dose|dosage))\b",
            r"\b(is\s+(this|my)\s+(symptom|pain|rash|lump|condition)\s+(serious|dangerous|cancer|fatal|life[\-\s]threatening))\b",
            r"\b(do\s+I\s+(have|need)\s+(surgery|chemotherapy|radiation|dialysis|transplant|biopsy))\b",
            r"\b(treat\s+(my|this)\s+(cancer|diabetes|heart\s+\w+|infection|disease)\s+(with|using|by))\b",
            r"\b(home\s+remedy\s+for|cure\s+(my|for)\s+\w+\s+(disease|cancer|infection|condition))\b",
        ],
        "status_code": 400,
        "message": (
            "Request blocked: FinAgent cannot provide medical diagnoses, prescriptions, "
            "or treatment recommendations. Please consult a qualified healthcare professional."
        ),
    },
    "violence": {
        "patterns": [
            r"\b(how\s+to\s+(make|build|create|synthesize|manufacture)\s+(a\s+|an\s+)?(bomb|explosive|weapon|poison\s+gas|nerve\s+agent|bioweapon|biological\s+weapon))\b",
            r"\b(instructions?\s+(for|to)\s+(attack|harm|kill|torture|injure|assassinate)\s+(someone|a\s+person|people))\b",
            r"\b(how\s+to\s+(hurt|kill|torture|injure|assault|murder|stab|shoot)\s+(someone|a\s+person|people|my\s+\w+))\b",
            r"\b(step[\-\s]by[\-\s]step\s+(guide|instructions?)\s+(to|for)\s+(murder|assault|attack|violence|killing))\b",
        ],
        "status_code": 400,
        "message": (
            "Request blocked: content involving instructions for violence or causing harm "
            "is not permitted."
        ),
    },
}

# Pre-compile all patterns for efficiency
_COMPILED: Dict[str, List[re.Pattern]] = {
    cat: [re.compile(p, re.IGNORECASE) for p in cfg["patterns"]]
    for cat, cfg in _CATEGORIES.items()
}


def _extract_text(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return " ".join(parts)


def _check_text(text: str) -> Optional[Dict[str, Any]]:
    """Return the first category config that matches, or None."""
    for category, patterns in _COMPILED.items():
        for pattern in patterns:
            if pattern.search(text):
                return {"category": category, **_CATEGORIES[category]}
    return None


class ContentSafetyGuardrail(CustomGuardrail):
    """
    Org-level content safety guardrail — blocks harmful input and output.

    Registered in litellm-config.yaml with default_on: true so it applies
    to every API key / team / organization without any opt-out at the caller level.
    """

    # ------------------------------------------------------------------ #
    # Pre-call hook — screens the user's input messages before the LLM    #
    # ------------------------------------------------------------------ #
    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: Any,
        data: Dict[str, Any],
        call_type: Literal[
            "completion",
            "text_completion",
            "embeddings",
            "image_generation",
            "moderation",
            "audio_transcription",
            "pass_through_endpoint",
            "rerank",
        ],
    ) -> None:
        messages = data.get("messages", [])
        if not messages:
            return

        text = _extract_text(messages)
        violation = _check_text(text)
        if violation:
            key_hint = (
                user_api_key_dict.api_key[:8] + "..."
                if user_api_key_dict.api_key
                else "anon"
            )
            verbose_proxy_logger.warning(
                "ContentSafetyGuardrail [pre_call]: blocked category=%s key=%s",
                violation["category"],
                key_hint,
            )
            raise HTTPException(
                status_code=violation["status_code"],
                detail={
                    "error": "content_policy_violation",
                    "category": violation["category"],
                    "message": violation["message"],
                },
            )

    # ------------------------------------------------------------------ #
    # Post-call hook — screens the model's response before returning it   #
    # ------------------------------------------------------------------ #
    async def async_post_call_success_hook(
        self,
        data: Dict[str, Any],
        user_api_key_dict: UserAPIKeyAuth,
        response: Any,
    ) -> None:
        try:
            output_text = ""
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and choice.message:
                    output_text = choice.message.content or ""
                elif hasattr(choice, "text"):
                    output_text = choice.text or ""

            if not output_text:
                return

            violation = _check_text(output_text)
            if violation:
                verbose_proxy_logger.warning(
                    "ContentSafetyGuardrail [post_call]: output blocked category=%s",
                    violation["category"],
                )
                raise HTTPException(
                    status_code=violation["status_code"],
                    detail={
                        "error": "response_content_policy_violation",
                        "category": violation["category"],
                        "message": (
                            "The model response was blocked by content policy. "
                            "Please rephrase your request."
                        ),
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            verbose_proxy_logger.error(
                "ContentSafetyGuardrail [post_call]: unexpected error: %s", exc
            )
