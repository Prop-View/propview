"""Publish the active-call gauge used by the GCE worker autoscaler."""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.request import Request, urlopen

logger = logging.getLogger("cloud_monitoring")
METRIC_TYPE = "custom.googleapis.com/propview/active_calls"
METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/"


def _metadata_value(path: str) -> str:
    request = Request(METADATA_URL + path, headers={"Metadata-Flavor": "Google"})
    with urlopen(request, timeout=2) as response:
        return response.read().decode().strip()


def _publish(project_id: str, active_calls: int) -> None:
    from google.api_core.exceptions import GoogleAPICallError
    from google.cloud import monitoring_v3

    try:
        instance_id = _metadata_value("id")
        zone_path = _metadata_value("zone")
        zone = zone_path.rsplit("/", 1)[-1]
        client = monitoring_v3.MetricServiceClient()
        series = monitoring_v3.TimeSeries()
        series.metric.type = METRIC_TYPE
        series.resource.type = "gce_instance"
        series.resource.labels["project_id"] = project_id
        series.resource.labels["instance_id"] = instance_id
        series.resource.labels["zone"] = zone

        point = monitoring_v3.Point()
        point.interval.end_time.GetCurrentTime()
        point.value.int64_value = active_calls
        series.points.append(point)
        client.create_time_series(name=f"projects/{project_id}", time_series=[series])
    except (GoogleAPICallError, OSError, TimeoutError, ValueError):
        logger.exception("Could not publish the active-call metric to Cloud Monitoring")
    finally:
        if "client" in locals():
            client.close()


async def publish_active_calls(active_calls: int) -> None:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID")
    if not project_id:
        return
    await asyncio.to_thread(_publish, project_id, active_calls)


def schedule_active_calls(active_calls: int) -> None:
    task = asyncio.create_task(publish_active_calls(active_calls))

    def report_failure(completed: asyncio.Task[None]) -> None:
        if completed.cancelled():
            return
        error = completed.exception()
        if error is not None:
            logger.error(
                "Active-call metric task failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(report_failure)
