import pytest

from tickets.models import Comment, Tag, Ticket

pytestmark = pytest.mark.django_db


def _open(client, **extra):
    payload = {
        "title": "Invoice looks wrong",
        "description": "There is a duplicate charge on the latest invoice.",
    }
    payload.update(extra)
    return client.post("/api/tickets/", payload, format="json")


def test_customer_sees_only_their_own_tickets(
    customer_client, other_client, other_customer, make_ticket
):
    own = _open(customer_client)
    assert own.status_code == 201
    other = make_ticket(other_customer, title="Bob's private issue")

    listing = customer_client.get("/api/tickets/")
    ids = [row["id"] for row in listing.data["results"]]
    assert own.data["id"] in ids
    assert other.id not in ids

    hidden = customer_client.get(f"/api/tickets/{other.id}/")
    assert hidden.status_code == 404

    sneaky = customer_client.get(f"/api/tickets/?requester={other_customer.id}")
    assert sneaky.data["count"] == 0


def test_agent_sees_every_ticket(agent_client, customer, other_customer, make_ticket):
    first = make_ticket(customer)
    second = make_ticket(other_customer, title="Second customer ticket")
    listing = agent_client.get("/api/tickets/")
    ids = {row["id"] for row in listing.data["results"]}
    assert {first.id, second.id} <= ids


def test_create_ignores_a_forged_requester(customer_client, customer, other_customer):
    response = _open(customer_client, requester=other_customer.id)
    assert response.status_code == 201
    ticket = Ticket.objects.get(pk=response.data["id"])
    assert ticket.requester_id == customer.id
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.triage_status == Ticket.TriageStatus.PENDING


def test_customer_cannot_change_workflow_fields(customer_client, customer, make_ticket, agent):
    ticket = make_ticket(customer)
    response = customer_client.patch(
        f"/api/tickets/{ticket.id}/",
        {"status": Ticket.Status.IN_PROGRESS, "assignee": agent.id, "priority": "urgent"},
        format="json",
    )
    assert response.status_code == 400
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.assignee_id is None


def test_customer_can_edit_an_open_ticket_but_not_a_resolved_one(
    customer_client, customer, make_ticket
):
    ticket = make_ticket(customer)
    updated = customer_client.patch(
        f"/api/tickets/{ticket.id}/",
        {"title": "Printer jam on floor 3"},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.data["title"] == "Printer jam on floor 3"

    ticket.status = Ticket.Status.RESOLVED
    ticket.save(update_fields=["status"])
    blocked = customer_client.patch(
        f"/api/tickets/{ticket.id}/",
        {"title": "Trying again"},
        format="json",
    )
    assert blocked.status_code == 400


def test_internal_notes_are_hidden_from_customers(
    customer_client, agent_client, customer, make_ticket
):
    ticket = make_ticket(customer)
    public = agent_client.post(
        f"/api/tickets/{ticket.id}/comments/",
        {"body": "We are looking into this.", "is_internal": False},
        format="json",
    )
    private = agent_client.post(
        f"/api/tickets/{ticket.id}/comments/",
        {"body": "Account is past due. Do not mention the dunning file.", "is_internal": True},
        format="json",
    )
    assert public.status_code == 201
    assert private.status_code == 201

    detail = customer_client.get(f"/api/tickets/{ticket.id}/")
    bodies = [comment["body"] for comment in detail.data["comments"]]
    assert "We are looking into this." in bodies
    assert all("dunning" not in body for body in bodies)
    assert detail.data["suggested_reply"] is None

    listed = customer_client.get(f"/api/tickets/{ticket.id}/comments/")
    listed_bodies = [comment["body"] for comment in listed.data["results"]]
    assert listed_bodies == ["We are looking into this."]

    agent_view = agent_client.get(f"/api/tickets/{ticket.id}/comments/")
    assert len(agent_view.data["results"]) == 2

    rejected = customer_client.post(
        f"/api/tickets/{ticket.id}/comments/",
        {"body": "secret note", "is_internal": True},
        format="json",
    )
    assert rejected.status_code == 400
    assert Comment.objects.filter(ticket=ticket, is_internal=True).count() == 1


def test_customer_cannot_comment_on_someone_elses_ticket(
    customer_client, other_customer, make_ticket
):
    ticket = make_ticket(other_customer)
    response = customer_client.post(
        f"/api/tickets/{ticket.id}/comments/",
        {"body": "hello"},
        format="json",
    )
    assert response.status_code == 404


def test_agent_can_assign_an_agent_but_not_a_customer(agent_client, customer, agent, make_ticket):
    ticket = make_ticket(customer)
    rejected = agent_client.patch(
        f"/api/tickets/{ticket.id}/",
        {"assignee": customer.id},
        format="json",
    )
    assert rejected.status_code == 400

    assigned = agent_client.patch(
        f"/api/tickets/{ticket.id}/",
        {"assignee": agent.id, "priority": Ticket.Priority.HIGH},
        format="json",
    )
    assert assigned.status_code == 200
    assert assigned.data["assignee"]["username"] == "sam"
    assert assigned.data["priority"] == Ticket.Priority.HIGH


def test_only_admins_can_delete_tickets(agent_client, admin_client, customer, make_ticket):
    ticket = make_ticket(customer)
    assert agent_client.delete(f"/api/tickets/{ticket.id}/").status_code == 403
    assert Ticket.objects.filter(pk=ticket.id).exists()
    assert admin_client.delete(f"/api/tickets/{ticket.id}/").status_code == 204
    assert not Ticket.objects.filter(pk=ticket.id).exists()


def test_tag_permissions(customer_client, agent_client, admin_client):
    denied = customer_client.post("/api/tags/", {"name": "VIP"}, format="json")
    assert denied.status_code == 403

    created = agent_client.post("/api/tags/", {"name": "VIP"}, format="json")
    assert created.status_code == 201
    assert created.data["name"] == "vip"
    assert agent_client.delete(f"/api/tags/{created.data['id']}/").status_code == 403
    assert admin_client.delete(f"/api/tags/{created.data['id']}/").status_code == 204


def test_customer_can_attach_an_existing_tag(customer_client):
    Tag.objects.create(name="billing")
    response = _open(customer_client, tags=["billing"])
    assert response.status_code == 201
    assert response.data["tags"] == ["billing"]

    missing = _open(customer_client, tags=["missing"])
    assert missing.status_code == 400


def test_anonymous_requests_are_rejected(api_client):
    assert api_client.get("/api/tickets/").status_code == 401
    assert api_client.get("/api/tags/").status_code == 401


def test_customer_patch_rejects_a_non_object_body(customer_client, customer, make_ticket):
    ticket = make_ticket(customer)
    response = customer_client.patch(f"/api/tickets/{ticket.id}/", [], format="json")
    assert response.status_code == 400


def test_model_string_forms(customer, make_ticket):
    tag = Tag.objects.create(name="vip")
    ticket = make_ticket(customer)
    comment = Comment.objects.create(ticket=ticket, author=customer, body="hello")
    assert str(customer) == "alice (customer)"
    assert str(tag) == "vip"
    assert str(ticket) == f"#{ticket.pk} Printer jam on floor 2"
    assert str(comment) == f"Comment {comment.pk} on ticket {ticket.pk}"
