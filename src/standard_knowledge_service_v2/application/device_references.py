"""Resolve references through catalog relations, never by nearest device names."""
import re


def reference_candidates(target, previous, devices, profile, roles):
    known = {device['device_id']: device for device in devices}
    candidates = {previous} if isinstance(previous, str) else set(previous or ())
    candidates &= known.keys()
    requested = {role for role, pattern in roles.items() if re.search(pattern, target)}
    if len(requested) != 1:
        return candidates
    role = next(iter(requested))
    groups = profile.get('groups', {})
    groups = groups.values() if isinstance(groups, dict) else groups
    expanded = {key for key in candidates if known[key]['device_type'] == role}
    for group in groups:
        if group.get('transformer') in candidates and group.get(role) in known:
            expanded.add(group[role])
    if re.search(r'另(?:一)?台|另一个', target) and len(expanded) == 1:
        pool = {key for key, device in known.items() if device['device_type'] == role}
        # The complement is meaningful only when the active scene has two candidates.
        return pool - expanded if len(pool) == 2 else set()
    return expanded
