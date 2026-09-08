UPDATE trips t
SET status = 'scheduled'
WHERE t.status = 'unassigned'
  AND t.route_id IS NOT NULL
  AND t.vehicle_id IS NOT NULL
  AND t.driver_id IS NOT NULL;

SELECT status,
       count(*) AS total,
       count(*) FILTER (WHERE route_id IS NOT NULL AND vehicle_id IS NOT NULL AND driver_id IS NOT NULL) AS fully_resourced
FROM trips GROUP BY status ORDER BY 2 DESC;