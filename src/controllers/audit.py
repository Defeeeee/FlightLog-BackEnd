from litestar import Controller, get, post, Request
from litestar.exceptions import NotFoundException
from supabase import Client
from typing import Any, Dict, List, Optional
from uuid import UUID

from src.auth.guards import auth_guard
from src.models.audit import AuditFinding, AuditSummary, SuppressRequest
from src.services import audit_engine


class AuditController(Controller):
    path = "/audit"
    guards = [auth_guard]

    @get("/summary")
    async def get_summary(self, request: Request, supabase_client: Client) -> AuditSummary:
        """Counts for the nav badge and the 'Salud del logbook' card."""
        user_id = str(request.state.user.id)
        response = (
            supabase_client.table("audit_findings")
            .select("rule_type, severity, suppressed, recalculated_at")
            .eq("user_id", user_id)
            .execute()
        )

        summary = AuditSummary(by_rule={})
        last: Optional[str] = None

        for row in response.data or []:
            stamp = row.get("recalculated_at")
            if stamp and (last is None or stamp > last):
                last = stamp

            if row.get("suppressed"):
                summary.suppressed += 1
                continue

            if row.get("severity") == "critical":
                summary.critical += 1
            else:
                summary.warning += 1

            rule = row.get("rule_type", "otro")
            summary.by_rule[rule] = summary.by_rule.get(rule, 0) + 1

        summary.open_total = summary.critical + summary.warning
        summary.last_recalculated_at = last
        return summary

    @get("/findings")
    async def list_findings(
        self,
        request: Request,
        supabase_client: Client,
        severity: Optional[str] = None,
        rule_type: Optional[str] = None,
        include_suppressed: bool = False,
    ) -> List[AuditFinding]:
        """Findings for the audit page, newest recalculation first."""
        user_id = str(request.state.user.id)
        query = supabase_client.table("audit_findings").select("*").eq("user_id", user_id)

        if not include_suppressed:
            query = query.eq("suppressed", False)
        if severity:
            query = query.eq("severity", severity)
        if rule_type:
            query = query.eq("rule_type", rule_type)

        response = query.order("severity").order("created_at", desc=True).execute()
        return [AuditFinding(**row) for row in response.data or []]

    @post("/findings/{finding_id:uuid}/suppress")
    async def suppress_finding(
        self,
        request: Request,
        supabase_client: Client,
        finding_id: UUID,
        data: SuppressRequest,
    ) -> AuditFinding:
        """
        Silences a finding the pilot has judged to be fine as logged.

        The row stays and keeps being refreshed by every recalculation — it just
        stops counting as open. Deleting it instead would only mean the next
        recalculation recreates it, since the underlying flights are unchanged.
        """
        user_id = str(request.state.user.id)
        update = {
            "suppressed": data.suppressed,
            "suppressed_reason": data.reason if data.suppressed else None,
        }

        response = (
            supabase_client.table("audit_findings")
            .update(update)
            .eq("id", str(finding_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not response.data:
            raise NotFoundException(f"Finding with ID {finding_id} not found")
        return AuditFinding(**response.data[0])

    @post("/recalculate")
    async def recalculate(self, request: Request, supabase_client: Client) -> Dict[str, Any]:
        """
        Re-runs every rule over the pilot's logbook.

        Called automatically after a flight is created, edited or deleted; also
        exposed so the audit page can offer a manual refresh for logbooks that
        predate the engine.
        """
        user_id = str(request.state.user.id)
        return audit_engine.recalculate_for_user(supabase_client, user_id)
