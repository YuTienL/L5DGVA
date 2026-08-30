from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..agent_profile import AgentProfile

@dataclass
class AgentResult:
    ok: bool
    text: str
    raw: Dict[str, Any]
    session_id: Optional[str] = None
    is_error: bool = False

class ClaudeAdapter:
    def run(self, prompt: str, cwd: str, resume_session: Optional[str] = None,
            agent_profile: "Optional[AgentProfile]" = None) -> AgentResult:
        raise NotImplementedError
