from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from compshare_cli.api import call, collect_pages, download_file, invoke
from compshare_cli.commands.common import confirm_details, request, runtime
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.output import Renderer
from compshare_cli.parsing import compact, money, money_cents, past_timestamp, split_csv, timestamp

app = typer.Typer(help="Manage teams, members, quotas and billing.", no_args_is_help=True)
invite_app = typer.Typer(help="Manage team invitations.", no_args_is_help=True)
member_app = typer.Typer(help="Manage team members.", no_args_is_help=True)
quota_app = typer.Typer(help="Manage team member quotas.", no_args_is_help=True)
billing_app = typer.Typer(help="Inspect and export team billing.", no_args_is_help=True)
app.add_typer(invite_app, name="invite")
app.add_typer(member_app, name="member")
app.add_typer(quota_app, name="quota")
app.add_typer(billing_app, name="billing")

TEAM_COLUMNS = (
    ("Id", "TEAM ID"),
    ("Name", "NAME"),
    ("Description", "DESCRIPTION"),
    ("MemberCount", "MEMBERS"),
)
MEMBER_COLUMNS = (
    ("UserCompanyId", "USER ID"),
    ("VirtualCompanyId", "MEMBER ID"),
    ("RemarkName", "NAME"),
    ("Status", "STATUS"),
    ("AllocateAmountDisplay", "QUOTA"),
    ("AvailableAmountDisplay", "AVAILABLE"),
)
ORDER_COLUMNS = (
    ("OrderNo", "ORDER"),
    ("OrderState", "STATUS"),
    ("ChargeType", "CHARGE"),
    ("Amount", "AMOUNT"),
    ("AmountReal", "PAID"),
    ("ResourceId", "RESOURCE"),
    ("CreateTime", "CREATED"),
)


