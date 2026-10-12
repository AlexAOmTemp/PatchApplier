"""View layer -- Tk widget construction.

Views never import from app.py: all event handlers and config access
come in as arguments (callbacks dict, config dict). The only dependencies
are Tk itself and pure helpers from presenters.
"""
