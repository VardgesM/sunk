from app.worker.sources import PollTag


class PollScheduler:
    """One monotonic scheduler; missed periods are skipped, never replayed in a burst."""

    def __init__(self) -> None:
        self.tags: dict[int, PollTag] = {}
        self.next_due: dict[int, float] = {}

    def refresh(self, tags: list[PollTag], now: float) -> set[int]:
        active = {tag.id: tag for tag in tags if tag.enabled}
        changed = {
            identifier
            for identifier in self.tags.keys() | active.keys()
            if self.tags.get(identifier) != active.get(identifier)
        }
        self.next_due = {
            identifier: now if identifier in changed else self.next_due[identifier]
            for identifier in active
        }
        self.tags = active
        return changed

    def due(self, now: float, limit: int = 50) -> list[PollTag]:
        identifiers = sorted(self.next_due, key=lambda identifier: self.next_due[identifier])
        return [
            self.tags[identifier] for identifier in identifiers if self.next_due[identifier] <= now
        ][:limit]

    def completed(self, tag: PollTag, now: float) -> None:
        self.next_due[tag.id] = now + tag.poll_interval_ms / 1000

    def delay(self, now: float, until_refresh: float) -> float:
        next_poll = min(self.next_due.values(), default=until_refresh)
        return max(0.001, min(next_poll, until_refresh) - now)
