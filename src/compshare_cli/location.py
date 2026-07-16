from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from compshare_cli.api import call
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.runtime import Runtime


def region_from_zone(zone: str) -> str:
    """Derive CompShare's region identifier from a zone identifier."""
    return zone.rsplit("-", 1)[0] if "-" in zone else zone


def supported_locations(state: Runtime) -> list[Dict[str, Any]]:
    response = call(state, "DescribeCompShareSupportZone", {"Region": state.region})
    return list(response.get("ZoneInfo") or [])


def supported_regions(state: Runtime) -> list[str]:
    regions = [str(item["Region"]) for item in supported_locations(state) if item.get("Region")]
    return list(dict.fromkeys([state.region, *regions]))


def candidate_regions(state: Runtime, preferred: Optional[str] = None) -> Iterable[str]:
    if preferred:
        yield preferred
        return
    yield state.region
    for region in supported_regions(state):
        if region != state.region:
            yield region


def locate_instance(
    state: Runtime,
    instance: str,
    *,
    preferred_region: Optional[str] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """Find an instance across supported regions and return region, zone, and details."""
    for region in candidate_regions(state, preferred_region):
        response = call(
            state,
            "DescribeCompShareInstance",
            {"Region": region, "UHostIds": [instance], "Limit": 1, "Offset": 0},
        )
        hosts = response.get("UHostSet") or []
        if hosts:
            host = dict(hosts[0])
            zone = str(host.get("Zone") or state.zone)
            return region, zone, host
    raise UsageError(
        tr(
            "Instance {instance} was not found in any supported region.",
            instance=instance,
        )
    )


def locate_disk(
    state: Runtime,
    disk_id: str,
    *,
    preferred_region: Optional[str] = None,
) -> Tuple[str, str, Optional[Dict[str, Any]], Dict[str, Any]]:
    """Find an attached disk across supported regions."""
    for region in candidate_regions(state, preferred_region):
        offset = 0
        while True:
            response = call(
                state,
                "DescribeCompShareInstance",
                {"Region": region, "Limit": 100, "Offset": offset},
            )
            hosts = response.get("UHostSet") or []
            for host in hosts:
                for disk in host.get("DiskSet") or []:
                    if disk.get("UDiskId") == disk_id or disk.get("DiskId") == disk_id:
                        return region, str(host.get("Zone") or state.zone), host, disk
            if len(hosts) < 100:
                break
            offset += 100
    raise UsageError(
        tr(
            "Attached disk {disk} was not found in any supported region; "
            "pass --zone if it is detached.",
            disk=disk_id,
        )
    )