def _params(ctx: typer.Context, values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {**request(ctx), **compact(values or {})}


def _time_params(start: Optional[str], end: Optional[str]) -> Dict[str, Any]:
    return compact(
        {
            "BeginTime": past_timestamp(start) if start else None,
            "EndTime": timestamp(end) if end else None,
        }
    )


def _member_rows(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw in response.get("TeamRelation") or []:
        row = dict(raw)
        allocated = row.get("AllocateAmount")
        available = row.get("AvailableAmount")
        row["AllocateAmountDisplay"] = (
            f"¥{allocated / 100:.2f}" if isinstance(allocated, int) else allocated
        )
        row["AvailableAmountDisplay"] = (
            f"¥{available / 100:.2f}" if isinstance(available, int) else available
        )
        rows.append(row)
    return rows


@app.command("list", help="List teams created by the current account.")
def list_teams(ctx: typer.Context) -> None:
    invoke(
        runtime(ctx),
        "ListCompShareTeam",
        request(ctx),
        list_key="Teams",
        columns=TEAM_COLUMNS,
    )


@app.command("joined", help="List teams joined by the current account.")
def joined(
    ctx: typer.Context,
    status: Optional[str] = typer.Option(None, help="Filter by membership status."),
) -> None:
    invoke(
        runtime(ctx),
        "ListCompShareTeamJoined",
        _params(ctx, {"Status": status}),
        list_key="JoinedTeams",
        columns=(
            ("TeamId", "TEAM ID"),
            ("TeamName", "NAME"),
            ("VirtualCompanyId", "MEMBER ID"),
            ("Status", "STATUS"),
            ("RemarkName", "REMARK"),
            ("CreateTime", "CREATED"),
        ),
    )


@app.command("show", help="Show team details and members.")
def show(ctx: typer.Context, team: int = typer.Argument(..., help="Team ID.")) -> None:
    state = runtime(ctx)
    response = call(state, "GetCompShareTeamInfo", _params(ctx, {"TeamId": team}))
    if state.json_output:
        Renderer(True, state.show_sensitive).data(response)
        return
    info = response.get("Team") or {}
    Renderer(False, state.show_sensitive).details(
        "Team details",
        [
            ("TEAM ID", info.get("Id") or team),
            ("NAME", info.get("Name")),
            ("DESCRIPTION", info.get("Description")),
            ("MEMBERS", len(response.get("TeamRelation") or [])),
        ],
    )
    Renderer(False, state.show_sensitive).table(_member_rows(response), MEMBER_COLUMNS)


@app.command("create", help="Create a team.")
def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Team name."),
    description: Optional[str] = typer.Option(None, help="Team description."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    confirm_details(
        state,
        "Operation plan",
        [("ACTION", tr("Create team")), ("NAME", name), ("DESCRIPTION", description)],
        "Confirm this operation?",
        yes,
    )
    invoke(
        state,
        "CreateCompShareTeam",
        _params(ctx, {"Name": name, "Description": description}),
        success=tr("Created team {name}", name=name),
    )


@app.command("update", help="Update a team name or description.")
def update(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    name: Optional[str] = typer.Option(None, help="New team name."),
    description: Optional[str] = typer.Option(None, help="New team description."),
) -> None:
    if name is None and description is None:
        raise UsageError(tr("Specify at least one field to update."))
    invoke(
        runtime(ctx),
        "UpdateCompShareTeam",
        _params(ctx, {"TeamId": team, "Name": name, "Description": description}),
        success=tr("Updated team {team}", team=team),
    )


@app.command("delete", help="Permanently delete an empty team.")
def delete(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    state = runtime(ctx)
    confirm_details(
        state,
        "Operation plan",
        [("TEAM ID", team), ("ACTION", tr("Permanently delete team"))],
        "Confirm this operation?",
        yes,
    )
    invoke(
        state,
        "DeleteCompShareTeam",
        _params(ctx, {"TeamId": team}),
        success=tr("Deleted team {team}", team=team),
    )


@invite_app.command("list", help="List team invitations received by the current account.")
def list_invites(ctx: typer.Context) -> None:
    invoke(
        runtime(ctx),
        "ListCompShareTeamInvite",
        request(ctx),
        list_key="Invites",
        columns=(
            ("TeamId", "TEAM ID"),
            ("TeamName", "NAME"),
            ("UserCompanyId", "USER ID"),
            ("Status", "STATUS"),
            ("RemarkName", "REMARK"),
            ("CreateTime", "CREATED"),
        ),
    )


def _invitee(value: str) -> Dict[str, Any]:
    raw_id, separator, remark = value.partition(":")
    try:
        user_id = int(raw_id)
    except ValueError as error:
        raise UsageError(
            tr("Invalid user {value}; use USER_ID or USER_ID:REMARK.", value=value)
        ) from error
    return compact({"UserCompanyId": user_id, "RemarkName": remark if separator else None})


@invite_app.command("send", help="Invite users to a team.")
def send_invites(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    users: List[str] = typer.Argument(..., help="User IDs, optionally USER_ID:REMARK."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    if len(users) > 100:
        raise UsageError(tr("At most 100 users can be invited at once."))
    invitees = [_invitee(value) for value in users]
    state = runtime(ctx)
    confirm_details(
        state,
        "Operation plan",
        [("TEAM ID", team), ("USER ID", [item["UserCompanyId"] for item in invitees])],
        "Confirm this operation?",
        yes,
    )
    response = call(
        state,
        "CreateCompShareTeamRelation",
        _params(ctx, {"TeamId": team, "UserInfo": invitees}),
    )
    errors = response.get("ErrorMap") or {}
    result = {**response, "ok": not errors}
    if errors:
        result["error"] = {
            "code": "partial_failure",
            "message": tr("Some team invitations failed."),
        }
    if state.json_output:
        Renderer(True, state.show_sensitive).data(result)
    elif errors:
        rows = [{"UserCompanyId": user_id, **(detail or {})} for user_id, detail in errors.items()]
        Renderer(False, state.show_sensitive).table(
            rows,
            (("UserCompanyId", "USER ID"), ("Code", "CODE"), ("Message", "MESSAGE")),
        )
    else:
        Renderer(False, state.show_sensitive).success(tr("Sent team invitations"), result)
    if errors:
        raise typer.Exit(1)


def _relation(
    ctx: typer.Context,
    team: int,
    status: str,
    *,
    user: Optional[int] = None,
    remark: Optional[str] = None,
    yes: bool = False,
) -> None:
    state = runtime(ctx)
    confirm_details(
        state,
        "Operation plan",
        [("TEAM ID", team), ("USER ID", user), ("ACTION", status)],
        "Confirm this operation?",
        yes,
    )
    invoke(
        state,
        "SetCompShareTeamRelation",
        _params(
            ctx,
            {
                "TeamId": team,
                "Status": status,
                "UserCompanyId": user,
                "RemarkName": remark,
            },
        ),
        success=tr("Updated team invitation"),
    )


@invite_app.command("accept", help="Accept a team invitation.")
def accept(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    _relation(ctx, team, "Agree", yes=yes)


@invite_app.command("reject", help="Reject a team invitation.")
def reject(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    _relation(ctx, team, "Reject", yes=yes)


@invite_app.command("cancel", help="Cancel a pending team invitation.")
def cancel(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    user: int = typer.Argument(..., help="User company ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    _relation(ctx, team, "Cancel", user=user, yes=yes)


@member_app.command("list", help="List members of a team.")
def list_members(ctx: typer.Context, team: int = typer.Argument(..., help="Team ID.")) -> None:
    state = runtime(ctx)
    response = call(state, "GetCompShareTeamInfo", _params(ctx, {"TeamId": team}))
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=_member_rows(response),
        columns=MEMBER_COLUMNS,
        json_list=True,
        json_fields=(
            "UserCompanyId",
            "VirtualCompanyId",
            "RemarkName",
            "Status",
            "AllocateAmount",
            "AvailableAmount",
        ),
    )


@member_app.command("rename", help="Update a team member remark.")
def rename_member(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    user: int = typer.Argument(..., help="User company ID."),
    name: str = typer.Argument(..., help="Member remark."),
) -> None:
    _relation(ctx, team, "UpdateRemarkName", user=user, remark=name, yes=True)


def _quota(
    ctx: typer.Context,
    team: int,
    members: List[int],
    amount: str,
    operation: str,
    yes: bool,
) -> None:
    parsed = money(amount)
    state = runtime(ctx)
    confirm_details(
        state,
        "Operation plan",
        [
            ("TEAM ID", team),
            ("MEMBER ID", members),
            ("AMOUNT", f"¥{parsed:.2f}"),
            ("ACTION", operation),
        ],
        "Confirm this operation?",
        yes,
    )
    response = call(
        state,
        "SetCompShareTeamAmount",
        _params(
            ctx,
            {
                "TeamId": team,
                "VirtualCompanyId": members,
                "Amount": money_cents(amount),
                "OperateType": operation,
            },
        ),
    )
    failed = response.get("FailedMembers") or {}
    result = {**response, "ok": not failed}
    if failed:
        result["error"] = {
            "code": "partial_failure",
            "message": tr("Some team quota updates failed."),
        }
    Renderer(state.json_output, state.show_sensitive).details(
        "Operation completed",
        [
            ("TEAM ID", team),
            ("MEMBER ID", members),
            ("AMOUNT", f"¥{parsed:.2f}"),
            ("FAILED", response.get("FailedMembers") or {}),
        ],
        response=result,
    )
    if failed:
        raise typer.Exit(1)


@quota_app.command("grant", help="Grant quota to team members.")
def grant(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    members: List[int] = typer.Argument(..., help="Virtual member IDs."),
    amount: str = typer.Option(..., "--amount", help="Amount in CNY."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    _quota(ctx, team, members, amount, "AllocateAmount", yes)


@quota_app.command("reclaim", help="Reclaim quota from team members.")
def reclaim(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    members: List[int] = typer.Argument(..., help="Virtual member IDs."),
    amount: str = typer.Option(..., "--amount", help="Amount in CNY."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    _quota(ctx, team, members, amount, "WithdrawAmount", yes)


def _billing_params(
    ctx: typer.Context,
    team: int,
    member: int,
    start: Optional[str],
    end: Optional[str],
) -> Dict[str, Any]:
    return _params(
        ctx,
        {"TeamId": team, "VirtualCompanyId": member, **_time_params(start, end)},
    )


def _order_sort(value: str) -> str:
    normalized = value.strip().replace("-", "_").casefold()
    aliases = {
        "createtime": "create_time",
        "orderstarttime": "order_start_time",
        "orderendtime": "order_end_time",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"create_time", "order_start_time", "order_end_time"}:
        raise UsageError(tr("--sort must be create_time, order_start_time, or order_end_time."))
    return normalized


@billing_app.command("list", help="List a team member's orders.")
def list_orders(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    member: int = typer.Argument(..., help="Virtual member ID."),
    start: Optional[str] = typer.Option(None, "--start", help="Start time or past duration."),
    end: Optional[str] = typer.Option(None, "--end", help="End time."),
    charge: Optional[List[str]] = typer.Option(None, "--charge", help="Billing type; repeatable."),
    status: Optional[List[str]] = typer.Option(None, "--status", help="Order state; repeatable."),
    resource: Optional[List[str]] = typer.Option(
        None, "--resource", help="Resource ID; repeatable."
    ),
    sort: str = typer.Option("create_time", "--sort", help="Order sort field."),
    ascending: bool = typer.Option(False, "--ascending", help="Sort in ascending order."),
    limit: int = typer.Option(25, min=1, max=100, help="Maximum number of results."),
    offset: int = typer.Option(0, min=0, help="Number of results to skip."),
    all_results: bool = typer.Option(False, "--all", help="Return all results."),
) -> None:
    state = runtime(ctx)
    params = _billing_params(ctx, team, member, start, end)
    params.update(
        compact(
            {
                "ChargeTypes": split_csv(charge or []) or None,
                "OrderStates": split_csv(status or []) or None,
                "ResourceIds": split_csv(resource or []) or None,
                "OrderBy": _order_sort(sort),
                "OrderDir": "ASC" if ascending else "DESC",
            }
        )
    )
    response = collect_pages(
        state,
        "DescribeTeamMemberOrder",
        params,
        "OrderInfos",
        offset=offset,
        limit=None if all_results else limit,
    )
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=response.get("OrderInfos") or [],
        columns=ORDER_COLUMNS,
        json_list=True,
        metadata={"all": all_results},
    )


@billing_app.command("summary", help="Show a team member's order summary.")
def order_summary(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    member: int = typer.Argument(..., help="Virtual member ID."),
    start: Optional[str] = typer.Option(None, "--start", help="Start time or past duration."),
    end: Optional[str] = typer.Option(None, "--end", help="End time."),
) -> None:
    state = runtime(ctx)
    response = call(
        state,
        "DescribeTeamMemberOrderCount",
        _billing_params(ctx, team, member, start, end),
    )
    Renderer(state.json_output, state.show_sensitive).details(
        "Billing summary",
        [
            ("COUNT", response.get("TotalCount")),
            ("AMOUNT", response.get("Amount")),
            ("PAID", response.get("AmountReal")),
            ("FREE", response.get("AmountFree")),
            ("COUPON", response.get("AmountCoupon")),
        ],
        response=response,
    )


@billing_app.command("unpaid", help="List and summarize a team member's unpaid orders.")
def unpaid(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    member: int = typer.Argument(..., help="Virtual member ID."),
    start: Optional[str] = typer.Option(None, "--start", help="Start time or past duration."),
    end: Optional[str] = typer.Option(None, "--end", help="End time."),
    limit: int = typer.Option(25, min=1, max=100, help="Maximum number of results."),
    offset: int = typer.Option(0, min=0, help="Number of results to skip."),
    all_results: bool = typer.Option(False, "--all", help="Return all results."),
) -> None:
    state = runtime(ctx)
    params = _billing_params(ctx, team, member, start, end)
    orders = collect_pages(
        state,
        "DescribeTeamMemberUnpaidOrder",
        params,
        "OrderInfos",
        offset=offset,
        limit=None if all_results else limit,
    )
    summary = call(
        state,
        "DescribeTeamMemberUnpaidOrderCount",
        params,
    )
    response = {"orders": orders, "summary": summary}
    if state.json_output:
        Renderer(True, state.show_sensitive).data(response)
        return
    Renderer(False, state.show_sensitive).details(
        "Unpaid summary",
        [("COUNT", summary.get("TotalCount")), ("AMOUNT", summary.get("Amount"))],
    )
    Renderer(False, state.show_sensitive).table(orders.get("OrderInfos") or [], ORDER_COLUMNS)


@billing_app.command("products", help="List product types used by a team member.")
def products(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    member: int = typer.Argument(..., help="Virtual member ID."),
    start: Optional[str] = typer.Option(None, "--start", help="Start time or past duration."),
    end: Optional[str] = typer.Option(None, "--end", help="End time."),
    status: Optional[List[str]] = typer.Option(None, "--status", help="Order state; repeatable."),
) -> None:
    state = runtime(ctx)
    params = _billing_params(ctx, team, member, start, end)
    params.update(compact({"OrderStates": split_csv(status or []) or None}))
    response = call(state, "ListMemberProductType", params)
    rows = [{"ProductType": item} for item in response.get("ProductTypeList") or []]
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=rows,
        columns=(("ProductType", "PRODUCT"),),
        json_list=True,
    )


@billing_app.command("export", help="Export team orders to a CSV file.")
def export_orders(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    output: Path = typer.Option(..., "--output", help="Destination CSV file."),
    member: int = typer.Option(0, "--member", min=0, help="Virtual member ID; 0 means all."),
    start: Optional[str] = typer.Option(None, "--start", help="Start time or past duration."),
    end: Optional[str] = typer.Option(None, "--end", help="End time."),
    status: Optional[List[str]] = typer.Option(None, "--status", help="Order state; repeatable."),
    force: bool = typer.Option(False, "--force", help="Overwrite the destination file."),
) -> None:
    if output.exists() and not force:
        raise UsageError(
            tr("Destination already exists: {path}. Use --force to overwrite.", path=output)
        )
    state = runtime(ctx)
    content, headers = download_file(
        state,
        "DownloadTeamOrder",
        _params(
            ctx,
            {
                "TeamId": team,
                "VirtualCompanyId": member,
                "OrderStates": split_csv(status or []) or None,
                **_time_params(start, end),
            },
        ),
    )
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
    except OSError as error:
        raise UsageError(
            tr("Unable to write file {path}: {error}", path=output, error=error)
        ) from error
    result = {
        "path": str(output.resolve()),
        "bytes": len(content),
        "content_type": headers.get("Content-Type"),
    }
    Renderer(state.json_output, state.show_sensitive).details(
        "Export completed",
        [("PATH", result["path"]), ("SIZE", result["bytes"])],
        response=result,
    )


@app.command("audit", help="List team operation logs.")
def audit(
    ctx: typer.Context,
    team: int = typer.Argument(..., help="Team ID."),
    start: Optional[str] = typer.Option(None, "--start", help="Start time or past duration."),
    end: Optional[str] = typer.Option(None, "--end", help="End time."),
    operation: Optional[List[str]] = typer.Option(
        None, "--operation", help="Operation type; repeatable."
    ),
    status: Optional[List[str]] = typer.Option(None, "--status", help="Status; repeatable."),
    ascending: bool = typer.Option(False, "--ascending", help="Sort in ascending order."),
    limit: int = typer.Option(25, min=1, max=100, help="Maximum number of results."),
    offset: int = typer.Option(0, min=0, help="Number of results to skip."),
    all_results: bool = typer.Option(False, "--all", help="Return all results."),
) -> None:
    state = runtime(ctx)
    params = _params(
        ctx,
        {
            "TeamId": team,
            "OperateType": split_csv(operation or []) or None,
            "Status": split_csv(status or []) or None,
            "OrderByASC": ascending,
            **_time_params(start, end),
        },
    )
    response = collect_pages(
        state,
        "ListCompShareTeamOperateLog",
        params,
        "Logs",
        offset=offset,
        limit=None if all_results else limit,
    )
    Renderer(state.json_output, state.show_sensitive).data(
        response,
        rows=response.get("Logs") or [],
        columns=(
            ("CreateTime", "CREATED"),
            ("OperateType", "ACTION"),
            ("Status", "STATUS"),
            ("Content", "MESSAGE"),
        ),
        json_list=True,
        metadata={"all": all_results},
    )
