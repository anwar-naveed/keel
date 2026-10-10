"""Meta agent watch — P5.1.

A keel agent itself (agents/meta_watch.yaml, tier read_only) that scans
runlogs for drift:
  (a) >= 3 runs, same agent, same error signature, in 24h
  (b) cost > 150% of that agent's 7-day mean
  (c) tool-error rate > 20% over the last 50 runs
Findings land in the `findings` table + a digest is printed.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from keel.runtime.runlog import reconstruct
from keel.runtime.state import RunState, RunStatus


class WatchError(Exception):
    """Base meta-watch error."""


def _ensure_findings_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            agent TEXT NOT NULL,
            detail TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _error_signature(runlog_events) -> str | None:
    """Extract the first tool/decision error text from a run's events."""
    for e in runlog_events:
        if e.type == "tool_result" and e.payload.get("error"):
            return e.payload["error"]
        if e.type == "decision" and e.payload.get("reason"):
            return e.payload["reason"]
    return None


def scan(data_dir: Path, conn, since_hours: int = 24,
         tool_error_threshold: float = 0.20,
         cost_window_days: int = 7) -> list[dict]:
    """Scan runlogs for drift; file findings; return them."""
    _ensure_findings_table(conn)
    findings: list[dict] = []

    now = datetime.now(UTC)
    runs = RunState.list_all(conn)

    # index: agent -> recent failed runs
    by_agent: dict[str, list[RunState]] = {}
    for run in runs:
        by_agent.setdefault(run.agent, []).append(run)

    # (a) repeated failure signature within window
    for agent, agent_runs in by_agent.items():
        recent = [
            r for r in agent_runs
            if r.status == RunStatus.FAILED
            and _parse_ts(r.updated_at) >= now - timedelta(hours=since_hours)
        ]
        if len(recent) < 3:
            continue
        signatures: dict[str, int] = {}
        for r in recent:
            sig = _error_signature(reconstruct(data_dir, r.run_id)) or "unknown"
            signatures[sig] = signatures.get(sig, 0) + 1
        for sig, count in signatures.items():
            if count >= 3:
                findings.append({
                    "kind": "repeated_failure",
                    "agent": agent,
                    "detail": f"{count} failures in {since_hours}h: {sig[:120]}",
                })

    # (b) cost spike vs 7-day mean (from runlog cost events)
    for agent, agent_runs in by_agent.items():
        daily_cost: dict[str, float] = {}
        for r in agent_runs:
            events = reconstruct(data_dir, r.run_id)
            cost = sum(
                e.payload.get("cost_usd", 0.0)
                for e in events if e.type == "cost"
            )
            day = (r.updated_at or r.created_at)[:10]
            daily_cost[day] = daily_cost.get(day, 0.0) + cost
        days = [
            (d, c) for d, c in daily_cost.items()
            if _parse_day(d) >= now - timedelta(days=cost_window_days)
        ]
        if len(days) < 2:
            continue
        latest_day, latest_cost = max(days)
        mean = sum(c for _, c in days) / len(days)
        if mean > 0 and latest_cost > 1.5 * mean:
            findings.append({
                "kind": "cost_spike",
                "agent": agent,
                "detail": (
                    f"{latest_day} cost ${latest_cost:.4f} is "
                    f"{latest_cost / mean:.1f}x the {cost_window_days}-day "
                    f"mean ${mean:.4f}"
                ),
            })

    # (c) tool-error rate over the last 50 runs
    last50 = runs[:50]
    tool_calls = 0
    tool_errors = 0
    for r in last50:
        for e in reconstruct(data_dir, r.run_id):
            if e.type == "tool_result":
                tool_calls += 1
                if e.payload.get("error"):
                    tool_errors += 1
    if tool_calls >= 5 and tool_errors / tool_calls > tool_error_threshold:
        findings.append({
            "kind": "tool_error_rate",
            "agent": "*",
            "detail": (
                f"tool-error rate {tool_errors}/{tool_calls} = "
                f"{tool_errors / tool_calls:.0%} exceeds "
                f"{tool_error_threshold:.0%} over last {len(last50)} runs"
            ),
        })

    # file findings
    for f in findings:
        conn.execute(
            "INSERT INTO findings (ts, kind, agent, detail) "
            "VALUES (?, ?, ?, ?)",
            (now.isoformat(), f["kind"], f["agent"], f["detail"]),
        )
    conn.commit()
    return findings


def digest(findings: list[dict]) -> str:
    """Human-readable one-screen digest."""
    if not findings:
        return "meta watch: no drift detected."
    lines = [f"meta watch: {len(findings)} finding(s)"]
    for f in findings:
        lines.append(f"  [{f['kind']}] {f['agent']}: {f['detail']}")
    return "\n".join(lines)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts) if ts else datetime.now(UTC)


def _parse_day(day: str) -> datetime:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)  # noqa: SIM


def run_meta_watch(data_dir: Path, conn) -> str:
    """Entry: scan + file + digest."""
    return digest(scan(data_dir, conn))


__all__ = ["scan", "digest", "run_meta_watch", "WatchError"]
