"""FastAPI REST API for the website blocker daemon."""

from .app import create_app
from .deps import set_session_factory
from .routes import blocks, grants, heartbeat, pending, settings, status

# Create the FastAPI app
app = create_app()

# Include all routers
app.include_router(heartbeat.router)
app.include_router(blocks.router)
app.include_router(status.router)
app.include_router(settings.router)
app.include_router(grants.router)
app.include_router(pending.router)

# Export public API
__all__ = ['app', 'set_session_factory']
