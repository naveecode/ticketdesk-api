import io
import json
import urllib.error

import pytest

from tickets.models import Ticket
from tickets.tasks import handle_triage, run_triage, triage_ticket
from tickets.triage import TriageTransientError, classify, fallback_classify

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("title", "description", "category", "priority"),
    [
        (
            "Invoice charged twice",
            "There is a duplicate charge on the invoice.",
            Ticket.Category.BILLING,
            Ticket.Priority.HIGH,
        ),
        (
            "Cannot reset my password",
            "Login stays locked.",
            Ticket.Category.ACCESS,
            Ticket.Priority.HIGH,
        ),
        (
            "Checkout API returning 500",
            "Customers see an error when the API times out.",
            Ticket.Category.TECHNICAL,
            Ticket.Priority.HIGH,
        ),
        (
            "Update my profile",
            "Please change the company name on the account profile.",
            Ticket.Category.ACCOUNT,
            Ticket.Priority.MEDIUM,
        ),
        (
            "How do I export a report?",
            "Looking for the steps to download last month.",
            Ticket.Category.GENERAL,
            Ticket.Priority.LOW,
        ),
        (
            "Production API outage",
            "The public API has been down since 09:10.",
            Ticket.Category.TECHNICAL,
            Ticket.Priority.URGENT,
        ),
    ],
)
def test_keyword_fallback_is_deterministic(title, description, category, priority):
    first = fallback_classify(title, description)
    second = fallback_classify(title, description)
    assert first == second
    assert first.category == category
    assert first.priority == priority
    assert first.source == Ticket.TriageSource.FALLBACK
    assert first.model == ""
    assert first.suggested_reply
    if priority == Ticket.Priority.URGENT:
        assert first.suggested_reply.startswith("We have flagged this as urgent.")


def test_run_triage_without_a_key_stores_fallback_and_latency(settings, customer, make_ticket):
    settings.LLM_API_KEY = ""
    ticket = make_ticket(
        customer,
        title="Invoice charged twice",
        description="There is a duplicate charge on the invoice.",
        status=Ticket.Status.IN_PROGRESS,
    )
    run_triage(ticket.id)
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.IN_PROGRESS
    assert ticket.category == Ticket.Category.BILLING
    assert ticket.priority == Ticket.Priority.HIGH
    assert ticket.triage_status == Ticket.TriageStatus.COMPLETED
    assert ticket.triage_source == Ticket.TriageSource.FALLBACK
    assert ticket.triage_latency_ms is not None
    assert ticket.triage_latency_ms >= 0
    assert ticket.triaged_at is not None
    assert ticket.suggested_reply


def test_completed_triage_is_not_repeated(customer, make_ticket):
    ticket = make_ticket(
        customer,
        category=Ticket.Category.BILLING,
        priority=Ticket.Priority.LOW,
        triage_status=Ticket.TriageStatus.COMPLETED,
    )
    run_triage(ticket.id)
    ticket.refresh_from_db()
    assert ticket.category == Ticket.Category.BILLING
    assert ticket.priority == Ticket.Priority.LOW


def test_missing_ticket_is_ignored():
    run_triage(10**9)


def _response(payload: dict):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    return FakeResponse()


def test_llm_result_is_stored(monkeypatch, settings, customer, make_ticket):
    settings.LLM_API_KEY = "sk-test"
    settings.LLM_MODEL = "gpt-test"
    settings.LLM_BASE_URL = "https://llm.example/v1/"
    settings.LLM_TIMEOUT = 5
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode())
        content = json.dumps(
            {
                "category": "account",
                "priority": "medium",
                "suggested_reply": "We will update the profile.",
            }
        )
        return _response({"choices": [{"message": {"content": f"```json\n{content}\n```"}}]})

    monkeypatch.setattr("tickets.triage.urllib.request.urlopen", fake_urlopen)
    ticket = make_ticket(customer)
    run_triage(ticket.id)
    ticket.refresh_from_db()

    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["timeout"] == 5
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "gpt-test"
    assert captured["body"]["temperature"] == 0
    assert ticket.category == Ticket.Category.ACCOUNT
    assert ticket.priority == Ticket.Priority.MEDIUM
    assert ticket.suggested_reply == "We will update the profile."
    assert ticket.triage_source == Ticket.TriageSource.LLM
    assert ticket.triage_model == "gpt-test"
    assert ticket.triage_latency_ms >= 0
    assert ticket.triage_error == ""


