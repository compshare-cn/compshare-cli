from __future__ import annotations

from enum import Enum

from compshare_cli.i18n import tr
from compshare_cli.insights import submit_feedback
from compshare_cli.output import Renderer
from compshare_cli.runtime import Runtime


class FeedbackCategory(str, Enum):
    bug = "bug"
    suggest = "suggest"


def run(state: Runtime, category: FeedbackCategory, message: str) -> None:
    response = submit_feedback(category.value, message)
    Renderer(state.json_output, state.show_sensitive).success(
        tr("Thank you for your feedback."), response
    )
