"""Active provider registration must retain the public trusted inference facade."""
from types import SimpleNamespace


def test_active_provider_registration_retains_public_llm(monkeypatch, tmp_path):
    import plugins.memory as memory
    import hermes_cli.plugin_isolation as isolation
    from hermes_cli.plugins import PluginContext

    sentinel = object()
    monkeypatch.setattr(PluginContext, "llm", property(lambda self: sentinel))
    registered = []

    def register(ctx):
        provider = SimpleNamespace(llm=ctx.llm)
        registered.append(provider)
        ctx.register_memory_provider(provider)

    module = SimpleNamespace(__file__=str(tmp_path / "synthetic" / "__init__.py"), register=register)
    monkeypatch.setattr(memory, "_load_package", lambda *args: module)
    monkeypatch.setattr(isolation, "user_plugin_host", lambda: None)
    provider = memory._load_provider_from_dir(tmp_path / "synthetic", register_skills=False)
    assert registered, "active provider registration lost public ctx.llm before capture"
    assert provider is registered[0], "loader silently fell back to a bare provider"
    assert provider.llm is sentinel
