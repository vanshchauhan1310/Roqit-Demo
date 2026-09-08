path = 'backend/app/workers/trip_assignment_worker.py'
with open(path, encoding='utf-8') as f:
    lines = f.read().split('\n')

for i, l in enumerate(lines):
    stripped = l.strip()
    if stripped.startswith('if status == TripAssignmentStatus') and stripped.endswith('n'):
        lines[i] = '            if status == TripAssignmentStatus.VALID:'

for i, l in enumerate(lines:
    stripped = l.strip()
    if stripped.startswith('print(f"Trip ') and 'already assigned' in stripped:
        lines[i] = '                ' + stripped

for i, l in enumerate(lines:
    stripped = l.strip()
    if stripped.startswith('if validate_trip_assignment') and stripped.endswith('n'):
        lines[i] = '                if validate_trip_assignment(db, trip, ) == TripAssignmentStatus.VALID:'

for i, l in enumerate(lines:
    stripped = l.strip()
    if stripped.startswith('print(f"Trip ') and 'resources backfilled' in stripped:
        lines[i] = '                    ' + stripped

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(lines))
print('FIXED')