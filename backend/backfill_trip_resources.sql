UPDATE trips t
SET vehicle_id = r.vehicle_id,
    driver_id  = r.driver_id
FROM routes r
WHERE r.route_id::text = t.route_id
  AND t.vehicle_id IS NULL
  AND r.vehicle_id IS NOT NULL
  AND r.driver_id IS NOT NULL;

SELECT (SELECT count(*) FROM trips WHERE vehicle_id IS NOT NULL AND driver_id IS NOT NULL) AS bounded_trips,
       (SELECT count(*) FROM trips WHERE route_id IS NOT NULL AND (vehicle_id IS NULL OR driver_id IS NULL)) AS still_missing;