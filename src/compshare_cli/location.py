from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from compshare_cli.api import call
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr
from compshare_cli.runtime import Runtime


def supported_locations(
    state: Runtime,
    request_region: Optional[str] = None,
) -> list[Dict[str, Any]]:
    params = {"Region": request_region} if request_region is not None else {}
    response = call(state, "DescribeCompShareSupportZone", params)
    return list(response.get("ZoneInfo") or [])


def instance_location(host: Dict[str, Any], instance: Optional[str] = None) -> Tuple[str, str]:
    """Return the location reported by DescribeCompShareInstance without inventing defaults."""
    region = host.get("Region")
    zone = host.get("Zone")
    if region and zone:
        return str(region), str(zone)
    identifier = instance or str(host.get("UHostId") or "")
    raise UsageError(
        tr(
            "DescribeCompShareInstance did not return Region and Zone for instance {instance}.",
            instance=identifier,
        )
    )


def locate_instance(
    state: Runtime,
    instance: str,
    *,
    request_region: Optional[str] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """Find an instance and return the Region and Zone reported by the API."""
    params: Dict[str, Any] = {"UHostIds": [instance], "Limit": 1, "Offset": 0}
    if request_region is not None:
        params["Region"] = request_region
    response = call(state, "DescribeCompShareInstance", params)
    hosts = response.get("UHostSet") or []
    host = next(
        (dict(item) for item in hosts if str(item.get("UHostId") or "") == instance),
        None,
    )
    if host is not None:
        region, zone = instance_location(host, instance)
        return region, zone, host
    raise UsageError(tr("Instance {instance} was not found.", instance=instance))


def locate_disk(
    state: Runtime,
    disk_id: str,
    *,
    request_region: Optional[str] = None,
) -> Tuple[str, str, Optional[Dict[str, Any]], Dict[str, Any]]:
    """Find an attached disk and use only the location reported for its instance."""
    offset = 0
    while True:
        params: Dict[str, Any] = {"Limit": 100, "Offset": offset}
        if request_region is not None:
            params["Region"] = request_region
        response = call(state, "DescribeCompShareInstance", params)
        hosts = response.get("UHostSet") or []
        for raw_host in hosts:
            host = dict(raw_host)
            for disk in host.get("DiskSet") or []:
                if disk.get("UDiskId") == disk_id or disk.get("DiskId") == disk_id:
                    region, zone = instance_location(host)
                    return region, zone, host, disk
        if len(hosts) < 100:
            break
        offset += 100
    raise UsageError(
        tr(
            "Attached disk {disk} was not found; pass --region and --zone if it is detached.",
            disk=disk_id,
        )
    )