def test_invalid_llm_payload_falls_back(monkeypatch, settings, customer, make_ticket):
    settings.LLM_API_KEY = "sk-test"

    def fake_urlopen(request, timeout):
        return _response({"choices": [{"message": {"content": '{"category": "spaceship"}'}}]})

    monkeypatch.setattr("tickets.triage.urllib.request.urlopen", fake_urlopen)
    ticket = make_ticket(
        customer,
        title="Invoice charged twice",
        description="There is a duplicate charge on the invoice.",
    )
    run_triage(ticket.id)
    ticket.refresh_from_db()
    assert ticket.triage_source == Ticket.TriageSource.FALLBACK
    assert ticket.category == Ticket.Category.BILLING
    assert "invalid category" in ticket.triage_error


def test_http_400_falls_back_without_retry(monkeypatch, settings, customer, make_ticket):
    settings.LLM_API_KEY = "sk-test"

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "bad request",
            None,
            io.BytesIO(b"nope"),
        )

    monkeypatch.setattr("tickets.triage.urllib.request.urlopen", fake_urlopen)
    ticket = make_ticket(
        customer,
        title="How do I export a report?",
        description="Just the steps please.",
    )
    run_triage(ticket.id)
    ticket.refresh_from_db()
    assert ticket.triage_source == Ticket.TriageSource.FALLBACK
    assert ticket.category == Ticket.Category.GENERAL
    assert ticket.triage_error == "llm http 400"


def test_transient_failure_requests_backoff_then_falls_back(
    monkeypatch, settings, customer, make_ticket
):
    settings.LLM_API_KEY = "sk-test"
    ticket = make_ticket(
        customer,
        title="Production API outage",
        description="The public API has been down since 09:10.",
    )

    def explode(title, description):
        raise TriageTransientError("llm http 503")

    monkeypatch.setattr("tickets.tasks.classify", explode)
    requested = {}

    def retry_fn(exc, countdown):
        requested["error"] = str(exc)
        requested["countdown"] = countdown

    outcome = handle_triage(ticket.id, retries=1, max_retries=3, retry_fn=retry_fn)
    assert outcome == "retry"
    assert requested == {"error": "llm http 503", "countdown": 2}
    ticket.refresh_from_db()
    assert ticket.triage_status == Ticket.TriageStatus.PENDING

    finished = handle_triage(
        ticket.id,
        retries=3,
        max_retries=3,
        retry_fn=lambda *_args: pytest.fail("should not retry"),
    )
    assert finished == "fallback"
    ticket.refresh_from_db()
    assert ticket.triage_status == Ticket.TriageStatus.COMPLETED
    assert ticket.triage_source == Ticket.TriageSource.FALLBACK
    assert ticket.priority == Ticket.Priority.URGENT
    assert ticket.triage_error == "llm http 503"


def test_celery_task_raises_retry(monkeypatch, customer, make_ticket):
    from celery.exceptions import Retry

    ticket = make_ticket(customer)

    def explode(*args, **kwargs):
        raise TriageTransientError("llm unreachable")

    monkeypatch.setattr("tickets.tasks.run_triage", explode)
    with pytest.raises(Retry):
        triage_ticket.apply(args=[ticket.id], throw=True)


