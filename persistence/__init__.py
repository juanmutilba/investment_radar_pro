"""Capa de persistencia. SQLite es el backend oficial para módulos nuevos (cartera, métricas de scan)."""

from persistence.sqlite import default_db_path, get_connection, init_database

__all__ = ["default_db_path", "get_connection", "init_database"]
