"""Small cross-cutting helpers shared by services and the UI:

- core.clock:  a single source of truth for "what time is it right now"
- core.events: a lightweight in-app signal so the UI can react instantly
               whenever data changes anywhere in the system
"""
