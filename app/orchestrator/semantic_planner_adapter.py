from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from config import SEMANTIC_PLANNER_ENABLED, SMART_AUTOMATION_ENABLED
from app.orchestrator.action_plan import ActionPlan

if TYPE_CHECKING:
    from app.orchestrator.automation_context import AutomationContext
    from app.orchestrator.smart_automation_planner import SmartAutomationPlanner

logger = logging.getLogger(__name__)


class SemanticPlannerAdapter:
    """Feature-flagged boundary for semantic planning.

    Phase 4A intentionally keeps this adapter non-executing. When both semantic
    flags are enabled it may ask SmartAutomationPlanner to classify the command,
    but it never returns an executable ActionPlan yet.
    """

    def __init__(
        self,
        *,
        smart_automation_enabled: bool = SMART_AUTOMATION_ENABLED,
        semantic_planner_enabled: bool = SEMANTIC_PLANNER_ENABLED,
        planner_factory: Callable[[], SmartAutomationPlanner] | None = None,
    ) -> None:
        self.smart_automation_enabled = bool(smart_automation_enabled)
        self.semantic_planner_enabled = bool(semantic_planner_enabled)
        self._planner_factory = planner_factory
        self._planner: SmartAutomationPlanner | None = None
        self.last_semantic_result: Any | None = None

    @property
    def enabled(self) -> bool:
        return self.smart_automation_enabled and self.semantic_planner_enabled

    def try_plan_action(self, text: str, context: AutomationContext | None = None) -> ActionPlan | None:
        if not self.enabled:
            return None

        planner = self._get_planner()
        self.last_semantic_result = planner.plan(text, context=context, dry_run=True)
        logger.debug("Semantic planner classified command in dormant mode: %s", self.last_semantic_result.as_dict())
        return None

    def _get_planner(self) -> SmartAutomationPlanner:
        if self._planner is None:
            if self._planner_factory is not None:
                self._planner = self._planner_factory()
            else:
                from app.orchestrator.smart_automation_planner import SmartAutomationPlanner

                self._planner = SmartAutomationPlanner()
        return self._planner
