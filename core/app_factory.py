"""Vue static host with a UI-independent local FastAPI backend."""


def create_app():
    from core.tool_run_logs import cleanup as cleanup_run_logs
    from core.workspace_app import create_workspace_app
    from service.capabilities.capability_packs import recover_existing
    from service.files.conversation_files import cleanup_uploads
    cleanup_run_logs()
    cleanup_uploads()
    recover_existing()
    return create_workspace_app()
