import pytest

from cloudpulse import create_app
from cloudpulse.pricing import daily_cost


@pytest.fixture
def client(tmp_path):
    return create_app(str(tmp_path / "test.db")).test_client()


def test_daily_cost_uses_aws_prices():
    # t3.medium is $0.0416/h, plus 30 GB of gp3 at $0.08/GB-month
    assert daily_cost("t3.medium", 30, True) == pytest.approx(0.0416 * 24 + 30 * 0.08 / 30)
    # a stopped instance still pays for its volume
    assert daily_cost("t3.medium", 30, False) == pytest.approx(30 * 0.08 / 30)


def test_health_and_all_pages_render(client):
    assert client.get("/health").get_json() == {"status": "ok"}
    for page in ["/", "/resources", "/resources/1", "/costs", "/budget", "/optimization", "/alerts", "/reports"]:
        assert client.get(page).status_code == 200, page


def test_add_resource_validates_input(client):
    assert client.post("/api/resources", json={"name": "vm", "type": "nope"}).status_code == 400
    assert client.post("/api/resources", json={"name": "", "type": "t3.micro"}).status_code == 400
    r = client.post("/api/resources", json={"name": "new-vm", "type": "t3.micro", "storage_gb": 8})
    assert r.status_code == 201
    added = client.get(f"/api/resources/{r.get_json()['id']}").get_json()
    assert added["name"] == "new-vm" and added["history"]


def test_budget_and_failure_alerts(client):
    assert client.put("/api/budget", json={"amount": -5}).status_code == 400
    assert client.put("/api/budget", json={"amount": 1}).get_json()["status"] == "exceeded"
    categories = {a["category"] for a in client.get("/api/alerts").get_json()}
    assert {"budget", "failure"} <= categories
    assert client.get("/api/overview").get_json()["status"] == "Critical"


def test_optimization_flags_idle_and_stopped_resources(client):
    data = client.get("/api/optimization").get_json()
    assert "batch-worker" in [r["name"] for r in data["underutilized"]]
    assert {"dev-sandbox", "legacy-app"} <= {x["resource"] for x in data["recommendations"]}
    assert data["total_saving"] > 0
