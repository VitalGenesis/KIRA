from .registry import register
from self_improvement import self_improve, self_improvement_status, rollback_self_improvement

register(
    "self_improve",
    "Mejora automáticamente módulos no críticos de KIRA, prueba los cambios en una copia aislada y los aplica si pasan. No requiere aprobación del usuario.",
    self_improve,
    {"goal": "string con el objetivo de mejora", "max_files": "number opcional (1-3)", "run_tests": "boolean opcional, por defecto true", "test_timeout": "number opcional"},
    risk="low",
    confirm=False,
)
register(
    "self_improvement_status",
    "Muestra historial reciente, archivos editables y límites del sistema de auto-mejora.",
    self_improvement_status,
    {"limit": "number opcional"},
)
register(
    "self_improvement_rollback",
    "Restaura una copia de seguridad de la última auto-mejora o del backup_id indicado.",
    rollback_self_improvement,
    {"backup_id": "string opcional"},
    risk="medium",
    confirm=False,
)