def test_create_enqueues_triage_and_update_does_not(
    customer_client, customer, make_ticket, monkeypatch
):
    queued = []

    def capture(ticket_id):
        queued.append(ticket_id)

    monkeypatch.setattr("tickets.signals.triage_ticket.delay", capture)

    response = customer_client.post(
        "/api/tickets/",
        {
            "title": "Need a hand",
            "description": "The export button does nothing when I click it.",
        },
        format="json",
    )
    assert response.status_code == 201
    assert queued == [response.data["id"]]

    ticket = make_ticket(customer)
    queued.clear()
    ticket.title = "Need a hand today"
    ticket.save()
    assert queued == []


def test_handle_triage_success_uses_the_fallback(settings, customer, make_ticket):
    settings.LLM_API_KEY = ""
    ticket = make_ticket(
        customer,
        title="How do I export a report?",
        description="Looking for the steps to download last month.",
    )
    outcome = handle_triage(ticket.id, retries=0, max_retries=3, retry_fn=lambda *_args: None)
    assert outcome == "ok"
    ticket.refresh_from_db()
    assert ticket.triage_source == Ticket.TriageSource.FALLBACK
    assert ticket.category == Ticket.Category.GENERAL


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not-json", "llm response was not json"),
        ("[]", "llm response was not an object"),
        (
            '{"category": "general", "priority": "nope", "suggested_reply": "Hello there."}',
            "invalid priority nope",
        ),
        (
            '{"category": "general", "priority": "low", "suggested_reply": "   "}',
            "empty suggested_reply",
        ),
    ],
)
def test_bad_model_json_falls_back(monkeypatch, settings, customer, make_ticket, content, message):
    settings.LLM_API_KEY = "sk-test"

    def fake_urlopen(request, timeout):
        return _response({"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("tickets.triage.urllib.request.urlopen", fake_urlopen)
    ticket = make_ticket(customer)
    run_triage(ticket.id)
    ticket.refresh_from_db()
    assert ticket.triage_source == Ticket.TriageSource.FALLBACK
    assert ticket.triage_error == message


def test_blank_api_key_uses_the_keyword_fallback(settings):
    settings.LLM_API_KEY = "   "
    result = classify("Invoice charged twice", "There is a duplicate charge on the invoice.")
    assert result.source == Ticket.TriageSource.FALLBACK
    assert result.category == Ticket.Category.BILLING


def test_llm_transport_errors_are_retryable(monkeypatch, settings):
    settings.LLM_API_KEY = "sk-test"
    settings.LLM_BASE_URL = "https://llm.example/v1"

    def raise_429(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "slow", None, io.BytesIO(b""))

    monkeypatch.setattr("tickets.triage.urllib.request.urlopen", raise_429)
    with pytest.raises(TriageTransientError, match="llm http 429"):
        classify("Need a hand", "The export button does nothing when I click it.")

    def raise_url(request, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr("tickets.triage.urllib.request.urlopen", raise_url)
    with pytest.raises(TriageTransientError, match="llm unreachable"):
        classify("Need a hand", "The export button does nothing when I click it.")


def test_unusable_llm_body_falls_back(monkeypatch, settings, customer, make_ticket):
    settings.LLM_API_KEY = "sk-test"

    def fake_urlopen(request, timeout):
        return _response({"unexpected": True})

    monkeypatch.setattr("tickets.triage.urllib.request.urlopen", fake_urlopen)
    ticket = make_ticket(customer)
    run_triage(ticket.id)
    ticket.refresh_from_db()
    assert ticket.triage_source == Ticket.TriageSource.FALLBACK
    assert ticket.triage_error == "llm response missing message content"


def test_broker_outage_does_not_block_ticket_creation(customer_client, monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr("tickets.signals.triage_ticket.delay", boom)
    response = customer_client.post(
        "/api/tickets/",
        {"title": "Need a hand", "description": "The export button does nothing when I click it."},
        format="json",
    )
    assert response.status_code == 201
