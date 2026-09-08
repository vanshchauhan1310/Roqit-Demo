import io

path = 'backend/app/workers/trip_assignment_worker.py'
with open(path, encoding='utf-8') as f:
    lines = f.read().split('\n')

# 1. Line 118 (index 117): corrupted 'if status == TripAssignmentStatus...'
for i, l in enumerate(lines):
    stripped = l.strip()
    if stripped.startswith('if status == TripAssignmentStatus') and l.strip().endswith('n'):
        lines[i] = '            if status == TripAssignmentStatus.VALID:'

# 2. 'already assigned' print lost its indent
for i, l in enumerate(lines):
    stripped = l.strip()
    if stripped.startswith('print(f"Trip ') and 'already assigned' in stripped:
        lines[i] = '                ' + stripped

# 3. Corrupted validation line (index area of resources backfilled)
for i, l in enumerate(lines:
    stripped = l.strip()
    if stripped.startswith('if validate_trip_assignment') and l.strip().endswith('n'):
        lines[i] = '                if validate_trip_assignment(db, trip) == TripAssignmentStatus.VALID:'

# 4. 'resources backfilled' print lost its indent
for i, l in enumerate(lines:
    stripped = l.strip()
    if stripped.startswith('print(f"Trip ') and 'resources backfilled' in stripped:
        lines[i] = '                    ' + stripped

with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(lines))
print('FIXED')