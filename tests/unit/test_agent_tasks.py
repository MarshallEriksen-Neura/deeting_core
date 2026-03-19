from app.tasks import agent as agent_tasks


def test_run_discovery_task_returns_retired_message():
    result = agent_tasks.run_discovery_task(
        "https://example.com/docs",
        capability="chat",
        model_hint="gpt-4o",
        provider_name_hint="ExampleAI",
    )

    assert "legacy provider discovery workflow has been removed" in result
