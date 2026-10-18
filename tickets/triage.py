"""Classify a ticket with an OpenAI-compatible chat API, or keyword rules.

`LLM_API_KEY` empty means the keyword fallback runs immediately. Transport
failures (timeouts, HTTP 429, HTTP 5xx) raise `TriageTransientError` so the
Celery task can retry with exponential backoff. A bad payload or a 4xx other
than 429 is permanent: the task stores the keyword result instead of retrying.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

from tickets.models import Ticket

_CATEGORY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("refund", "invoice", "billing", "charge", "payment", "subscription"),
        Ticket.Category.BILLING,
    ),
    (
        ("password", "login", "log in", "sign in", "locked", "2fa", "mfa", "credential"),
        Ticket.Category.ACCESS,
    ),
    (
        ("crash", "error", "bug", "exception", "timeout", "500", "api", "outage"),
        Ticket.Category.TECHNICAL,
    ),
    (("account", "profile", "username"), Ticket.Category.ACCOUNT),
)
_URGENT_TERMS = ("urgent", "asap", "outage", "down", "data loss")
_PRIORITY_FOR_CATEGORY = {
    Ticket.Category.BILLING: Ticket.Priority.HIGH,
    Ticket.Category.ACCESS: Ticket.Priority.HIGH,
    Ticket.Category.TECHNICAL: Ticket.Priority.HIGH,
    Ticket.Category.ACCOUNT: Ticket.Priority.MEDIUM,
    Ticket.Category.GENERAL: Ticket.Priority.LOW,
}
_REPLIES = {
    Ticket.Category.BILLING: (
        "Thanks for contacting us about billing. An agent will review the charge "
        "and follow up with the next step."
    ),
    Ticket.Category.ACCESS: (
        "Thanks for reporting this access issue. An agent will verify the account "
        "and help you sign in."
    ),
    Ticket.Category.TECHNICAL: (
        "Thanks for the report. An agent will investigate the technical issue "
        "and update this ticket."
    ),
    Ticket.Category.ACCOUNT: (
        "Thanks for the account request. An agent will review it and reply here."
    ),
    Ticket.Category.GENERAL: (
        "Thanks for reaching out. An agent will review this ticket and respond shortly."
    ),
}

_SYSTEM_PROMPT = (
    "You triage helpdesk tickets. Reply with a single JSON object and no other text. "
    'Keys: "category" (one of general, billing, technical, account, access), '
    '"priority" (one of low, medium, high, urgent), '
    '"suggested_reply" (one or two sentences an agent could send first).'
)


class TriageTransientError(Exception):
    """Retryable failure talking to the model endpoint."""


class TriagePermanentError(Exception):
    """The endpoint answered, but the result cannot be used."""


@dataclass(frozen=True)
class TriageResult:
    category: str
    priority: str
    suggested_reply: str
    source: str
    model: str


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def fallback_classify(title: str, description: str) -> TriageResult:
    text = f"{title}\n{description}".lower()
    category = Ticket.Category.GENERAL
    for terms, candidate in _CATEGORY_RULES:
        if any(_contains_term(text, term) for term in terms):
            category = candidate
            break
    if any(_contains_term(text, term) for term in _URGENT_TERMS):
        priority = Ticket.Priority.URGENT
    else:
        priority = _PRIORITY_FOR_CATEGORY[category]
    reply = _REPLIES[category]
    if priority == Ticket.Priority.URGENT:
        reply = f"We have flagged this as urgent. {reply}"
    return TriageResult(
        category=category,
        priority=priority,
        suggested_reply=reply,
        source=Ticket.TriageSource.FALLBACK,
        model="",
    )


def _strip_fences(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _result_from_content(content: str) -> TriageResult:
    try:
        data = json.loads(_strip_fences(content))
    except json.JSONDecodeError as exc:
        raise TriagePermanentError("llm response was not json") from exc
    if not isinstance(data, dict):
        raise TriagePermanentError("llm response was not an object")
    category = data.get("category")
    priority = data.get("priority")
    reply = data.get("suggested_reply")
    if category not in Ticket.Category.values:
        raise TriagePermanentError(f"invalid category {category}")
    if priority not in Ticket.Priority.values:
        raise TriagePermanentError(f"invalid priority {priority}")
    if not isinstance(reply, str) or not reply.strip():
        raise TriagePermanentError("empty suggested_reply")
    return TriageResult(
        category=category,
        priority=priority,
        suggested_reply=reply.strip(),
        source=Ticket.TriageSource.LLM,
        model=settings.LLM_MODEL,
    )


def llm_classify(title: str, description: str) -> TriageResult:
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Title: {title}\n\nDescription:\n{description}"},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.LLM_TIMEOUT) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        if exc.code == 429 or 500 <= exc.code <= 599:
            raise TriageTransientError(f"llm http {exc.code}") from exc
        raise TriagePermanentError(f"llm http {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise TriageTransientError("llm unreachable") from exc

    try:
        body = json.loads(raw)
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise TriagePermanentError("llm response missing message content") from exc
    return _result_from_content(content)


def classify(title: str, description: str) -> TriageResult:
    if not str(settings.LLM_API_KEY).strip():
        return fallback_classify(title, description)
    return llm_classify(title, description)
