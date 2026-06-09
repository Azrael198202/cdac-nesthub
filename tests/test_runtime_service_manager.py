from pathlib import Path

from ai_core.runtime.services.service_manager import RuntimeServiceManager
from auxiliary_brain.studio.service import AgentStudioService


def test_runtime_service_manager_create_start_status(tmp_path: Path):
    manager = RuntimeServiceManager(service_dir=tmp_path / "services", trace_dir=tmp_path / "traces")
    started = {"count": 0}

    def start_handler(configuration):
        started["count"] += 1
        return {"tick_seconds": configuration.get("tick_seconds")}

    manager.register_handler("durable_task_dispatcher", start=start_handler, status=lambda cfg: {"running": True})
    created = manager.create_service(
        service_id="durable_task_dispatcher",
        name="Durable Task Dispatcher",
        service_type="durable_task_dispatcher",
        configuration={"tick_seconds": 3},
    )
    assert created["ok"] is True
    assert created["service"]["status"] == "created"

    started_result = manager.start_service("durable_task_dispatcher")
    assert started_result["ok"] is True
    assert started_result["status"] == "running"
    assert started["count"] == 1
    assert manager.status_service("durable_task_dispatcher")["service"]["runtime_status"]["running"] is True


def test_runtime_service_suggestion_for_recurring_policy(tmp_path: Path):
    manager = RuntimeServiceManager(service_dir=tmp_path / "services", trace_dir=tmp_path / "traces")
    suggestion = manager.suggest_service_for_context({"schedule_policy": {"enabled": True, "mode": "recurring"}})
    assert suggestion
    assert suggestion["kind"] == "runtime_service_suggestion"
    assert suggestion["service_type"] == "durable_task_dispatcher"


def test_agent_studio_routes_runtime_service_commands():
    service = AgentStudioService()
    create = service.router.route("Create runtime service named Durable Task Dispatcher.")
    assert create.action == "create_runtime_service"
    start = service.router.route("Start runtime service Durable Task Dispatcher.")
    assert start.action == "start_runtime_service"
    listing = service.router.route("List runtime services")
    assert listing.action == "list_runtime_services"
