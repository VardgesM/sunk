"""Group due tags only; never bridge unconfigured address gaps."""
from app.worker.decoder import register_count
from app.worker.sources import PollTag


def read_groups(tags: list[PollTag]) -> list[list[PollTag]]:
    groups: list[list[PollTag]] = []
    for tag in sorted(tags, key=lambda t: (
        t.transport.id, t.device_id, t.slave_id, t.register_type, t.address, t.id
    )):
        width = 1 if tag.data_type == "bool" else register_count(tag.data_type)
        limit = 2000 if tag.register_type in ("coil", "discrete_input") else 125
        if groups:
            group = groups[-1]
            first = group[0]
            end = max(t.address + (1 if t.data_type == "bool" else register_count(t.data_type))
                      for t in group)
            same = (tag.transport == first.transport and tag.device_id == first.device_id
                    and tag.slave_id == first.slave_id
                    and tag.register_type == first.register_type)
            if same and tag.address <= end and max(end, tag.address + width) - first.address <= limit:
                group.append(tag)
                continue
        groups.append([tag])
    return groups
